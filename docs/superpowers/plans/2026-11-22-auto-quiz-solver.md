# Auto Quiz Solver (Offline OCR & Database) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Xây dựng phần mềm Python tự động chụp màn hình, nhận diện câu hỏi trắc nghiệm ôn thi bằng lái xe qua OCR, tra cứu đáp án chuẩn trong ngân hàng dữ liệu offline 600 câu hỏi, và dùng OpenCV + PyAutoGUI tự động click đáp án và bấm nút "Tiếp" chuyển câu.

**Architecture:** Kiến trúc module hóa tách biệt:
1. `data/questions.json`: Lưu trữ ngân hàng câu hỏi & đáp án chuẩn.
2. `src/matcher.py`: Xử lý so khớp mờ văn bản OCR với database câu hỏi bằng `rapidfuzz`.
3. `src/detector.py`: Xử lý thị giác máy tính với `opencv-python` để định vị nút radio và nút "Tiếp".
4. `src/ocr_engine.py`: Xử lý nhận dạng chữ offline siêu tốc qua `rapidocr-onnxruntime`.
5. `main.py`: Điều khiển luồng tự động hóa với `pyautogui`, cơ chế ngắt an toàn và thông báo khi hoàn thành.

**Tech Stack:** Python 3.11, `rapidocr-onnxruntime`, `rapidfuzz`, `opencv-python`, `numpy`, `pyautogui`, `pillow`, `pytest`.

