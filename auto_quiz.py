"""
auto_quiz.py - Tool tự động nhận diện câu hỏi, chọn đáp án đúng và bấm 'Tiếp'
TÍCH HỢP CHẾ ĐỘ GIẢ LẬP HÀNH VI NGƯỜI THẬT (ANTI-BOT / CHỐNG DETECT):
1. Delay ngẫu nhiên giữa các thao tác (đọc câu hỏi, xem đáp án, chuyển câu).
2. Chuột di chuyển mượt mà (smooth curve + easeOutQuad) thay vì dịch chuyển tức thời.
3. Rung tọa độ chuột (jitter ngẫu nhiên vài pixel) để không bao giờ click trùng tọa độ cũ.
4. Tự động nhận diện câu cuối cùng và bấm 'Kết thúc luyện thi'.
"""

import sys
import os
import time
import random
import argparse
import threading
import ctypes
from typing import Optional, Tuple
import numpy as np
import pyautogui
import mss
from quiz_solver import QuizSolver

# Cấu hình an toàn cho PyAutoGUI: Di chuyển chuột vào góc trên-trái màn hình (0, 0) để dừng khẩn cấp
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

def enable_windows_dpi_awareness():
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

enable_windows_dpi_awareness()


def human_click(
    x: int,
    y: int,
    jitter: int = 4,
    smooth: bool = True,
    duration_range: Tuple[float, float] = (0.25, 0.45)
):
    """
    Giả lập cú click chuột của người thật:
    - Thêm độ lệch ngẫu nhiên vài pixel (jitter) để không bao giờ click vào đúng 1 pixel cố định.
    - Di chuyển chuột mượt mà (easeOutQuad) trong khoảng thời gian ngẫu nhiên.
    - Nghỉ một nhịp micro-pause (50-150ms) trước khi nhấn chuột xuống.
    """
    target_x = x + random.randint(-jitter, jitter)
    target_y = y + random.randint(-jitter, jitter)

    if smooth:
        move_time = random.uniform(duration_range[0], duration_range[1])
        pyautogui.moveTo(target_x, target_y, duration=move_time, tween=pyautogui.easeOutQuad)
    else:
        pyautogui.moveTo(target_x, target_y)

    time.sleep(random.uniform(0.06, 0.14))
    pyautogui.click()


def sleep_random(min_sec: float, max_sec: float, label: str = "") -> float:
    """Nghỉ ngẫu nhiên giữa min_sec và max_sec để chống bị nhận diện là bot."""
    if min_sec >= max_sec:
        wait_time = round(min_sec, 2)
    else:
        wait_time = round(random.uniform(min_sec, max_sec), 2)
    if label:
        print(f"   ⏳ [{label}] Nghỉ ngẫu nhiên {wait_time}s...")
    time.sleep(wait_time)
    return wait_time


