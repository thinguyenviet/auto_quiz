"""
quiz_solver.py - Core matching and vision engine for automated quiz answering.
Uses RapidOCR (ONNX) + RapidFuzz to recognize questions from screen and match with database.
Hỗ trợ cả dạng nút Tiếp chuẩn (sample.png) và nút Tiếp compact sát đáy (sample2.png),
đồng thời tự động phát hiện và bấm 'Kết thúc luyện thi' khi hoàn thành toàn bộ bài thi.
"""

import os
import re
import json
import unicodedata
from typing import Optional, Dict, Any, List, Tuple, Union
import numpy as np
import cv2
from PIL import Image
from rapidocr_onnxruntime import RapidOCR
from rapidfuzz import fuzz


def normalize_text(text: str) -> str:
    """Normalize text by converting to lowercase and stripping punctuation."""
    text = text.lower()
    text = re.sub(
        r'[^a-z0-9\sàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]',
        ' ',
        text
    )
    return ' '.join(text.split())


def remove_diacritics(text: str) -> str:
    """Remove Vietnamese diacritics for robust matching against OCR quirks."""
    nfkd = unicodedata.normalize('NFKD', text)
    res = ''.join([c for c in nfkd if not unicodedata.combining(c)])
    return res.replace('đ', 'd').replace('Đ', 'D')


