"""
WeChat Chat Driver: captures chat messages, performs turn segmentation,
and validates active contact against safety guardrails.
"""
import logging
import os
import re
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image
import config
from core import llm_client
from core.contracts import ChatCaptureResult, NO_REPLY
from capture.names import is_contact_match
from capture.window import find_wechat_main_window_id, capture_window_screenshot
from capture.vision_ocr import run_vision_ocr, has_green_bubble_background

logger = logging.getLogger(__name__)

# 标题栏 / 主聊天区的全局几何边界 (Vision 坐标: 原点左下角，y 越大越靠上)
HEADER_MIN_Y = 0.84
CHAT_MIN_X = 0.36
CHAT_TOP_Y = 0.84
IMAGE_CROP_TOP_Y = 0.92

_NOISE_KEYWORDS = [
    "send", "发送", "按 enter", "ctrl+enter", "按 esc", "小胶囊", "点击复制",
    "抓取最新", "导入建档", "④", "口*、心", "uu.l", "曰％", "已发出"
]
_TIME_WORDS = ["昨天", "今天", "星期", "周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def capture_chat_snapshot(expected_target: Optional[str] = None) -> ChatCaptureResult:
    """
    全景单次抓取：截取微信窗口 -> 单次 Vision OCR -> 标题栏核验联系人 -> 气泡归属与图片识别
    -> (可选) 大模型语义归并 / 本地规则回合切分。
    截图仅写入当前用户私有的临时目录，解析结束后立即删除。
    """
    win_id = find_wechat_main_window_id(expected_target=expected_target)
    if not win_id:
        return ChatCaptureResult(reply_status="pending")

    work_dir = tempfile.mkdtemp(prefix="capture-", dir=config.private_tmp_dir())
    try:
        shot_path = os.path.join(work_dir, "window.png")
        if not capture_window_screenshot(win_id, shot_path):
            return ChatCaptureResult(reply_status="pending")
        return _parse_window_screenshot(shot_path, work_dir, expected_target)
    except Exception as e:
        logger.error("[Chat Driver Error] %s", e)
        return ChatCaptureResult(reply_status="pending")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _detect_header_contact(raw_obs: List[Dict[str, Any]]) -> Optional[str]:
    """顶栏活跃联系人解析 (全局几何：x 在 0.26~0.78 之间，y 在顶部 0.84 以上)"""
    header_cands = [o for o in raw_obs if 0.26 <= o["x"] <= 0.78 and o["y"] >= HEADER_MIN_Y]
    header_cands.sort(key=lambda o: -o["y"])
    ignore_header = {"q", "search", "<", ">", "微信", "wechat"}
    for c in header_cands:
        txt = c["text"].strip()
        if (txt.lower() not in ignore_header and
                not re.search(r"^\d+$", txt) and
                not re.match(r"^(\d{1,2}:\d{2})$", txt)):
            return txt
    return None


def _tag_chat_elements(img: Image.Image, chat_raw: List[Dict[str, Any]]) -> List[Tuple[str, str, Dict[str, Any]]]:
    """过滤噪音并打标 (TIME / EGO / TARGET / QUOTE_EGO)，chat_raw 需已按从上到下排序"""
    elements = []
    for item in chat_raw:
        txt = item["text"].strip()
        low = txt.lower()
        if any(k in low for k in _NOISE_KEYWORDS):
            continue
        if not re.search(r"[\u4e00-\u9fa5a-zA-Z0-9]", txt):
            continue

        # 时间戳判定 (居中且符合时间格式)
        is_time = bool(re.search(r"(\d{1,2}:\d{2})", txt) or any(k in txt for k in _TIME_WORDS))
        is_centered = (0.50 <= item["x"] <= 0.75) and (item["w"] < 0.20)
        if is_time and is_centered:
            elements.append(("TIME", txt, item))
            continue

        # 角色判定：检查是否为绿底气泡，或在聊天面板右侧 (r_x > 0.80 且 x > 0.48)
        has_green = has_green_bubble_background(img, item["x"], item["y"], item["w"], item["h"])
        if has_green or (item["r_x"] > 0.80 and item["x"] > 0.48):
            elements.append(("EGO", txt, item))
            continue

        # 对方气泡内引用判定 (单聊中任何 `xxx：` 均为对方引用我方发言)
        m = re.match(r"^([^\n：:]{1,16})[：:]([\s\S]*)", txt)
        if m:
            if "\n" in txt:
                p1, p2 = txt.split("\n", 1)
                elements.append(("QUOTE_EGO", p1.strip(), item))
                if p2.strip():
                    elements.append(("TARGET", p2.strip(), item))
            else:
                elements.append(("QUOTE_EGO", txt, item))
        else:
            elements.append(("TARGET", txt, item))
    return elements


def _detect_image_elements(
    img: Image.Image, chat_raw: List[Dict[str, Any]], input_y: float, work_dir: str
) -> List[Tuple[str, str, Dict[str, Any]]]:
    """图片气泡多模态识别 (仅针对无文字的真实照片气泡，绝不干扰文字气泡与绿色发言气泡)"""
    try:
        from capture.image_detector import detect_chat_image_bubbles
        w, h = img.size
        cw_min_x, ch_min_y = int(w * 0.35), int(h * (1.0 - IMAGE_CROP_TOP_Y))
        cw_max_x, ch_max_y = int(w * 0.98), int(h * (1.0 - input_y))
        chat_cropped = img.crop((cw_min_x, ch_min_y, cw_max_x, ch_max_y))
        crop_path = os.path.join(work_dir, "chat_area.png")
        chat_cropped.save(crop_path)

        # 将已知文字框换算为裁剪区相对像素坐标
        crop_text_boxes = []
        for tb in chat_raw:
            crop_text_boxes.append({
                "x": int(tb["x"] * w) - cw_min_x,
                "y": int((1.0 - tb["y"] - tb["h"]) * h) - ch_min_y,
                "w": int(tb["w"] * w),
                "h": int(tb["h"] * h),
            })

        detected = detect_chat_image_bubbles(
            chat_cropped, crop_path, known_text_boxes=crop_text_boxes, work_dir=work_dir
        )
        # 裁剪区纵向覆盖 Vision y ∈ [input_y, IMAGE_CROP_TOP_Y]，映射回全窗口 y 坐标
        return [
            (d["role"], d["text"], {"y": input_y + d["y"] * (IMAGE_CROP_TOP_Y - input_y), "is_image": True})
            for d in detected
        ]
    except Exception as e:
        logger.warning("[Image Detection Warning] %s", e)
        return []


def _parse_window_screenshot(shot_path: str, work_dir: str, expected_target: Optional[str]) -> ChatCaptureResult:
    img = Image.open(shot_path).convert("RGB")

    raw_obs = run_vision_ocr(shot_path)
    if not raw_obs:
        return ChatCaptureResult(reply_status="pending")

    # 1. 目标人安全拦截 (fail-closed)：标题栏识别不到或与预期不符时一律不抓取，防止串台写错档案
    detected_contact = _detect_header_contact(raw_obs)
    if expected_target and not is_contact_match(detected_contact, expected_target):
        return ChatCaptureResult(contact_name=detected_contact, reply_status="mismatch", is_mismatch=True)

    # 2. 输入框下边界检测 (寻找底部 Send/发送 或 底部按钮，通常 y <= 0.22)
    send_btns = [
        o for o in raw_obs
        if o["text"] in ["Send", "发送"] or (o["x"] >= 0.80 and o["y"] <= 0.22) or any(k in o["text"] for k in ["按 Enter", "Ctrl+Enter"])
    ]
    input_y = max([b["y"] for b in send_btns]) + 0.04 if send_btns else 0.16

    # 3. 聊天消息区全局几何过滤 (排除左侧会话列表、输入框草稿与顶部标题栏)，按从上到下排序
    chat_raw = [o for o in raw_obs if o["x"] >= CHAT_MIN_X and input_y <= o["y"] < CHAT_TOP_Y]
    chat_raw.sort(key=lambda o: -o["y"])

    elements = _tag_chat_elements(img, chat_raw)
    image_elements = _detect_image_elements(img, chat_raw, input_y, work_dir)
    if image_elements:
        elements.extend(image_elements)
        elements.sort(key=lambda el: -el[2].get("y", 0.0))

    if not elements:
        return ChatCaptureResult(contact_name=detected_contact, reply_status="pending")

    grouped_turns = _group_turns(elements)

    # 4. 【优先通道】大模型语义归并 (复用本地 OCR 与气泡归属结果)
    if llm_client.is_enabled():
        from capture.llm_parser import parse_chat_elements_via_llm
        llm_data = parse_chat_elements_via_llm(elements, contact_name=detected_contact)
        if llm_data:
            return _result_from_llm(llm_data, detected_contact, grouped_turns)

    # 5. 本地规则兜底
    if not grouped_turns:
        return ChatCaptureResult(contact_name=detected_contact, reply_status="pending")
    return _result_from_turns(grouped_turns, detected_contact)


def _build_dialogue_context(grouped_turns: List[Dict[str, Any]], contact: Optional[str]) -> str:
    """构建最近 2~3 轮滑动上下文流水"""
    lines = []
    for t in grouped_turns[-6:]:
        spk = "我" if t["role"] == "EGO" else (contact or "对方")
        time_prefix = f"[{t.get('time_hint')}] " if t.get("time_hint") else ""
        quote_suffix = f" (引用我方: \"{t['quote']}\")" if t.get("quote") else ""
        lines.append(f"{time_prefix}[{spk}]{quote_suffix}: {t['text']}")
    return "\n".join(lines)


def _result_from_llm(llm_data: Dict[str, Any], contact: Optional[str], grouped_turns: List[Dict[str, Any]]) -> ChatCaptureResult:
    replied = "replied" in (llm_data.get("reply_status") or "")
    incoming_text = llm_data.get("incoming_text") or ""
    ego_text = llm_data.get("ego_text") or NO_REPLY
    dialogue_context = llm_data.get("dialogue_context") or _build_dialogue_context(grouped_turns, contact)
    return ChatCaptureResult(
        contact_name=contact,
        incoming_text=incoming_text,
        ego_text=ego_text,
        reply_status="replied" if replied else "pending",
        dialogue_context=dialogue_context,
        case_type=1 if replied else 2,
        # 记忆沉淀使用本地逐气泡切分的轮次 (比模型汇总文本更细、更稳定，便于去重)
        raw_turns=grouped_turns,
        time_hint=grouped_turns[-1].get("time_hint") if grouped_turns else None,
        last_ego_text=ego_text if ego_text != NO_REPLY else ""
    )


def _result_from_turns(grouped_turns: List[Dict[str, Any]], contact: Optional[str]) -> ChatCaptureResult:
    """判定情况 1 (最后一条是我方) vs 情况 2 (待我回复)，并切出对应的对方消息"""
    last_turn = grouped_turns[-1]
    last_ego_idx = max((i for i, t in enumerate(grouped_turns) if t["role"] == "EGO"), default=-1)

    if last_turn["role"] == "EGO":
        case_type, reply_status, ego_text = 1, "replied", last_turn["text"]
        prev_ego_idx = max((i for i, t in enumerate(grouped_turns[:-1]) if t["role"] == "EGO"), default=-1)
        between = grouped_turns[prev_ego_idx + 1:-1]
        last_ego_text = grouped_turns[prev_ego_idx]["text"] if prev_ego_idx != -1 else ""
        incoming_text = "\n".join(t["text"] for t in between if t["role"] == "TARGET")
    else:
        case_type, reply_status, ego_text = 2, "pending", NO_REPLY
        below = grouped_turns[last_ego_idx + 1:]
        last_ego_text = grouped_turns[last_ego_idx]["text"] if last_ego_idx != -1 else ""
        incoming_text = "\n".join(t["text"] for t in below if t["role"] == "TARGET") or last_turn["text"]

    return ChatCaptureResult(
        contact_name=contact,
        incoming_text=incoming_text,
        ego_text=ego_text,
        reply_status=reply_status,
        dialogue_context=_build_dialogue_context(grouped_turns, contact),
        is_mismatch=False,
        case_type=case_type,
        raw_turns=grouped_turns,
        time_hint=last_turn.get("time_hint"),
        last_ego_text=last_ego_text
    )

def _group_turns(elements: List[tuple]) -> List[Dict[str, Any]]:
    """聚合连击短气泡并智能合并中文折行长句，关联时间戳，剥离引用污染"""
    grouped = []
    current_role = None
    current_lines = []
    current_time_hint = None
    current_quote = []
    last_y = None

    for role, txt, item in elements:
        y = item.get("y", 0.0) if isinstance(item, dict) else 0.0
        if role == "TIME":
            current_time_hint = txt
            continue

        # 我方被引用的文字单独作为引用资产记录，绝不污染对方说话正文
        if role == "QUOTE_EGO":
            current_quote.append(txt)
            continue

        if role != current_role:
            if current_role and current_lines:
                grouped.append({
                    "role": current_role,
                    "text": "\n".join(current_lines),
                    "time_hint": current_time_hint,
                    "quote": "\n".join(current_quote) if current_quote else None
                })
                current_quote = []
            current_role = role
            current_lines = [txt]
            last_y = y
        else:
            # 中文自然折行判定：垂直距离极近 (同气泡内折行，delta_y < 0.032) 且上一行未以标点结束
            is_same_bubble = (last_y is not None) and (abs(last_y - y) < 0.032)
            if (is_same_bubble and current_lines and 
                not current_lines[-1].endswith(("。", "！", "？", "…", "，", ",", "!", "?", "；", ";")) and
                re.match(r"[\u4e00-\u9fa5]", current_lines[-1][-1]) and
                re.match(r"[\u4e00-\u9fa5]", txt[0])):
                current_lines[-1] += txt
            else:
                current_lines.append(txt)
            last_y = y

    if current_role and current_lines:
        grouped.append({
            "role": current_role,
            "text": "\n".join(current_lines),
            "time_hint": current_time_hint,
            "quote": "\n".join(current_quote) if current_quote else None
        })

    return grouped