**Spec:** [docs/superpowers/specs/2026-11-22-auto-quiz-solver-design.md](file:///D:/test/a/docs/superpowers/specs/2026-11-22-auto-quiz-solver-design.md)

## Global Constraints
- Hệ điều hành: Windows 10/11, Python 3.11.
- Không sử dụng API ngoài (100% offline, miễn phí).
- Không tự động nộp bài: Dừng an toàn khi hoàn thành câu 182 / không thấy nút "Tiếp".
- Failsafe khẩn cấp: PyAutoGUI FailSafe (rê chuột góc màn hình) và phím tắt thoát.

## Review Focus
1. Tỷ lệ nhận diện OCR có thể bị nhiễu do hình ảnh biển báo xen kẽ: bộ so khớp `rapidfuzz` phải lọc và so khớp theo `token_set_ratio` với ngưỡng tin cậy >= 70%.
2. Tọa độ radio buttons phải được sắp xếp chặt chẽ theo trục Y tăng dần để không click nhầm thứ tự đáp án (1, 2, 3...).
3. Nút "Tiếp" có thể bị mờ hoặc disabled: OpenCV template matching phải kiểm tra ngưỡng tương đồng >= 0.8.
4. Trường hợp không tìm thấy đáp án khớp: bot phải tạm dừng và cảnh báo thay vì click bừa bãi.
5. Zoom màn hình: Khuyến cáo chạy ở tỷ lệ zoom 80-90% để toàn bộ nút "Tiếp" và câu hỏi nằm trong viewport.

---

### Task 1: Thiết Lập Môi Trường & Ngân Hàng Dữ Liệu Câu Hỏi
**Files:**
- Create: `requirements.txt`
- Create: `data/questions.json`
- Test: `tests/test_data.py`

**Interfaces:**
- Produces: `data/questions.json` chứa danh sách câu hỏi: `[{"id": int, "question": str, "answers": list[str], "correct": int}]`

- [ ] **Step 1: Viết test kiểm tra tính toàn vẹn của file dữ liệu câu hỏi**
```python
def test_questions_data_format():
    import json, os
    assert os.path.exists("data/questions.json")
    with open("data/questions.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) > 0
    q = data[0]
    assert "question" in q and "answers" in q and "correct" in q
    assert isinstance(q["correct"], int)
```
- [ ] **Step 2: Chạy test để xác nhận FAIL**
Run: `pytest tests/test_data.py`
- [ ] **Step 3: Tạo `requirements.txt` và nạp bộ dữ liệu 600 câu hỏi (trọng tâm 182 câu biển báo) vào `data/questions.json`**
- [ ] **Step 4: Chạy lại test để xác nhận PASS**
- [ ] **Step 5: Commit**

---

### Task 2: Module So Khớp Văn Bản (Fuzzy Matcher)
**Files:**
- Create: `src/matcher.py`
- Test: `tests/test_matcher.py`

**Interfaces:**
- Consumes: `data/questions.json`
- Produces: `find_best_match(ocr_text: str, questions: list[dict], threshold: float = 70.0) -> dict | None`
  Trả về `{"id": int, "correct": int, "score": float}` nếu tìm thấy, hoặc `None` nếu dưới ngưỡng.

- [ ] **Step 1: Viết failing test cho `find_best_match`**
```python
def test_find_best_match_sample_question():
    from src.matcher import find_best_match
    questions = [{
        "id": 1,
        "question": "Hai biển này có ý nghĩa gì?",
        "answers": [
            "Để chỉ nơi đường sắt giao vuông góc với đường bộ không có rào chắn.",
            "Để báo trước sắp đến vị trí giao cắt đường bộ với đường sắt cùng mức, không vuông góc và không có người gác, không có rào chắn.",
            "Nơi đường sắt giao nhau với đường bộ."
        ],
        "correct": 2
    }]
    ocr_sample = "1. Câu hỏi chọn một đáp án Hai biển này có ý nghĩa gì? 1- Để chỉ nơi đường sắt giao vuông góc 2- Để báo trước sắp đến vị trí giao cắt 3- Nơi đường sắt"
    match = find_best_match(ocr_sample, questions)
    assert match is not None
    assert match["id"] == 1
    assert match["correct"] == 2
```
- [ ] **Step 2: Chạy test để xác nhận FAIL**
- [ ] **Step 3: Triển khai `find_best_match` trong `src/matcher.py` dùng `rapidfuzz`**
- [ ] **Step 4: Chạy test để xác nhận PASS**
- [ ] **Step 5: Commit**

---

### Task 3: Trích Xuất Template & Module Nhận Diện OpenCV
**Files:**
- Create: `assets/btn_next.png`
- Create: `assets/radio_unselected.png`
- Create: `src/detector.py`
- Test: `tests/test_detector.py`

**Interfaces:**
- Consumes: Ảnh màn hình (numpy array / OpenCV BGR image)
- Produces:
  - `find_next_button(image, template, threshold=0.8) -> tuple[int, int] | None`: Tọa độ tâm (X, Y) của nút "Tiếp".
  - `find_radio_buttons(image, template=None, min_radius=10, max_radius=30) -> list[tuple[int, int]]`: Danh sách tọa độ tâm các nút radio sắp xếp theo $Y$ tăng dần.

- [ ] **Step 1: Viết script trích xuất `btn_next.png` và `radio_unselected.png` từ `sample.png`**
- [ ] **Step 2: Viết test kiểm tra detector trên chính ảnh mẫu `sample.png`**
```python
def test_detect_next_button_on_sample():
    import cv2
    from src.detector import find_next_button
    img = cv2.imread("sample.png")
    pos = find_next_button(img)
    assert pos is not None
    x, y = pos
    assert 1400 < x < 1600 and 800 < y < 900  # Nút Tiếp ở góc dưới bài thi

def test_detect_radio_buttons_on_sample():
    import cv2
    from src.detector import find_radio_buttons
    img = cv2.imread("sample.png")
    radios = find_radio_buttons(img)
    assert len(radios) == 3
    # Đảm bảo sắp xếp Y tăng dần
    assert radios[0][1] < radios[1][1] < radios[2][1]
```
- [ ] **Step 3: Triển khai `src/detector.py`**
- [ ] **Step 4: Chạy test để xác nhận PASS**
- [ ] **Step 5: Commit**

---

### Task 4: Module Nhận Dạng OCR Offline
**Files:**
- Create: `src/ocr_engine.py`
- Test: `tests/test_ocr_engine.py`

**Interfaces:**
- Produces: `extract_text_from_image(image_cv2) -> str`

- [ ] **Step 1: Viết test kiểm tra OCR đọc được câu hỏi từ vùng bài thi trong `sample.png`**
```python
def test_ocr_extracts_question_text():
    import cv2
    from src.ocr_engine import extract_text_from_image
    img = cv2.imread("sample.png")
    # Crop vùng câu hỏi
    h, w, _ = img.shape
    quiz_crop = img[int(h*0.2):int(h*0.85), int(w*0.2):int(w*0.8)]
    text = extract_text_from_image(quiz_crop)
    assert "Hai biển này có ý nghĩa gì" in text or "giao vuông góc" in text
```
- [ ] **Step 2: Triển khai `src/ocr_engine.py` dùng `rapidocr_onnxruntime`**
- [ ] **Step 3: Chạy test để xác nhận PASS**
- [ ] **Step 4: Commit**

---

### Task 5: Tích Hợp Vòng Lặp Tự Động Hóa (Automation Loop & CLI)
**Files:**
- Create: `src/solver.py`
- Create: `main.py`
- Test: `tests/test_solver_integration.py`

**Interfaces:**
- `AutoSolver(questions_path, assets_dir)`:
  - `solve_single_step(screenshot) -> bool`: Chụp $\rightarrow$ OCR $\rightarrow$ Match $\rightarrow$ Click Radio $\rightarrow$ Click Tiếp.
  - `run()`: Vòng lặp với thời gian chờ, phím dừng khẩn cấp và thông báo hoàn thành.

- [ ] **Step 1: Viết test integration mô phỏng 1 lượt giải trên `sample.png`**
- [ ] **Step 2: Triển khai `src/solver.py` và `main.py`**
- [ ] **Step 3: Kiểm tra hoàn chỉnh luồng chạy và verify**
- [ ] **Step 4: Commit**