class AutoQuizController:
    # Các profile tốc độ
    PROFILES = {
        "human": {
            "name": "Người thật (Chống detect)",
            "read_range": (1.8, 3.6),       # Thời gian giả lập đọc đề câu hỏi
            "answer_range": (2.0, 3.8),     # Thời gian giả lập xem phản hồi/giải thích
            "next_range": (2.2, 4.2),       # Thời gian chờ câu mới load
            "smooth_mouse": True,
            "jitter": 4
        },
        "medium": {
            "name": "Vừa phải",
            "read_range": (0.8, 1.5),
            "answer_range": (1.0, 1.8),
            "next_range": (1.2, 2.0),
            "smooth_mouse": True,
            "jitter": 3
        },
        "fast": {
            "name": "Nhanh",
            "read_range": (0.2, 0.4),
            "answer_range": (0.5, 0.8),
            "next_range": (0.8, 1.2),
            "smooth_mouse": False,
            "jitter": 1
        }
    }

    def __init__(
        self,
        db_path: str = "data/questions.json",
        profile: str = "human",
        custom_read_range: Optional[Tuple[float, float]] = None,
        custom_answer_range: Optional[Tuple[float, float]] = None,
        custom_next_range: Optional[Tuple[float, float]] = None,
        on_status_change = None,
        on_question_solved = None
    ):
        self.db_path = db_path
        self.set_profile(profile)

        # Ghi đè nếu có cấu hình custom
        if custom_read_range:
            self.read_range = custom_read_range
        if custom_answer_range:
            self.answer_range = custom_answer_range
        if custom_next_range:
            self.next_range = custom_next_range

        self.on_status_change = on_status_change
        self.on_question_solved = on_question_solved

        self.solver = QuizSolver(db_path=self.db_path)
        self.is_running = False
        self.is_paused = False
        self.worker_thread = None

        self.total_solved = 0
        self.last_solved_id = -1
        self.repeat_count = 0

    def set_profile(self, profile_name: str):
        """Thay đổi cấu hình độ trễ."""
        p = self.PROFILES.get(profile_name, self.PROFILES["human"])
        self.profile_name = profile_name
        self.read_range = p["read_range"]
        self.answer_range = p["answer_range"]
        self.next_range = p["next_range"]
        self.smooth_mouse = p["smooth_mouse"]
        self.jitter = p["jitter"]

    def capture_screen(self) -> np.ndarray:
        """Chụp toàn bộ màn hình chính bằng mss cực nhanh (~30ms)."""
        with mss.MSS() as sct:
            mon = sct.monitors[1]
            raw = sct.grab(mon)
            img = np.array(raw)[:, :, :3]  # BGR
            return img

    def finish_quiz(self) -> bool:
        """Tự động tìm và bấm nút 'Kết thúc luyện thi' (kèm xác nhận nếu có popup)."""
        self._notify_status("🏁 Đang tìm và bấm 'Kết thúc luyện thi'...")
        screen = self.capture_screen()
        btn_finish = self.solver.find_finish_button(screen)

        if btn_finish:
            print(f"🎯 [KẾT THÚC] Đã tìm thấy nút 'Kết thúc luyện thi' tại {btn_finish}! Đang bấm...")
            human_click(btn_finish[0], btn_finish[1], jitter=self.jitter, smooth=self.smooth_mouse)
            sleep_random(1.2, 2.0, "Chờ popup xác nhận kết thúc")

            # Kiểm tra xem có popup hỏi xác nhận không
            screen_popup = self.capture_screen()
            btn_confirm = self.solver.find_modal_confirm_button(screen_popup)
            if btn_confirm:
                print(f"   ✓ Đã xác nhận popup kết thúc tại {btn_confirm}")
                human_click(btn_confirm[0], btn_confirm[1], jitter=self.jitter, smooth=self.smooth_mouse)

            self._notify_status("🏆 ĐÃ HOÀN THÀNH BÀI THI & BẤM KẾT THÚC THÀNH CÔNG!")
            self.is_running = False
            return True
        else:
            self._notify_status("⚠️ Không tìm thấy nút 'Kết thúc luyện thi' trên màn hình!")
            return False

    def wait_and_click_next(
        self,
        ans_click: Optional[Tuple[int, int]] = None,
        min_y: int = 0,
        is_last_question: bool = False,
        retry_interval: float = 0.5
    ) -> Tuple[bool, Optional[Tuple[int, int]]]:
        """
        LIÊN TỤC CHỤP LẠI MÀN HÌNH VÀ TÌM NÚT 'TIẾP' CHO ĐẾN KHI BẤM ĐƯỢC:
        - Tự động phát hiện nếu đã đến câu cuối cùng thì chuyển sang bấm 'Kết thúc luyện thi'.
        - Thao tác di chuyển chuột tự nhiên, có jitter để chống phát hiện.
        """
        attempt = 0
        while self.is_running or not self.worker_thread:
            if self.is_paused:
                time.sleep(0.3)
                continue

            attempt += 1

            # 1. Chụp lại màn hình mới nhất
            screen = self.capture_screen()

            # 2. Nếu là câu cuối cùng hoặc đã thử 6 lần mà không thấy nút Tiếp:
            if is_last_question or attempt >= 6:
                btn_finish = self.solver.find_finish_button(screen)
                if btn_finish and is_last_question:
                    self.finish_quiz()
                    return True, btn_finish

            # 3. Tìm nút Tiếp trên màn hình mới
            next_pos = self.solver.find_next_button(screen, min_y=min_y)

            if next_pos:
                print(f"   ✓ [Chụp lần {attempt + 1}] Đã tìm thấy nút 'Tiếp' tại {next_pos}! Đang bấm...")
                human_click(next_pos[0], next_pos[1], jitter=self.jitter, smooth=self.smooth_mouse)
                return True, next_pos

            # 4. Nếu chưa thấy, thông báo và tiếp tục lặp lại
            msg = f"⏳ Chưa thấy nút 'Tiếp' (Lần {attempt}). Đang chụp lại và tìm tiếp..."
            print(f"   {msg}")
            self._notify_status(msg)

            # Cứ mỗi 4 lần thử, click lại vào đáp án
            if ans_click and attempt % 4 == 0:
                print(f"   🔄 Thử click lại đáp án tại {ans_click} để kích hoạt nút Tiếp...")
                human_click(ans_click[0], ans_click[1], jitter=self.jitter, smooth=self.smooth_mouse)

            # Cứ mỗi 8 lần thử, cuộn nhẹ màn hình xuống
            if attempt % 8 == 0:
                print("   🔄 Thử cuộn nhẹ màn hình xuống...")
                pyautogui.scroll(-100)

            time.sleep(retry_interval)

        return False, None

    def solve_once(self) -> Tuple[bool, str]:
        """Giải 1 câu hỏi hiện tại."""
        screen_1 = self.capture_screen()
        res = self.solver.solve_phase1(screen_1, fast_mode=True)

        if not res.get('success'):
            curr_q = res.get('curr_q')
            total_q = res.get('total_q')
            if curr_q and total_q and curr_q >= total_q:
                self.finish_quiz()
                return True, "Đã hoàn thành toàn bộ câu hỏi và bấm Kết thúc!"

            msg = f"❌ Không nhận diện được câu hỏi: {res.get('error')}"
            self._notify_status(msg)
            return False, msg

        qid = res['question_id']
        qtext = res['question_text']
        correct_idx = res['correct_index']
        correct_ans = res['correct_text']
        ans_click = res['answer_click']
        confidence = res['confidence']
        curr_q = res.get('curr_q')
        total_q = res.get('total_q')

        progress_str = f" [{curr_q}/{total_q}]" if curr_q and total_q else ""
        info = (
            f"🎯 [Câu {qid}]{progress_str} {qtext[:45]}...\n"
            f"   -> Chọn đáp án {correct_idx}: '{correct_ans[:40]}...' (Khớp: {confidence:.0f}%)"
        )
        print(info)

        if not ans_click:
            msg = f"⚠️ Không tìm thấy vị trí nút đáp án {correct_idx} trên màn hình!"
            self._notify_status(msg)
            return False, msg

        # Giả lập thời gian đọc câu hỏi của người thật
        sleep_random(self.read_range[0], self.read_range[1], "Đọc câu hỏi & suy nghĩ")

        # Click chọn đáp án bằng chuột tự nhiên
        human_click(ans_click[0], ans_click[1], jitter=self.jitter, smooth=self.smooth_mouse)
        print(f"   ✓ Đã click chọn đáp án {correct_idx} tại {ans_click}")

        # Giả lập thời gian xem lại kết quả/giải thích
        sleep_random(self.answer_range[0], self.answer_range[1], "Xem phản hồi đáp án")

        # Kiểm tra xem có phải câu cuối cùng không
        is_last = (curr_q is not None and total_q is not None and curr_q >= total_q)
        if is_last:
            print("🏁 Đây là câu hỏi cuối cùng! Chuyển sang bấm 'Kết thúc luyện thi'...")
            self.finish_quiz()
            return True, f"Thành công câu cuối {qid} và bấm Kết thúc!"

        # Chụp lần 2 & tìm nút Tiếp liên tục
        success, next_click = self.wait_and_click_next(
            ans_click=ans_click,
            min_y=res.get('last_ans_y', 0),
            is_last_question=is_last,
            retry_interval=0.5
        )

        if success and next_click:
            self.total_solved += 1
            self.last_solved_id = qid
            res['next_click'] = next_click
            if self.on_question_solved:
                self.on_question_solved(res)
            sleep_random(self.next_range[0], self.next_range[1], "Chờ tải câu tiếp theo")
            return True, f"Thành công câu {qid}"
        else:
            return False, "Đã hủy thao tác."

    def _auto_loop(self):
        """Vòng lặp tự động giải câu hỏi liên tục."""
        p_name = self.PROFILES.get(self.profile_name, {}).get("name", self.profile_name)
        self._notify_status(f"▶ Đang tự động làm bài [Chế độ: {p_name}]... (F9: Tạm dừng, F10: Dừng)")

        while self.is_running:
            if self.is_paused:
                time.sleep(0.3)
                continue

            try:
                screen_1 = self.capture_screen()
                res = self.solver.solve_phase1(screen_1, fast_mode=True)

                if not res.get('success'):
                    curr_q = res.get('curr_q')
                    total_q = res.get('total_q')
                    if curr_q and total_q and curr_q >= total_q:
                        self.finish_quiz()
                        break

                    self.repeat_count += 1
                    if self.repeat_count > 5:
                        self._notify_status("⚠️ Chưa thấy câu hỏi mới, đang tiếp tục chờ...")
                    time.sleep(1.0)
                    continue

                qid = res['question_id']
                curr_q = res.get('curr_q')
                total_q = res.get('total_q')

                # Kiểm tra nếu trang chưa kịp chuyển sang câu mới
                if qid == self.last_solved_id:
                    self.repeat_count += 1
                    if self.repeat_count > 3:
                        btn_pos = self.solver.find_next_button(screen_1, min_y=res.get('last_ans_y', 0))
                        if btn_pos:
                            human_click(btn_pos[0], btn_pos[1], jitter=self.jitter, smooth=self.smooth_mouse)
                        self.repeat_count = 0
                    time.sleep(1.0)
                    continue

                self.repeat_count = 0
                correct_idx = res['correct_index']
                correct_ans = res['correct_text']
                ans_click = res['answer_click']
                confidence = res['confidence']

                progress_str = f" [{curr_q}/{total_q}]" if curr_q and total_q else ""
                print(
                    f"[{self.total_solved + 1}]{progress_str} ID:{qid} (Khớp {confidence:.0f}%) "
                    f"-> Chọn {correct_idx}: {correct_ans[:35]}"
                )

                # Giả lập thời gian đọc câu hỏi của người thật
                sleep_random(self.read_range[0], self.read_range[1], "Đọc câu hỏi & suy nghĩ")

                # Click chọn đáp án bằng chuột tự nhiên có jitter
                if ans_click:
                    human_click(ans_click[0], ans_click[1], jitter=self.jitter, smooth=self.smooth_mouse)

                # Giả lập thời gian xem lại kết quả/giải thích
                sleep_random(self.answer_range[0], self.answer_range[1], "Xem phản hồi đáp án")

                # Kiểm tra xem đây có phải câu cuối cùng không
                is_last = (curr_q is not None and total_q is not None and curr_q >= total_q)
                if is_last:
                    print("🏁 Đã đến câu cuối cùng! Tiến hành bấm 'Kết thúc luyện thi'...")
                    self.finish_quiz()
                    break

                # Chụp lần 2 & tìm nút Tiếp liên tục
                success, next_click = self.wait_and_click_next(
                    ans_click=ans_click,
                    min_y=res.get('last_ans_y', 0),
                    is_last_question=is_last,
                    retry_interval=0.5
                )

                if success and next_click:
                    self.total_solved += 1
                    self.last_solved_id = qid
                    res['next_click'] = next_click
                    if self.on_question_solved:
                        self.on_question_solved(res)
                    sleep_random(self.next_range[0], self.next_range[1], "Chờ tải câu tiếp theo")
                elif not self.is_running:
                    break

            except pyautogui.FailSafeException:
                print("\n[!] FAILSAFE: Chuột được di chuyển vào góc màn hình! Dừng khẩn cấp.")
                self.is_running = False
                self._notify_status("⏹ Dừng khẩn cấp (FailSafe)")
                break
            except Exception as e:
                print(f"[!] Lỗi trong quá trình chạy: {e}")
                time.sleep(1.0)

        self._notify_status("⏹ Đã dừng.")

    def start_auto(self):
        """Bắt đầu chạy tự động."""
        if not self.is_running:
            self.is_running = True
            self.is_paused = False
            self.worker_thread = threading.Thread(target=self._auto_loop, daemon=True)
            self.worker_thread.start()
        elif self.is_paused:
            self.is_paused = False
            self._notify_status("▶ Tiếp tục chạy...")

    def pause_auto(self):
        """Tạm dừng."""
        if self.is_running:
            self.is_paused = not self.is_paused
            status = "⏸ Đã tạm dừng" if self.is_paused else "▶ Tiếp tục chạy..."
            self._notify_status(status)

    def stop_auto(self):
        """Dừng hoàn toàn."""
        self.is_running = False
        self.is_paused = False
        self._notify_status("⏹ Đã dừng")

    def _notify_status(self, text: str):
        print(f"[Trạng thái] {text}")
        if self.on_status_change:
            self.on_status_change(text)