class QuizSolver:
    def __init__(self, db_path: str = "data/questions.json"):
        self.db_path = db_path
        self.db = self._load_db()
        self.ocr = RapidOCR()

        # Nạp mẫu nút Tiếp từ cả sample.png (chuẩn 47px) và sample2.png (compact 35px)
        self.templates_next = []
        if os.path.exists('sample.png'):
            try:
                s1 = cv2.imread('sample.png')
                if s1 is not None and s1.shape[0] >= 920 and s1.shape[1] >= 1520:
                    self.templates_next.append(s1[868:915, 1430:1505])
            except Exception:
                pass

        if os.path.exists('sample2.png'):
            try:
                s2 = cv2.imread('sample2.png')
                if s2 is not None and s2.shape[0] >= 1025 and s2.shape[1] >= 1500:
                    self.templates_next.append(s2[990:1025, 1420:1495])
            except Exception:
                pass

    def _load_db(self) -> List[Dict[str, Any]]:
        """Load and pre-index questions from database."""
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"Database file not found: {self.db_path}")

        with open(self.db_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        for item in data:
            q_norm = normalize_text(item.get('question', ''))
            item['_q_norm'] = q_norm
            item['_q_clean'] = remove_diacritics(q_norm)
            item['_ans_clean'] = [
                remove_diacritics(normalize_text(a)) for a in item.get('answers', [])
            ]
        return data

    def extract_ocr_lines(
        self,
        image: Union[str, np.ndarray, Image.Image],
        offset_x: int = 0,
        offset_y: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Run OCR on image and return structured line information with real-time bounding boxes.
        offset_x and offset_y map coordinates back to full screen space.
        """
        if isinstance(image, Image.Image):
            image = np.array(image)

        results, _ = self.ocr(image)
        lines = []
        if not results:
            return lines

        for box, text, score in results:
            if score < 0.35:
                continue
            text_str = text.strip()
            if not text_str:
                continue

            x_min = min(pt[0] for pt in box) + offset_x
            x_max = max(pt[0] for pt in box) + offset_x
            y_min = min(pt[1] for pt in box) + offset_y
            y_max = max(pt[1] for pt in box) + offset_y
            x_mid = (x_min + x_max) / 2
            y_mid = (y_min + y_max) / 2

            norm = normalize_text(text_str)
            clean = remove_diacritics(norm)

            lines.append({
                'text': text_str,
                'norm': norm,
                'clean': clean,
                'box': [
                    [pt[0] + offset_x, pt[1] + offset_y] for pt in box
                ],
                'x_min': x_min,
                'x_max': x_max,
                'y_min': y_min,
                'y_max': y_max,
                'x_mid': x_mid,
                'y_mid': y_mid,
                'score': score
            })
        return lines

    def filter_quiz_region(
        self,
        lines: List[Dict[str, Any]],
        img_w: int,
        img_h: int,
        is_already_cropped: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Filter out irrelevant lines (browser header, OS taskbar, left menu)
        using DYNAMIC relative proportions of the captured window/screen.
        """
        if not lines or is_already_cropped:
            return lines

        filtered = []
        for l in lines:
            if l['y_mid'] < img_h * 0.12:
                continue
            if l['y_mid'] > img_h * 0.985:
                continue
            if l['x_mid'] < img_w * 0.17:
                continue
            filtered.append(l)

        return filtered if filtered else lines

    def get_progress(self, lines: List[Dict[str, Any]]) -> Tuple[Optional[int], Optional[int]]:
        """
        Nhận diện tiến độ làm bài (Ví dụ: 'Câu hỏi : 25/182' hoặc 'Câu hỏi : 182/182').
        Trả về (câu_hiện_tại, tổng_số_câu).
        """
        for l in lines:
            clean = l['clean']
            m = re.search(r'cau\s*hoi\s*[:\s]*(\d+)\s*[/|\s]\s*(\d+)', clean)
            if m:
                return int(m.group(1)), int(m.group(2))
        return None, None

    def find_best_question_match(
        self, quiz_lines: List[Dict[str, Any]]
    ) -> Tuple[Optional[Dict[str, Any]], float, List[Dict[str, Any]]]:
        """
        Match detected screen text against the question database.
        Returns (best_question, confidence_score, screen_answer_lines).
        """
        if not quiz_lines:
            return None, 0.0, []

        answers_on_screen = []
        question_lines = []

        for l in quiz_lines:
            t = l['text'].strip()
            if 'cau hoi chon' in l['clean']:
                continue
            # Bỏ qua dòng phản hồi giải thích đã hiển thị (ví dụ: 'Chính xác', 'Phản hồi:', 'Câu trả lời chính xác là')
            if any(k in l['clean'] for k in ['chinh xac', 'phan hoi', 'cau tra loi chinh xac']):
                continue

            m = re.match(r'^(?:[O0o(\[\]\u25cb\u25cf]\s*[)\s]*)?([1-4])\s*[-.:)]\s*(.*)', t)
            if m and ('cau hoi' not in l['clean']):
                answers_on_screen.append({
                    'opt_num': int(m.group(1)),
                    'opt_text': m.group(2).strip(),
                    'line': l
                })
            else:
                if not any(k in l['clean'] for k in ['tiep', 'truoc', 'gop y', 'cau hoi :', 'ket thuc', 'kiem tra']):
                    question_lines.append(l)

        screen_q_text = " ".join([l['clean'] for l in question_lines])

        screen_ans_texts = {
            item['opt_num']: remove_diacritics(normalize_text(item['opt_text']))
            for item in answers_on_screen
        }

        best_q = None
        best_score = -1.0

        for q in self.db:
            q_clean = q['_q_clean']
            q_sim = fuzz.token_set_ratio(q_clean, screen_q_text)

            ans_sims = []
            if screen_ans_texts:
                for opt_num, s_text in screen_ans_texts.items():
                    if 1 <= opt_num <= len(q['_ans_clean']):
                        db_ans = q['_ans_clean'][opt_num - 1]
                        ans_sims.append(fuzz.token_set_ratio(db_ans, s_text))
                avg_ans_sim = sum(ans_sims) / len(ans_sims) if ans_sims else 0.0
            else:
                for db_ans in q['_ans_clean']:
                    ans_sims.append(fuzz.partial_ratio(db_ans, screen_q_text))
                avg_ans_sim = sum(ans_sims) / len(ans_sims) if ans_sims else 0.0

            total_score = q_sim * 0.4 + avg_ans_sim * 0.6
            if total_score > best_score:
                best_score = total_score
                best_q = q

        return best_q, best_score, answers_on_screen

    def locate_answer_click(
        self,
        question: Dict[str, Any],
        quiz_lines: List[Dict[str, Any]],
        answers_on_screen: List[Dict[str, Any]]
    ) -> Optional[Tuple[int, int]]:
        """
        Tìm tọa độ click đáp án đúng trên màn hình hiện tại (Lần 1).
        """
        correct_idx = question.get('correct', 1)
        correct_text = question['answers'][correct_idx - 1] if correct_idx <= len(question['answers']) else ""
        correct_clean = remove_diacritics(normalize_text(correct_text))

        for item in answers_on_screen:
            if item['opt_num'] == correct_idx:
                l = item['line']
                click_x = int(l['x_min'] + 15)
                click_y = int(l['y_mid'])
                return (click_x, click_y)

        best_line = None
        best_sim = -1.0
        for l in quiz_lines:
            if any(k in l['clean'] for k in ['cau hoi chon', 'tiep', 'truoc', 'gop y', 'cau hoi :', 'ket thuc', 'chinh xac', 'phan hoi']):
                continue
            sim = fuzz.token_set_ratio(correct_clean, l['clean'])
            if sim > best_sim:
                best_sim = sim
                best_line = l

        if best_line and best_sim >= 50.0:
            click_x = int(best_line['x_min'] + 15)
            click_y = int(best_line['y_mid'])
            return (click_x, click_y)

        return None

    def find_next_button(
        self,
        image_input: Union[str, np.ndarray, Image.Image],
        min_y: int = 0
    ) -> Optional[Tuple[int, int]]:
        """
        TÌM NÚT 'TIẾP' TRÊN ẢNH CHỤP MÀN HÌNH:
        - Hỗ trợ cả vị trí giữa thẻ bài thi (sample.png) và vị trí compact ở đáy màn hình (sample2.png).
        - Kết hợp Template Matching (~15ms) và OCR fallback.
        - Giới hạn x < 0.88*w để TUYỆT ĐỐI KHÔNG bấm nhầm nút 'Tiếp theo ->' ở góc phải.
        """
        if isinstance(image_input, str):
            image = Image.open(image_input)
            image_np = np.array(image)
        elif isinstance(image_input, Image.Image):
            image_np = np.array(image_input)
        else:
            image_np = image_input

        img_h, img_w = image_np.shape[:2]

        # Vùng tìm kiếm nút Tiếp:
        # y: từ 45% màn hình đến 98.5% (ngay trên taskbar)
        # x: từ 35% đến 88% (nút Tiếp ở x ~ 76%, nút Tiếp theo ở x ~ 97%)
        scan_y1 = int(img_h * 0.45)
        scan_y2 = int(img_h * 0.985)
        scan_x1 = int(img_w * 0.35)
        scan_x2 = int(img_w * 0.88)

        search_area = image_np[scan_y1:scan_y2, scan_x1:scan_x2]

        # 1. Thử qua Template Matching với các template đã lưu (~15ms)
        for tmpl in self.templates_next:
            try:
                res = cv2.matchTemplate(search_area, tmpl, cv2.TM_CCOEFF_NORMED)
                min_v, max_v, min_l, max_l = cv2.minMaxLoc(res)
                if max_v >= 0.80:
                    btn_h, btn_w = tmpl.shape[:2]
                    click_x = int(scan_x1 + max_l[0] + btn_w / 2)
                    click_y = int(scan_y1 + max_l[1] + btn_h / 2)
                    return (click_x, click_y)
            except Exception:
                pass

        # 2. OCR quét tìm chữ 'Tiếp' trong vùng search_area
        lines = self.extract_ocr_lines(search_area, offset_x=scan_x1, offset_y=scan_y1)
        for l in lines:
            clean = l['clean']
            # Chấp nhận 'tiep' (hoặc 'tiép' đã bỏ dấu) nhưng LOẠI TRỪ 'theo' và 'muc'
            if 'tiep' in clean and 'theo' not in clean and 'muc' not in clean:
                return int(l['x_mid']), int(l['y_mid'])

        # 3. Quét mở rộng thêm nếu vẫn chưa thấy
        wide_lines = self.extract_ocr_lines(image_np[int(img_h * 0.3):int(img_h * 0.985), int(img_w * 0.2):int(img_w * 0.90)],
                                            offset_x=int(img_w * 0.2), offset_y=int(img_h * 0.3))
        for l in wide_lines:
            clean = l['clean']
            if 'tiep' in clean and 'theo' not in clean and 'muc' not in clean:
                return int(l['x_mid']), int(l['y_mid'])

        return None

    def find_finish_button(
        self,
        image_input: Union[str, np.ndarray, Image.Image]
    ) -> Optional[Tuple[int, int]]:
        """
        TÌM NÚT 'KẾT THÚC LUYỆN THI' TRÊN MÀN HÌNH:
        Nằm ở góc trên bên phải của khung câu hỏi (x ~ 70% - 96% w, y ~ 30% - 55% h).
        """
        if isinstance(image_input, str):
            image = Image.open(image_input)
            image_np = np.array(image)
        elif isinstance(image_input, Image.Image):
            image_np = np.array(image_input)
        else:
            image_np = image_input

        img_h, img_w = image_np.shape[:2]
        crop_x1 = int(img_w * 0.70)
        crop_x2 = int(img_w * 0.96)
        crop_y1 = int(img_h * 0.30)
        crop_y2 = int(img_h * 0.55)

        sub_img = image_np[crop_y1:crop_y2, crop_x1:crop_x2]
        lines = self.extract_ocr_lines(sub_img, offset_x=crop_x1, offset_y=crop_y1)

        for l in lines:
            clean = l['clean']
            if 'ket thuc' in clean:
                return int(l['x_mid']), int(l['y_mid'])

        # Nếu vùng nhỏ chưa thấy, quét mở rộng toàn bộ góc trên bên phải
        wide_lines = self.extract_ocr_lines(image_np[:int(img_h * 0.6), int(img_w * 0.5):],
                                            offset_x=int(img_w * 0.5), offset_y=0)
        for l in wide_lines:
            if 'ket thuc' in l['clean']:
                return int(l['x_mid']), int(l['y_mid'])

        return None

    def find_modal_confirm_button(
        self,
        image_input: Union[str, np.ndarray, Image.Image]
    ) -> Optional[Tuple[int, int]]:
        """
        Tìm nút xác nhận trên popup modal (nếu có hỏi: 'Bạn có chắc chắn muốn kết thúc?').
        Tìm chữ: 'Đồng ý', 'Xác nhận', 'Kết thúc', 'OK'.
        """
        if isinstance(image_input, str):
            image = Image.open(image_input)
            image_np = np.array(image)
        elif isinstance(image_input, Image.Image):
            image_np = np.array(image_input)
        else:
            image_np = image_input

        img_h, img_w = image_np.shape[:2]
        # Popup thường nằm ở trung tâm màn hình
        center_crop = image_np[int(img_h * 0.3):int(img_h * 0.7), int(img_w * 0.3):int(img_w * 0.7)]
        lines = self.extract_ocr_lines(center_crop, offset_x=int(img_w * 0.3), offset_y=int(img_h * 0.3))

        for l in lines:
            clean = l['clean']
            if any(k in clean for k in ['dong y', 'xac nhan', 'co']):
                return int(l['x_mid']), int(l['y_mid'])

        return None

    def solve_phase1(
        self,
        image_input: Union[str, np.ndarray, Image.Image],
        fast_mode: bool = True
    ) -> Dict[str, Any]:
        """
        Pha 1: Nhận diện câu hỏi, xác định đáp án đúng và tọa độ click đáp án.
        """
        if isinstance(image_input, str):
            image = Image.open(image_input)
            image_np = np.array(image)
        elif isinstance(image_input, Image.Image):
            image_np = np.array(image_input)
        else:
            image_np = image_input

        img_h, img_w = image_np.shape[:2]
        offset_x, offset_y = 0, 0
        is_cropped = False

        if fast_mode and img_w >= 1200 and img_h >= 700:
            crop_x1 = int(img_w * 0.16)
            crop_x2 = int(img_w * 0.95)
            crop_y1 = int(img_h * 0.18)
            crop_y2 = int(img_h * 0.95)
            image_to_scan = image_np[crop_y1:crop_y2, crop_x1:crop_x2]
            offset_x, offset_y = crop_x1, crop_y1
            is_cropped = True
        else:
            image_to_scan = image_np

        all_lines = self.extract_ocr_lines(image_to_scan, offset_x=offset_x, offset_y=offset_y)
        quiz_lines = self.filter_quiz_region(all_lines, img_w=img_w, img_h=img_h, is_already_cropped=is_cropped)
        curr_q, total_q = self.get_progress(all_lines)
        best_q, score, answers_on_screen = self.find_best_question_match(quiz_lines)

        if (not best_q or score < 50.0) and is_cropped:
            all_lines = self.extract_ocr_lines(image_np, offset_x=0, offset_y=0)
            quiz_lines = self.filter_quiz_region(all_lines, img_w=img_w, img_h=img_h, is_already_cropped=False)
            curr_q, total_q = self.get_progress(all_lines)
            best_q, score, answers_on_screen = self.find_best_question_match(quiz_lines)

        if not best_q or score < 40.0:
            return {
                'success': False,
                'curr_q': curr_q,
                'total_q': total_q,
                'error': f'Không tìm thấy câu hỏi phù hợp trong database (độ khớp: {score:.1f}%).'
            }

        correct_idx = best_q['correct']
        correct_text = best_q['answers'][correct_idx - 1]
        ans_click = self.locate_answer_click(best_q, quiz_lines, answers_on_screen)

        last_ans_y = 0
        if answers_on_screen:
            last_ans_y = max(item['line']['y_max'] for item in answers_on_screen)

        return {
            'success': True,
            'question_id': best_q['id'],
            'chapter': best_q.get('chapter', 1),
            'chapter_name': best_q.get('chapter_name', ''),
            'question_text': best_q['question'],
            'confidence': score,
            'correct_index': correct_idx,
            'correct_text': correct_text,
            'answer_click': ans_click,
            'answers_found': len(answers_on_screen),
            'last_ans_y': last_ans_y,
            'curr_q': curr_q,
            'total_q': total_q
        }

    def solve(
        self,
        image_input: Union[str, np.ndarray, Image.Image],
        fast_mode: bool = True
    ) -> Dict[str, Any]:
        """Giải câu hỏi và tìm nút đáp án, nút Tiếp, nút Kết thúc."""
        res = self.solve_phase1(image_input, fast_mode=fast_mode)
        if not res['success']:
            return res

        next_click = self.find_next_button(image_input, min_y=res.get('last_ans_y', 0))
        finish_click = self.find_finish_button(image_input)
        res['next_click'] = next_click
        res['finish_click'] = finish_click
        return res
