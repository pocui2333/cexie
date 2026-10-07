"""
macOS Vision OCR text recognition and visual bubble feature analysis.
"""
import re
from typing import List, Dict, Any, Optional
from PIL import Image
import Vision
from Foundation import NSURL, NSDictionary

def run_vision_ocr(image_path: str, languages: List[str] = None) -> List[Dict[str, Any]]:
    """调用 macOS 原生 Vision 框架进行高精度文本识别"""
    if languages is None:
        languages = ["zh-Hans", "en-US"]

    url = NSURL.fileURLWithPath_(image_path)
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, NSDictionary.dictionary())
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLanguages_(languages)
    req.setUsesLanguageCorrection_(True)
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)

    success, err = handler.performRequests_error_([req], None)
    if not success or not req.results():
        return []

    observations = []
    for obs in req.results():
        txt = obs.text().strip()
        if not txt:
            continue
        bb = obs.boundingBox()
        # Vision bounding box: origin=(x, y) bottom-left, size=(w, h), normalized 0~1
        observations.append({
            "text": txt,
            "x": bb.origin.x,
            "y": bb.origin.y,
            "w": bb.size.width,
            "h": bb.size.height,
            "r_x": bb.origin.x + bb.size.width
        })
    return observations

def has_green_bubble_background(pil_image: Image.Image, x: float, y: float, w: float, h: float) -> bool:
    """检查识别区域周围是否存在微信我方发言特有的绿色气泡像素"""
    img_w, img_h = pil_image.size
    px1 = int(x * img_w)
    px2 = int((x + w) * img_w)
    # Vision coordinates y starts from bottom
    py1 = int((1.0 - (y + h)) * img_h)
    py2 = int((1.0 - y) * img_h)

    for sy in range(max(0, py1), min(img_h, py2), max(1, (py2 - py1) // 3)):
        for sx in range(max(0, px1), min(img_w, px2), max(1, (px2 - px1) // 5)):
            try:
                r, g, b = pil_image.getpixel((sx, sy))[:3]
                if g > 90 and (g - r >= 25) and (g - b >= 20):
                    return True
            except Exception:
                pass
    return False

def extract_contact_from_header(screenshot_path: str) -> Optional[str]:
    """从微信窗口顶部中间标题栏提取活跃聊天对象备注名"""
    try:
        img = Image.open(screenshot_path)
        w, h = img.size
        # 裁剪顶栏中央区域 (避免侧边栏干扰，覆盖联系人/群聊名)
        crop_box = (int(w * 0.26), 0, int(w * 0.70), int(h * 0.09))
        cropped = img.crop(crop_box)
        tmp_crop = "/tmp/echolens_header_crop.png"
        cropped.save(tmp_crop)

        observations = run_vision_ocr(tmp_crop)
        if not observations:
            return None

        # 过滤时间戳与系统星期杂词
        ignore_words = [
            "saturday", "sunday", "monday", "tuesday", "wednesday", "thursday", "friday",
            "yesterday", "today", "昨天", "今天", "周六", "周日", "星期", "微信", "wechat"
        ]

        valid_names = []
        for obs in observations:
            txt = obs["text"]
            low = txt.lower()
            if any(ign in low for ign in ignore_words):
                continue
            if re.search(r"(\d{1,2}:\d{2})", low):
                continue
            # 允许中英文字符、数字、下划线及群人数括号
            if re.match(r"^[\u4e00-\u9fa5A-Za-z0-9_\-\s（）\(\)]+$", txt):
                valid_names.append((obs["y"], txt))

        if valid_names:
            valid_names.sort(key=lambda x: -x[0])
            return valid_names[0][1].strip()
    except Exception as e:
        print(f"[Header OCR Error] {e}")
    return None