def run_hotkey_listener(controller: AutoQuizController):
    """Lắng nghe phím tắt toàn cục bằng thư viện keyboard."""
    import keyboard
    keyboard.add_hotkey('f8', lambda: threading.Thread(target=controller.solve_once, daemon=True).start())
    keyboard.add_hotkey('f9', lambda: controller.pause_auto() if controller.is_running else controller.start_auto())
    keyboard.add_hotkey('f10', lambda: controller.stop_auto())
    print("\n" + "=" * 60)
    print("  ⌨️  DANH SÁCH PHÍM TẮT:")
    print("  [F8]  : Tự động giải 1 câu hiện tại")
    print("  [F9]  : Bật / Tạm dừng chế độ tự động liên tục")
    print("  [F10] : Dừng hẳn")
    print("  [Góc màn hình]: Rê chuột vào góc trên-trái để dừng khẩn cấp")
    print("=" * 60 + "\n")


def launch_gui(controller: AutoQuizController):
    """Mở giao diện điều khiển nhỏ gọn (Always on Top)."""
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("Auto Quiz 600 Câu - Anti-Bot")
    root.geometry("440x420")
    root.attributes("-topmost", True)
    root.resizable(False, False)

    header_frame = tk.Frame(root, bg="#1e293b", padx=12, pady=10)
    header_frame.pack(fill=tk.X)

    title_label = tk.Label(
        header_frame,
        text="🚗 Auto Quiz LMS - Chống Phát Hiện Tool",
        font=("Segoe UI", 12, "bold"),
        fg="#f8fafc",
        bg="#1e293b"
    )
    title_label.pack(anchor="w")

    subtitle_label = tk.Label(
        header_frame,
        text="Delay ngẫu nhiên, chuột lướt tự nhiên, tự động kết thúc bài thi",
        font=("Segoe UI", 8),
        fg="#38bdf8",
        bg="#1e293b"
    )
    subtitle_label.pack(anchor="w")

    content_frame = tk.Frame(root, padx=12, pady=10)
    content_frame.pack(fill=tk.BOTH, expand=True)

    # Lựa chọn chế độ tốc độ
    mode_frame = tk.Frame(content_frame)
    mode_frame.pack(fill=tk.X, pady=(0, 6))

    mode_label = tk.Label(mode_frame, text="Tốc độ:", font=("Segoe UI", 9, "bold"), fg="#475569")
    mode_label.pack(side=tk.LEFT, padx=(0, 6))

    mode_var = tk.StringVar(value="human")

    def on_mode_change():
        controller.set_profile(mode_var.get())
        status_var.set(f"Đã chuyển sang chế độ: {controller.PROFILES[mode_var.get()]['name']}")

    r_human = tk.Radiobutton(mode_frame, text="🐢 Người thật (Chống bot)", variable=mode_var, value="human", command=on_mode_change)
    r_human.pack(side=tk.LEFT, padx=3)

    r_med = tk.Radiobutton(mode_frame, text="🐇 Vừa", variable=mode_var, value="medium", command=on_mode_change)
    r_med.pack(side=tk.LEFT, padx=3)

    r_fast = tk.Radiobutton(mode_frame, text="⚡ Nhanh", variable=mode_var, value="fast", command=on_mode_change)
    r_fast.pack(side=tk.LEFT, padx=3)

    status_var = tk.StringVar(value="Sẵn sàng. Chế độ Người thật (2.5s - 5s ngẫu nhiên).")
    status_label = tk.Label(
        content_frame,
        textvariable=status_var,
        font=("Segoe UI", 8, "italic"),
        fg="#0284c7",
        wraplength=410,
        justify=tk.LEFT
    )
    status_label.pack(fill=tk.X, pady=(0, 6))

    info_box = tk.LabelFrame(content_frame, text="Câu hỏi gần nhất", font=("Segoe UI", 9, "bold"), padx=8, pady=4)
    info_box.pack(fill=tk.X, pady=2)

    q_info_var = tk.StringVar(value="Chưa có câu nào được giải.")
    q_info_label = tk.Label(
        info_box,
        textvariable=q_info_var,
        font=("Segoe UI", 8),
        fg="#334155",
        wraplength=390,
        justify=tk.LEFT
    )
    q_info_label.pack(fill=tk.X)

    counter_var = tk.StringVar(value="Đã hoàn thành: 0 câu")
    counter_label = tk.Label(content_frame, textvariable=counter_var, font=("Segoe UI", 9, "bold"), fg="#16a34a")
    counter_label.pack(anchor="w", pady=4)

    btn_frame = tk.Frame(content_frame)
    btn_frame.pack(fill=tk.X, pady=6)

    def on_start():
        controller.start_auto()

    def on_step():
        threading.Thread(target=controller.solve_once, daemon=True).start()

    def on_finish():
        threading.Thread(target=controller.finish_quiz, daemon=True).start()

    def on_stop():
        controller.stop_auto()

    btn_start = tk.Button(
        btn_frame, text="▶ Bắt đầu (F9)", bg="#22c55e", fg="white",
        font=("Segoe UI", 9, "bold"), padx=4, pady=4, relief=tk.FLAT, command=on_start
    )
    btn_start.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

    btn_step = tk.Button(
        btn_frame, text="⏩ 1 Câu (F8)", bg="#3b82f6", fg="white",
        font=("Segoe UI", 9, "bold"), padx=4, pady=4, relief=tk.FLAT, command=on_step
    )
    btn_step.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

    btn_finish = tk.Button(
        btn_frame, text="🏁 Kết thúc", bg="#eab308", fg="black",
        font=("Segoe UI", 9, "bold"), padx=4, pady=4, relief=tk.FLAT, command=on_finish
    )
    btn_finish.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

    btn_stop = tk.Button(
        btn_frame, text="⏹ Dừng (F10)", bg="#ef4444", fg="white",
        font=("Segoe UI", 9, "bold"), padx=4, pady=4, relief=tk.FLAT, command=on_stop
    )
    btn_stop.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

    def status_callback(text):
        root.after(0, lambda: status_var.set(text))

    def solved_callback(res):
        progress_str = f" [{res.get('curr_q')}/{res.get('total_q')}]" if res.get('curr_q') else ""
        text = f"Câu {res['question_id']}{progress_str}: Chọn [{res['correct_index']}]\n{res['correct_text'][:65]}..."
        root.after(0, lambda: [
            q_info_var.set(text),
            counter_var.set(f"Đã hoàn thành: {controller.total_solved} câu")
        ])

    controller.on_status_change = status_callback
    controller.on_question_solved = solved_callback

    try:
        run_hotkey_listener(controller)
    except Exception as e:
        print(f"Lưu ý: Không thể đăng ký phím tắt toàn cục ({e}), sử dụng các nút trên giao diện.")

    root.mainloop()


