# Auto Quiz Tool - Tự Động Làm Trắc Nghiệm Bằng Lái Xe (600 Câu)

Tool Python tự động chụp màn hình, nhận diện câu hỏi từ trang web thi/luyện thi trực tuyến (như LMS HueLMS), đối chiếu với ngân hàng 600 câu hỏi trong `data/questions.json`, tự động click chọn đáp án đúng và click nút **Tiếp**.

---

## 🛡️ Chế độ giả lập người thật (Anti-Bot / Chống Detect)

Để tránh bị hệ thống LMS hoặc giám sát thi trực tuyến phát hiện việc dùng bot/tool tự động:
1. **Delay ngẫu nhiên giữa các thao tác**:
   - Thời gian đọc đề & suy nghĩ: **1.8s - 3.6s** (ngẫu nhiên).
   - Thời gian xem lại phản hồi sau khi chọn đáp án: **2.0s - 3.8s** (ngẫu nhiên).
   - Thời gian chờ chuyển câu: **2.2s - 4.2s** (ngẫu nhiên).
2. **Di chuyển chuột mượt mà (Human Smooth Motion)**:
   - Con trỏ chuột lướt tự nhiên theo đường cong quán tính (`easeOutQuad`) trong khoảng 0.25s - 0.45s thay vì dịch chuyển tức thời.
3. **Rung tọa độ click (Random Jitter)**:
   - Tọa độ click được cộng/trừ ngẫu nhiên $\pm 2$ đến $4$ pixel trong phạm vi nút, không bao giờ click trùng vào 1 tọa độ lặp lại.
4. **Tự động bấm "Kết thúc luyện thi"**:
   - Tự động nhận diện khi hoàn thành câu hỏi cuối cùng (ví dụ `182/182`) và bấm nút nộp bài.

---

## ⌨️ Phím tắt toàn cục (Hotkeys)

| Phím tắt | Chức năng |
| :--- | :--- |
| **`F8`** | Giải **1 câu** hiện tại (Giả lập người thật đọc đề, chọn đáp án, bấm Tiếp) |
| **`F9`** | **Bắt đầu / Tạm dừng** chế độ tự động liên tục |
| **`F10`** | **Dừng hẳn** quá trình tự động |
| **Góc màn hình (0,0)** | Rê chuột vào góc trên cùng bên trái màn hình để **dừng khẩn cấp** |

---

## 📖 Hướng dẫn sử dụng

### 1. Mở giao diện điều khiển (Khuyên dùng)
```bash
python auto_quiz.py
```
> Bạn có thể chọn trực tiếp 3 mức tốc độ trên giao diện:
> - **🐢 Người thật (Chống detect)**: 2.5s - 5.0s (Khuyên dùng).
> - **🐇 Vừa phải**: 1.5s - 2.5s.
> - **⚡ Nhanh**: 0.6s - 1.2s.

### 2. Chạy từ dòng lệnh với chế độ người thật
```bash
python auto_quiz.py --auto --mode human
```

### 3. Tự chỉnh khoảng delay ngẫu nhiên theo ý muốn:
```bash
python auto_quiz.py --auto --delay-read 2.0 4.0 --delay-ans 2.5 5.0 --delay-next 3.0 6.0
```
- `--delay-read MIN MAX`: Thời gian đọc đề trước khi click.
- `--delay-ans MIN MAX`: Thời gian xem đáp án trước khi bấm Tiếp.
- `--delay-next MIN MAX`: Thời gian chờ tải câu mới.
