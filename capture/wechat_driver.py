"""
WeChat Chat Driver: captures chat messages, performs turn segmentation,
and validates active contact against safety guardrails.
"""
import re
from typing import Optional, Tuple, List
from PIL import Image
import config
from capture.window import find_wechat_main_window_id, capture_window_screenshot
from capture.vision_ocr import (
    run_vision_ocr,
    has_green_bubble_background,
    extract_contact_from_header
)
from core.contracts import ChatCaptureResult

def is_contact_match(detected: Optional[str], expected: Optional[str]) -> bool:
    """核验抓取到的联系人姓名与预期目标是否匹配 (防工作群穿透，容忍轻微 OCR 形近字误判)"""
    if not detected or not expected:
        return False
    d = detected.strip().lower()
    e = expected.strip().lower()
    if d == e:
        return True
    if e in d or d in e:
        return True

    # 容差模糊核验: 去掉群聊人数括号或备注空格后缀
    clean_d = re.sub(r'[\s（\(].*$', '', d)
    clean_e = re.sub(r'[\s（\(].*$', '', e)
    if clean_d and clean_e:
        if clean_d == clean_e or clean_d in clean_e or clean_e in clean_d:
            return True

        # 若名字长度 >= 2，且重合字符数占绝大部分 (如 3 字中 2 字相同)，判定为同一联系人
        common_chars = set(clean_d) & set(clean_e)
        if len(clean_e) >= 2 and len(common_chars) >= max(2, len(clean_e) - 1):
            return True

    return False

def capture_wechat_chat_context(expected_target: Optional[str] = None) -> Tuple[Optional[str], Optional[str], Optional[str], str, str]:
    """
    抓取微信聊天窗口并结算当前回合状态:
    返回 5 元组: (contact_name, target_text, ego_text, reply_status, dialogue_context)
    """
    res = capture_chat_snapshot(expected_target=expected_target)
    return (
        res.contact_name,
        res.incoming_text,
        res.ego_text,
        res.reply_status,
        res.dialogue_context
    )

