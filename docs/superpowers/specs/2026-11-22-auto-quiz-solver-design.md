# Thiết Kế: Phần Mềm Tự Động Hóa Giải Trắc Nghiệm Bằng OCR & Ngân Hàng Dữ Liệu 600 Câu Hỏi (Offline)

## 1. Mục Đích & Bối Cảnh (Intent & Why)
Người dùng muốn phần mềm Python tự động hóa ôn luyện trắc nghiệm trực tuyến (ví dụ bài thi biển báo giao thông trong `sample.png`) mà **không dùng AI Gemini**.
Phần mềm sẽ:
- Tự động chụp màn hình câu hỏi.
- Dùng thư viện OCR offline (như `rapidocr-onnxruntime` hoặc `easyocr`) để đọc văn bản câu hỏi và các phương án.
- Tra cứu đối chiếu với **Ngân hàng dữ liệu 600 câu hỏi thi GPLX chuẩn** (lưu dạng file JSON offline trong project) để lấy ra đáp án đúng 100%.
- Sử dụng OpenCV nhận diện chính xác vị trí nút radio đáp án tương ứng và nút "Tiếp".
- Dùng PyAutoGUI click chọn đáp án và click "Tiếp" để sang câu kế tiếp.
- Dừng lại an toàn khi hoàn thành để người dùng tự nhấn "Kết thúc luyện thi" thủ công.

---

## 2. Mục Tiêu & Giới Hạn (Goals, Non-Goals, Anti-Goals)

### Goals
- **100% Offline & Miễn phí:** Không phụ thuộc API bên ngoài, không cần API Key, không tốn phí, không sợ hết quota.
- **Tốc độ xử lý cực nhanh:** OCR offline + tìm kiếm trong JSON chỉ mất ~0.2 - 0.5s/câu.
- **Độ chính xác tuyệt đối:** Sử dụng thuật toán so khớp mờ (Fuzzy Matching) giữa văn bản OCR đọc được và câu hỏi + danh sách đáp án trong database 600 câu chuẩn của Bộ GTVT.
- **Nhận diện tọa độ click chính xác 100% (OpenCV):**
  - OpenCV tìm danh sách các nút radio tròn (`1-`, `2-`, `3-`, `4-`) từ trên xuống dưới.
  - Template matching tìm nút màu xanh "Tiếp".
- **Cơ chế an toàn:**
  - Fail-safe di chuột vào góc màn hình hoặc phím tắt `q` để dừng khẩn cấp.
  - Dừng lại khi không còn câu mới hoặc hết 182 câu, phát chuông báo để người dùng nộp bài thủ công.

### Non-Goals
- Không can thiệp sửa đổi backend hay can thiệp DOM trang web LMS.
- Không tự động bấm nút "Kết thúc luyện thi" (theo yêu cầu của người dùng để nộp bài thủ công).

### Anti-Goals
- Không click khi tỷ lệ so khớp câu hỏi quá thấp (dưới ngưỡng tin cậy).
- Không click lệch vị trí nút bấm.

---

## 3. Ràng Buộc & Công Nghệ (Tech Stack & Constraints)
- **Hệ điều hành:** Windows (Python 3.11).
- **Thư viện chính:**
  - `rapidocr-onnxruntime` (nhẹ, nhanh, không cần cài tesseract binary ngoài, nhận diện tiếng Việt cực chuẩn).
  - `rapidfuzz` (thư viện fuzzy matching C++ siêu nhanh trong Python).
  - `opencv-python` & `numpy` (nhận diện hình ảnh nút radio và nút "Tiếp").
  - `pyautogui` & `pillow` (chụp màn hình, click chuột).
- Cửa sổ trình duyệt cần hiển thị trên màn hình khi bot chạy, khuyến nghị zoom 80% - 90% để không bị tràn màn hình.

---

## 4. Kiến Trúc Dữ Liệu & Quy Trình Hoạt Động (Architecture & Workflow)

### Cấu trúc dữ liệu (`data/questions.json`)
```json
[
  {
    "id": 1,
    "question": "Hai biển này có ý nghĩa gì?",
    "answers": [
      "Để chỉ nơi đường sắt giao vuông góc với đường bộ không có rào chắn.",
      "Để báo trước sắp đến vị trí giao cắt đường bộ với đường sắt cùng mức, không vuông góc và không có người gác, không có rào chắn.",
      "Nơi đường sắt giao nhau với đường bộ."
    ],
    "correct": 2
  }
]
```

### Quy trình từng câu:
1. **Chụp ảnh:** Chụp vùng câu hỏi hoặc toàn màn hình trình duyệt.
2. **OCR:** Trích xuất các dòng chữ câu hỏi và các đáp án trên màn hình.
3. **Tra cứu:** Tính điểm tương đồng (Fuzzy Match score) giữa đoạn text nhận dạng được với câu hỏi và các phương án trong database. Chọn ra bản ghi câu hỏi khớp nhất ($> 80\%$ confidence) $\rightarrow$ lấy ra số thứ tự đáp án đúng `correct_answer_index` (1, 2, 3...).
4. **Định vị nút radio (OpenCV):**
   - Quét tìm tất cả các nút radio trên màn hình, sắp xếp theo tọa độ $Y$ từ trên xuống dưới.
   - Chọn nút thứ `correct_answer_index`.
5. **Click đáp án:** PyAutoGUI click vào tâm của radio button đó.
6. **Định vị & Click nút "Tiếp":** OpenCV tìm template nút "Tiếp" (`assets/btn_next.png`), PyAutoGUI click vào nút "Tiếp".
7. **Nghỉ & Lặp lại:** Nghỉ 1s chờ trang tải câu mới. Nếu không tìm thấy nút "Tiếp" (hết câu), dừng bot và phát âm thanh thông báo.

---

## 5. Việc Dành Cho Builder (Left to the Builder)
- Chuẩn bị file dữ liệu ngân hàng 600 câu hỏi `data/questions.json` (đặc biệt là 182 câu hỏi phần biển báo đường bộ).
- Cắt và lưu template mẫu nút "Tiếp" và radio button vào thư mục `assets/`.
- Cài đặt thuật toán so khớp `rapidfuzz` với ngưỡng tin cậy an toàn.
- Cài đặt bộ điều khiển OpenCV template matching và PyAutoGUI click.
- Viết file chạy chính `main.py` có giao diện console hiển thị tiến độ và phím tắt điều khiển.