def test_on_image(image_path: str, db_path: str = "data/questions.json"):
    """Chế độ kiểm tra trên ảnh có sẵn."""
    print(f"\n--- Đang kiểm tra trên ảnh: {image_path} ---")
    solver = QuizSolver(db_path=db_path)
    res = solver.solve(image_path, fast_mode=True)

    if not res['success']:
        print(f"❌ Lỗi: {res.get('error')}")
        return

    progress_str = f" ({res['curr_q']}/{res['total_q']})" if res.get('curr_q') else ""
    print(f"✅ Nhận diện THÀNH CÔNG{progress_str}:")
    print(f"   - Mã câu hỏi DB       : ID {res['question_id']}")
    print(f"   - Chương               : {res.get('chapter', 1)} - {res.get('chapter_name', '')}")
    print(f"   - Nội dung câu hỏi     : {res['question_text']}")
    print(f"   - Độ khớp             : {res['confidence']:.1f}%")
    print(f"   - ĐÁP ÁN ĐÚNG          : Đáp án [{res['correct_index']}] - {res['correct_text']}")
    print(f"   - Tọa độ Click Đáp án  : {res['answer_click']}")
    print(f"   - Tọa độ Click Tiếp    : {res['next_click']}")
    print(f"   - Tọa độ Nút Kết Thúc  : {res.get('finish_click')}")
    print("-" * 50)