def capture_chat_snapshot(expected_target: Optional[str] = None) -> ChatCaptureResult:
    """
    全景无损单次抓取与几何布局解析器：
    不再物理硬裁剪窗口图片，直接对整个微信窗口全图进行单次 Vision OCR，
    利用全局空间几何坐标解构，彻底杜绝字迹被腰斩、底部漏抓与窗口比例失调问题。
    """
    win_id = find_wechat_main_window_id(expected_target=expected_target)
    if not win_id:
        return ChatCaptureResult(reply_status="pending")

    tmp_win = "/tmp/echolens_wc_win.png"
    if not capture_window_screenshot(win_id, tmp_win):
        return ChatCaptureResult(reply_status="pending")

    # 【方案 A 核心优先通道】：大模型端到端空间语义解析 (彻底摆脱本地脆弱坐标规则)
    if config.LLM_API_KEY:
        try:
            from capture.llm_parser import parse_chat_screen_via_llm
            llm_data = parse_chat_screen_via_llm(tmp_win, expected_target=expected_target)
            if llm_data and llm_data.get("contact_name"):
                detected_contact = llm_data["contact_name"]
                if expected_target and not is_contact_match(detected_contact, expected_target):
                    return ChatCaptureResult(
                        contact_name=detected_contact,
                        reply_status="mismatch",
                        is_mismatch=True
                    )
                
                reply_status = llm_data.get("reply_status", "pending")
                case_type = 1 if "replied" in reply_status else 2
                incoming_text = llm_data.get("incoming_text", "")
                ego_text = llm_data.get("ego_text", "暂未回复")
                dialogue_context = llm_data.get("dialogue_context", f"[{detected_contact}]: {incoming_text}\n[我]: {ego_text}")
                
                raw_turns = []
                if incoming_text:
                    raw_turns.append({"role": "TARGET", "text": incoming_text, "time_hint": None, "quote": None})
                if ego_text and ego_text != "暂未回复":
                    raw_turns.append({"role": "EGO", "text": ego_text, "time_hint": None, "quote": None})
                
                return ChatCaptureResult(
                    contact_name=detected_contact,
                    incoming_text=incoming_text,
                    ego_text=ego_text,
                    reply_status="replied" if case_type == 1 else "pending",
                    dialogue_context=dialogue_context,
                    is_mismatch=False,
                    case_type=case_type,
                    raw_turns=raw_turns,
                    time_hint=None,
                    last_ego_text=ego_text
                )
        except Exception as e:
            print(f"[LLM Parser Dispatch Warning] {e}")

    try:
        img = Image.open(tmp_win)
        w, h = img.size

        # 单次全景 OCR 识别全窗口文字 (兜底方案)
        raw_obs = run_vision_ocr(tmp_win)
        if not raw_obs:
            return ChatCaptureResult(reply_status="pending")

        # 1. 顶栏活跃联系人解析 (全局几何：x 在 0.26~0.78 之间，y 在顶部 0.84~0.98 区间)
        header_cands = [o for o in raw_obs if 0.26 <= o["x"] <= 0.78 and o["y"] >= 0.84]
        header_cands.sort(key=lambda o: -o["y"])
        detected_contact = None
        ignore_header = {"q", "search", "<", ">", "微信", "wechat"}
        for c in header_cands:
            txt = c["text"].strip()
            if (txt.lower() not in ignore_header and 
                not re.search(r"^\d+$", txt) and 
                not re.match(r"^(\d{1,2}:\d{2})$", txt)):
                detected_contact = txt
                break

        # 2. 目标人安全拦截：如果与预期目标不符，立即终止 (防串台)
        if expected_target and detected_contact:
            if not is_contact_match(detected_contact, expected_target):
                return ChatCaptureResult(
                    contact_name=detected_contact,
                    reply_status="mismatch",
                    is_mismatch=True
                )

        # 3. 输入框下边界检测 (寻找底部 Send/发送 或 底部按钮，通常 y <= 0.22)
        send_btns = [
            o for o in raw_obs
            if o["text"] in ["Send", "发送"] or (o["x"] >= 0.80 and o["y"] <= 0.22) or any(k in o["text"] for k in ["按 Enter", "Ctrl+Enter"])
        ]
        input_y = max([b["y"] for b in send_btns]) + 0.04 if send_btns else 0.16

        # 4. 聊天消息区全局几何过滤：
        # 微信布局：左侧导航与会话列表占据 x < 0.35；右侧主聊天区严格占据 x >= 0.36
        # 纵向：input_y <= y < 0.84 (完全排除输入框草稿与顶部标题栏)
        chat_raw = [o for o in raw_obs if o["x"] >= 0.36 and input_y <= o["y"] < 0.84]

        # 按时间由旧到新排序 (Vision 原点在左下角，y 越大越靠上；从上到下按 -y 倒序排序)
        chat_raw.sort(key=lambda o: -o["y"])

        # 5. 过滤噪音并打标 (TIME / EGO / TARGET / QUOTE)
        elements = []
        noise_keywords = [
            "send", "发送", "按 enter", "ctrl+enter", "按 esc", "小胶囊", "点击复制",
            "抓取最新", "导入建档", "④", "口*、心", "uu.l", "曰％", "已发出"
        ]

        for item in chat_raw:
            txt = item["text"].strip()
            low = txt.lower()
            if any(k in low for k in noise_keywords):
                continue
            if not re.search(r"[\u4e00-\u9fa5a-zA-Z0-9]", txt):
                continue

            # 时间戳判定 (居中且符合时间格式)
            is_time = bool(re.search(r"(\d{1,2}:\d{2})", txt) or any(k in txt for k in ["昨天", "今天", "星期", "周一", "周二", "周三", "周四", "周五", "周六", "周日"]))
            is_centered = (0.50 <= item["x"] <= 0.75) and (item["w"] < 0.20)
            if is_time and is_centered:
                elements.append(("TIME", txt, item))
                continue

            # 角色判定：检查是否为绿底气泡，或在聊天面板右侧 (r_x > 0.80 且 x > 0.48)
            has_green = has_green_bubble_background(img, item["x"], item["y"], item["w"], item["h"])
            is_ego = has_green or (item["r_x"] > 0.80 and item["x"] > 0.48)
            if is_ego:
                elements.append(("EGO", txt, item))
            else:
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

        # 5.1 图片气泡多模态识别 (仅针对无文字的真实照片气泡，绝不干扰文字气泡与绿色发言气泡)
        try:
            from capture.image_detector import detect_chat_image_bubbles
            cw_min_x, ch_min_y = int(w * 0.35), int(h * 0.08)
            cw_max_x, ch_max_y = int(w * 0.98), int(h * (1.0 - input_y))
            chat_crop_box = (cw_min_x, ch_min_y, cw_max_x, ch_max_y)
            chat_cropped = img.crop(chat_crop_box)
            tmp_img_crop = "/tmp/echolens_wc_img_crop.png"
            chat_cropped.save(tmp_img_crop)

            # 将已知文字框换算为裁剪区相对像素坐标
            crop_text_boxes = []
            for tb in chat_raw:
                tbx = int(tb["x"] * w) - cw_min_x
                tby = int((1.0 - tb["y"] - tb["h"]) * h) - ch_min_y
                tbw = int(tb["w"] * w)
                tbh = int(tb["h"] * h)
                crop_text_boxes.append({"x": tbx, "y": tby, "w": tbw, "h": tbh})

            detected_images = detect_chat_image_bubbles(chat_cropped, tmp_img_crop, known_text_boxes=crop_text_boxes)
            for img_item in detected_images:
                # 映射回全屏 y 坐标
                full_y = input_y + (img_item["y"] * (0.84 - input_y))
                elements.append((
                    img_item["role"],
                    img_item["text"],
                    {"y": full_y, "is_image": True}
                ))
            if detected_images:
                elements.sort(key=lambda el: -el[2].get("y", 0.0))
        except Exception as e:
            print(f"[Image Detection Warning] {e}")

        if not elements:
            return ChatCaptureResult(contact_name=detected_contact, reply_status="pending")

        # 6. 回合切分与气泡折行合并
        grouped_turns = _group_turns(elements)
        if not grouped_turns:
            return ChatCaptureResult(contact_name=detected_contact, reply_status="pending")

        # 7. 构建最近 2~3 轮黄金滑动上下文流水
        dialogue_lines = []
        for t in grouped_turns[-6:]:
            spk = "我" if t["role"] == "EGO" else (detected_contact or "对方")
            time_prefix = f"[{t.get('time_hint')}] " if t.get('time_hint') else ""
            quote_suffix = f" (引用我方: \"{t['quote']}\")" if t.get('quote') else ""
            dialogue_lines.append(f"{time_prefix}[{spk}]{quote_suffix}: {t['text']}")
        dialogue_context = "\n".join(dialogue_lines)

        # 8. 判定情况 1 vs 情况 2
        last_turn = grouped_turns[-1]
        last_role = last_turn["role"]
        last_text = last_turn["text"]
        latest_time_hint = last_turn.get("time_hint")

        if last_role == "EGO":
            case_type = 1
            ego_text = last_text
            reply_status = "replied"

            prev_ego_idx = -1
            for idx in range(len(grouped_turns) - 2, -1, -1):
                if grouped_turns[idx]["role"] == "EGO":
                    prev_ego_idx = idx
                    break

            if prev_ego_idx != -1:
                target_turns_between = [
                    t["text"] for t in grouped_turns[prev_ego_idx + 1 : -1]
                    if t["role"] == "TARGET"
                ]
                last_ego_text = grouped_turns[prev_ego_idx]["text"]
            else:
                target_turns_between = [
                    t["text"] for t in grouped_turns[:-1]
                    if t["role"] == "TARGET"
                ]
                last_ego_text = ""

            incoming_text = "\n".join(target_turns_between) if target_turns_between else ""

        else:
            case_type = 2
            reply_status = "pending"

            last_ego_idx = -1
            for idx in range(len(grouped_turns) - 1, -1, -1):
                if grouped_turns[idx]["role"] == "EGO":
                    last_ego_idx = idx
                    break

            if last_ego_idx != -1:
                target_turns_below = [
                    t["text"] for t in grouped_turns[last_ego_idx + 1 :]
                    if t["role"] == "TARGET"
                ]
                last_ego_text = grouped_turns[last_ego_idx]["text"]
            else:
                target_turns_below = [
                    t["text"] for t in grouped_turns
                    if t["role"] == "TARGET"
                ]
                last_ego_text = ""

            ego_text = "暂未回复"
            incoming_text = "\n".join(target_turns_below) if target_turns_below else last_text

        return ChatCaptureResult(
            contact_name=detected_contact,
            incoming_text=incoming_text,
            ego_text=ego_text,
            reply_status=reply_status,
            dialogue_context=dialogue_context,
            is_mismatch=False,
            case_type=case_type,
            raw_turns=grouped_turns,
            time_hint=latest_time_hint,
            last_ego_text=last_ego_text
        )

    except Exception as e:
        print(f"[Chat Driver Error] {e}")

    return ChatCaptureResult(reply_status="pending")

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

