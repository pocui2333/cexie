"""
Image Detector & Multimodal Interpreter for WeChat chat bubbles.
Detects image/photo bubbles in WeChat chat area and interprets them into
concise, high-EQ semantic descriptions [图片: {description}] using VLM with MD5 caching.
"""
import os
import io
import re
import json
import ssl
import hashlib
import base64
import urllib.request
import urllib.error
from typing import List, Dict, Any, Optional
from PIL import Image

import Vision
from Foundation import NSURL, NSDictionary
import config

_IMAGE_CACHE: Dict[str, str] = {}

def calculate_image_variance(pil_crop: Image.Image) -> float:
    """计算切片区域颜色标准差，区分纯色文本气泡与色彩丰富的真实图片"""
    # 缩小后快速抽样
    thumb = pil_crop.resize((32, 32), Image.Resampling.BOX).convert("RGB")
    pixels = list(thumb.getdata())
    n = len(pixels)
    if n == 0:
        return 0.0
    r_vals = [p[0] for p in pixels]
    g_vals = [p[1] for p in pixels]
    b_vals = [p[2] for p in pixels]
    avg_r = sum(r_vals) / n
    avg_g = sum(g_vals) / n
    avg_b = sum(b_vals) / n
    var_r = sum((x - avg_r) ** 2 for x in r_vals) / n
    var_g = sum((x - avg_g) ** 2 for x in g_vals) / n
    var_b = sum((x - avg_b) ** 2 for x in b_vals) / n
    return (var_r + var_g + var_b) ** 0.5

def describe_image_via_vlm(pil_crop: Image.Image) -> Optional[str]:
    """调用多模态大模型对图片进行大白话视觉描述 (带缩放压缩优化)"""
    if not config.LLM_API_KEY:
        return None

    # 缩放至最大 380px，既清晰又轻量极速
    w, h = pil_crop.size
    max_dim = 380
    if max(w, h) > max_dim:
        scale = max_dim / float(max(w, h))
        pil_crop = pil_crop.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    pil_crop.convert("RGB").save(buf, format="JPEG", quality=82)
    img_bytes = buf.getvalue()

    # MD5 快速缓存检查
    img_hash = hashlib.md5(img_bytes).hexdigest()
    if img_hash in _IMAGE_CACHE:
        return _IMAGE_CACHE[img_hash]

    b64_str = base64.b64encode(img_bytes).decode("utf-8")

    prompt = (
        "这是一张从微信聊天窗口中截取出的图片/照片/表情包气泡。\n"
        "请用一句话简明扼要地描述画面的核心主体与视觉重点（例如：'一只手捏着黄色黏土小人'、'试衣镜前米白色开衫配牛仔裤穿搭'、'一盘刚出炉的战斧牛排'、'一只可爱的金毛幼犬在草地上打滚'、'小红书关于露营推荐的图文笔记截图'）。\n"
        "要求：大白话、直接提炼核心主体，严禁包含任何前缀客套（不要写'这是一张...'或'图中显示...'），字数控制在15~25字以内。如果是纯色空白背景则回复NONE。"
    )

    url = f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.LLM_API_KEY}"
    }
    body = {
        "model": config.LLM_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_str}"}}
                ]
            }
        ],
        "temperature": 0.2,
        "max_tokens": 40
    }

    try:
        import certifi
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ssl_ctx = ssl._create_unverified_context()

    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=4.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            desc = data["choices"][0]["message"]["content"].strip()
            if not desc or "NONE" in desc.upper():
                return None
            desc = re.sub(r"^(这是一张|图中是|画面显示|照片中是)", "", desc).strip()
            _IMAGE_CACHE[img_hash] = desc
            return desc
    except Exception as e:
        print(f"[VLM Image Describe Warning] {e}")
        return None

def fallback_macos_vision_classify(crop_path: str) -> Optional[str]:
    """macOS 本地 Vision 离线分类兜底"""
    try:
        url = NSURL.fileURLWithPath_(crop_path)
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, NSDictionary.dictionary())
        req = Vision.VNClassifyImageRequest.alloc().init()
        success, _ = handler.performRequests_error_([req], None)
        if success and req.results():
            top = req.results()[0]
            cat = top.identifier()
            mapping = {
                "food": "美食/聚餐",
                "drink": "饮品/咖啡",
                "dog": "宠物狗狗",
                "cat": "宠物猫咪",
                "pet": "可爱宠物",
                "clothing": "穿搭服饰",
                "outdoor": "户外风景",
                "screenshot": "手机截图/图文笔记",
                "document": "文档/聊天截图"
            }
            for k, v in mapping.items():
                if k in cat.lower():
                    return v
            return f"照片分享 ({cat})"
    except Exception:
        pass
    return None

def is_wechat_green_bubble(pil_crop: Image.Image) -> bool:
    """
    检查切片是否为微信我方绿色文字气泡。
    微信特有的我方绿色气泡 (#95EC69 ~ #A0EA70) 绝对是我方文字发言，绝不可能是聊天图片！
    """
    thumb = pil_crop.resize((24, 24), Image.Resampling.BOX).convert("RGB")
    pixels = list(thumb.getdata())
    green_count = 0
    for r, g, b in pixels:
        if g > 85 and (g - r >= 18) and (g - b >= 15):
            green_count += 1
    # 只要有 15% 以上像素为微信特有绿底，即判定为我方发言气泡
    return green_count >= (len(pixels) * 0.15)