def main():
    parser = argparse.ArgumentParser(description="Tool tự động làm trắc nghiệm bằng lái xe (600 câu) - Giả lập người thật.")
    parser.add_argument("--test", "-t", type=str, help="Kiểm tra trên 1 ảnh mẫu (ví dụ: sample.png hoặc sample2.png)")
    parser.add_argument("--auto", "-a", action="store_true", help="Chạy tự động liên tục ngay lập tức")
    parser.add_argument("--step", "-s", action="store_true", help="Giải 1 câu hỏi hiện tại rồi dừng")
    parser.add_argument("--gui", "-g", action="store_true", help="Mở giao diện điều khiển nổi trên màn hình")
    parser.add_argument("--mode", "-m", choices=["human", "medium", "fast"], default="human", help="Chế độ tốc độ (human: người thật chống detect, medium, fast)")
    parser.add_argument("--delay-read", type=float, nargs=2, metavar=('MIN', 'MAX'), help="Thời gian giả lập đọc đề (ví dụ: --delay-read 2.0 4.0)")
    parser.add_argument("--delay-ans", type=float, nargs=2, metavar=('MIN', 'MAX'), help="Thời gian giả lập xem đáp án (ví dụ: --delay-ans 2.0 4.0)")
    parser.add_argument("--delay-next", type=float, nargs=2, metavar=('MIN', 'MAX'), help="Thời gian chờ tải câu mới (ví dụ: --delay-next 2.5 5.0)")
    parser.add_argument("--db", type=str, default="data/questions.json", help="Đường dẫn file câu hỏi JSON")
    args = parser.parse_args()

    if args.test:
        test_on_image(args.test, db_path=args.db)
        return

    controller = AutoQuizController(
        db_path=args.db,
        profile=args.mode,
        custom_read_range=tuple(args.delay_read) if args.delay_read else None,
        custom_answer_range=tuple(args.delay_ans) if args.delay_ans else None,
        custom_next_range=tuple(args.delay_next) if args.delay_next else None
    )

    if args.gui:
        launch_gui(controller)
    elif args.step:
        print("Đang giải 1 câu hỏi theo chế độ người thật...")
        controller.solve_once()
    elif args.auto:
        try:
            run_hotkey_listener(controller)
        except Exception:
            pass
        controller.start_auto()
        try:
            while controller.is_running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            controller.stop_auto()
    else:
        try:
            run_hotkey_listener(controller)
            launch_gui(controller)
        except Exception:
            print("Chạy chế độ console CLI...")
            controller.start_auto()
            try:
                while True:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                controller.stop_auto()


if __name__ == "__main__":
    main()
