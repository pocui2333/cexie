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

def detect_chat_image_bubbles(
    cropped_img: Image.Image,
    crop_file_path: str,
    known_text_boxes: Optional[List[dict]] = None
) -> List[Dict[str, Any]]:
    """
    探测聊天视口中的所有图片/照片气泡，并转化为语义文本元素:
    返回格式: [{"role": "TARGET"|"EGO", "text": "[图片: ...]", "y": float, "box": (x, y, w, h)}]
    """
    w, h = cropped_img.size
    url = NSURL.fileURLWithPath_(crop_file_path)
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, NSDictionary.dictionary())
    req = Vision.VNDetectRectanglesRequest.alloc().init()
    req.setMinimumSize_(0.06)
    req.setMaximumObservations_(15)

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

        # 1. 过滤边缘头像: 靠左(x < 0.08)或靠右(x > 0.92)且尺寸在头像区间的排除
        rel_x = bx / float(w)
        if (rel_x < 0.06 and bw < int(w * 0.12)) or (rel_x > 0.88 and bw < int(w * 0.12)):
            continue

        # 2. 过滤过小或过长条的非图片杂块
        if bw < 80 or bh < 60:
            continue
        aspect = bw / float(bh)
        if aspect > 5.0 or aspect < 0.2:
            continue

        # 2.5 检查是否与已知纯文本气泡重叠 (避免将单行/多行普通文字气泡误判为图片)
        if known_text_boxes:
            is_pure_text_bubble = False
            for tb in known_text_boxes:
                tx = int(tb["x"] * w)
                ty = int((1.0 - tb["y"] - tb["h"]) * h)
                tw = int(tb["w"] * w)
                th = int(tb["h"] * h)
                tc_x = tx + tw / 2
                tc_y = ty + th / 2
                if bx <= tc_x <= bx + bw and by <= tc_y <= by + bh:
                    # 文字占矩形主要高度，或为我方绿底气泡，判定为普通文字气泡
                    if th > 0.30 * bh or tb.get("has_green"):
                        is_pure_text_bubble = True
                        break
            if is_pure_text_bubble:
                continue

        # 3. 裁剪并分析色彩丰富度
        crop_box = (max(0, bx), max(0, by), min(w, bx + bw), min(h, by + bh))
        pil_crop = cropped_img.crop(crop_box)
        variance = calculate_image_variance(pil_crop)

        # 若颜色方差很低 (纯白/纯灰/纯绿)，说明是纯文字气泡或空白背景，跳过
        if variance < 28.0:
            continue

        # 4. 判断发送方: 靠右侧为 EGO (我方)，靠左侧为 TARGET (对方)
        center_x = (bx + bw / 2) / float(w)
        role = "EGO" if center_x > 0.55 else "TARGET"

        # 5. 调用 VLM 进行多模态视觉描述提取
        desc = describe_image_via_vlm(pil_crop)
        if not desc:
            # 临时保存切片供本地分类
            tmp_crop_path = f"/tmp/echolens_img_crop_{bx}_{by}.jpg"
            pil_crop.convert("RGB").save(tmp_crop_path, "JPEG")
            desc = fallback_macos_vision_classify(tmp_crop_path)

        if not desc:
            desc = "照片/图片分享"

        # 6. 计算 Vision 归一化 y 坐标 (原点在左下角，便于与 OCR 文本自上而下对齐)
        norm_y = 1.0 - ((by + bh / 2) / float(h))

        detected_images.append({
            "role": role,
            "text": f"[图片: {desc}]",
            "y": norm_y,
            "box": (bx, by, bw, bh)
        })

    return detected_images