def detect_chat_image_bubbles(
    cropped_img: Image.Image,
    crop_file_path: str,
    known_text_boxes: Optional[List[dict]] = None
) -> List[Dict[str, Any]]:
    """
    探测聊天视口中的真实照片/图片气泡，并转化为语义文本元素:
    严格防线：
    1. 绿色气泡绝对是我方文字发言，100% 严禁判定为图片！
    2. 头像 (左边缘对方头像、右边缘我方头像) 100% 严禁判定为图片！
    3. 已有 OCR 文本的气泡 100% 严禁判定为图片！
    """
    w, h = cropped_img.size
    url = NSURL.fileURLWithPath_(crop_file_path)
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, NSDictionary.dictionary())
    req = Vision.VNDetectRectanglesRequest.alloc().init()
    req.setMinimumSize_(0.08)
    req.setMaximumObservations_(10)

    success, _ = handler.performRequests_error_([req], None)
    if not success or not req.results():
        return []

    detected_images = []

    for r in req.results():
        bb = r.boundingBox()
        # Vision 坐标系原点为左下角，转换为 PIL 坐标系 (左上角原点)
        bx = int(bb.origin.x * w)
        by = int((1.0 - bb.origin.y - bb.size.height) * h)
        bw = int(bb.size.width * w)
        bh = int(bb.size.height * h)

        rel_x = bx / float(w)
        rel_right = (bx + bw) / float(w)

        # 1. 严格过滤头像：微信单聊左右两侧边缘均为用户头像，绝非聊天图片
        # 左侧头像区：rel_x < 0.15；右侧头像区：rel_right > 0.85
        # 且头像尺寸通常在 40~120px 之间，呈 1:1 方形
        is_avatar_position = (rel_x < 0.15) or (rel_right > 0.85)
        aspect = bw / float(bh) if bh > 0 else 1.0
        if is_avatar_position and (0.75 <= aspect <= 1.35) and (bw <= 130 and bh <= 130):
            continue

        # 2. 过滤过小或长宽比极端的杂块
        if bw < 90 or bh < 75:
            continue
        if aspect > 4.5 or aspect < 0.22:
            continue

        # 3. 裁剪并做强特征排查
        crop_box = (max(0, bx), max(0, by), min(w, bx + bw), min(h, by + bh))
        pil_crop = cropped_img.crop(crop_box)

        # 核心防线：检查是否为微信绿色气泡！绿色气泡必须是我方文本发言，绝不是图片！
        if is_wechat_green_bubble(pil_crop):
            continue

        # 4. 检查是否与已知纯文本气泡重叠 (普通文字气泡绝不能误当成图片)
        if known_text_boxes:
            is_text_bubble = False
            for tb in known_text_boxes:
                tx = int(tb["x"] * w) if tb["x"] <= 1.0 else int(tb["x"])
                ty = int((1.0 - tb["y"] - tb["h"]) * h) if tb["y"] <= 1.0 else int(tb["y"])
                tw = int(tb["w"] * w) if tb["w"] <= 1.0 else int(tb["w"])
                th = int(tb["h"] * h) if tb["h"] <= 1.0 else int(tb["h"])
                # 检查交集重叠
                intersect_w = max(0, min(bx + bw, tx + tw) - max(bx, tx))
                intersect_h = max(0, min(by + bh, ty + th) - max(by, ty))
                if intersect_w > 15 and intersect_h > 15:
                    is_text_bubble = True
                    break
            if is_text_bubble:
                continue

        # 5. 分析色彩丰富度，排除单色空白背景与普通浅灰纯文字气泡
        variance = calculate_image_variance(pil_crop)
        if variance < 32.0:
            continue

        # 6. 判断发送方: 靠右侧为 EGO (我方)，靠左侧为 TARGET (对方)
        center_x = (bx + bw / 2) / float(w)
        role = "EGO" if center_x > 0.55 else "TARGET"

        # 7. 调用多模态描述
        desc = describe_image_via_vlm(pil_crop)
        if not desc:
            tmp_crop_path = f"/tmp/echolens_img_crop_{bx}_{by}.jpg"
            pil_crop.convert("RGB").save(tmp_crop_path, "JPEG")
            desc = fallback_macos_vision_classify(tmp_crop_path)

        if not desc:
            continue

        # 8. 语义后验防线：若模型误将 UI 元素、头像或气泡文字描述出来，坚决丢弃
        noise_descs = ["聊天气泡", "绿色气泡", "头像", "文字", "聊天界面", "对话框", "深色短发", "白衬衫"]
        if any(nd in desc for nd in noise_descs):
            continue

        norm_y = 1.0 - ((by + bh / 2) / float(h))
        detected_images.append({
            "role": role,
            "text": f"[图片: {desc}]",
            "y": norm_y,
            "box": (bx, by, bw, bh)
        })

    return detected_images
