"""
WeChat Chat Driver: captures chat messages, performs turn segmentation,
and validates active contact against safety guardrails.
"""
import re
from typing import Optional, Tuple, List
from PIL import Image
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
    核心执行器：单次静默抓取并构建高内聚的 ChatCaptureResult
    """
    win_id = find_wechat_main_window_id()
    if not win_id:
        return ChatCaptureResult(reply_status="pending")

    tmp_win = "/tmp/echolens_wc_win.png"
    tmp_crop = "/tmp/echolens_wc_crop.png"

    if not capture_window_screenshot(win_id, tmp_win):
        return ChatCaptureResult(reply_status="pending")

    try:
        # 1. 识别顶栏联系人
        detected_contact = extract_contact_from_header(tmp_win)

        # 2. 目标人安全拦截：如果与预期目标不符，立即终止
        if expected_target and detected_contact:
            if not is_contact_match(detected_contact, expected_target):
                return ChatCaptureResult(
                    contact_name=detected_contact,
                    reply_status="mismatch",
                    is_mismatch=True
                )

        # 3. 裁剪聊天消息气泡区域 (排除底部输入框，保留 100% 原生视网膜高清分辨率，杜绝字迹笔画模糊误判)
        img = Image.open(tmp_win)
        w, h = img.size
        crop_box = (int(w * 0.32), int(h * 0.10), int(w * 0.98), int(h * 0.89))
        cropped = img.crop(crop_box)
        cropped.save(tmp_crop)

        # 4. 执行 OCR 并提取像素特征
        raw_obs = run_vision_ocr(tmp_crop)
        if not raw_obs:
            return ChatCaptureResult(contact_name=detected_contact, reply_status="pending")

        obs_list = []
        for item in raw_obs:
            has_green = has_green_bubble_background(
                cropped, item["x"], item["y"], item["w"], item["h"]
            )
            obs_list.append({
                "y": item["y"],
                "x": item["x"],
                "w": item["w"],
                "r_x": item["r_x"],
                "txt": item["text"],
                "has_green": has_green
            })

        # 按时间自上而下排序 (y 倒序)
        obs_list.sort(key=lambda it: -it["y"])

        # 5. 过滤时间标签与日历组件
        filtered_elements = _filter_and_tag_bubbles(obs_list)
        if not filtered_elements:
            return ChatCaptureResult(contact_name=detected_contact, reply_status="pending")

        # 6. 回合切分与气泡折行合并 (Turn Grouping with time hint tracking)
        grouped_turns = _group_turns(filtered_elements)
        if not grouped_turns:
            return ChatCaptureResult(contact_name=detected_contact, reply_status="pending")

        # 7. 构建最近 2~3 轮黄金滑动上下文流水
        dialogue_lines = []
        for t in grouped_turns[-6:]:
            spk = "我" if t["role"] == "EGO" else (detected_contact or "对方")
            time_prefix = f"[{t.get('time_hint')}] " if t.get('time_hint') else ""
            dialogue_lines.append(f"{time_prefix}[{spk}]: {t['text']}")
        dialogue_context = "\n".join(dialogue_lines)

        # 8. 判定情况 1 vs 情况 2:
        last_turn = grouped_turns[-1]
        last_role = last_turn["role"]
        last_text = last_turn["text"]
        latest_time_hint = last_turn.get("time_hint")

        if last_role == "EGO":
            # 情况 1: 如果最后一条是我的回复，说明这个是我最新的回复消息
            # 然后和上一次我回复消息之间的所有都是对方的消息，一块展示到对方那栏
            case_type = 1
            ego_text = last_text
            reply_status = "replied"

            # 寻找倒数第二次 EGO (上一次我的回复)
            prev_ego_idx = -1
            for idx in range(len(grouped_turns) - 2, -1, -1):
                if grouped_turns[idx]["role"] == "EGO":
                    prev_ego_idx = idx
                    break

            # 上一次我的回复与这次我的回复之间所有的对方消息
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
            # 情况 2: 如果最后一条不是我的回复（是对方的消息）
            # 找到上一次我的消息，上一次我的消息下面的所有就都是对方最新的消息，我还没回复
            case_type = 2
            reply_status = "pending"

            # 寻找上一次我的消息 (最后一个 EGO)
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

            # 保留我方上一句真实回复，绝不在对方来消息时清空抹除为无
            ego_text = last_ego_text or "暂未回复"
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

def _filter_and_tag_bubbles(obs_list: List[dict], ego_aliases: List[str] = None) -> List[tuple]:
    """过滤杂音并打标角色 (TIME / EGO / TARGET / QUOTE_EGO)"""
    alias_set = set(ego_aliases or ["我", "自己"])

    def is_timestamp(txt: str, x: float) -> bool:
        t = txt.strip().lower()
        if re.search(r"(\d{1,2}:\d{2})", t):
            return True
        if any(k in t for k in ["yesterday", "today", "昨天", "今天", "周一", "周二", "周三", "周四", "周五", "周六", "周日"]) and 0.15 <= x <= 0.85:
            return True
        return False

    def is_calendar_widget(txt: str, y: float, x: float) -> bool:
        if y > 0.80 and (re.search(r"\d{1,2}/\d{2}", txt) or any(k in txt for k in ["周", "陶", "尚"]) or x < 0.20):
            return True
        return False

    elements = []
    in_ego_quote = False
    for item in obs_list:
        txt = item["txt"]
        if is_calendar_widget(txt, item["y"], item["x"]):
            continue
        if len(txt) <= 1 and not re.match(r"[\u4e00-\u9fa5]", txt):
            continue
        if is_timestamp(txt, item["x"]):
            elements.append(("TIME", txt, item))
            in_ego_quote = False
        else:
            # 严格依据微信绿色气泡与靠右对齐特征判别我方发言
            is_ego = item["has_green"] or (item["r_x"] > 0.78 and item["x"] > 0.25)
            if is_ego:
                elements.append(("EGO", txt, item))
                in_ego_quote = False
            else:
                # 对方气泡内检测是否在引用我方发言 (例如: 我方：我记得...)
                m = re.match(r"^([^\n：]{1,8})：(.*)", txt)
                if m and m.group(1).strip() in alias_set:
                    in_ego_quote = True
                    quoted_body = m.group(2).strip()
                    if quoted_body:
                        elements.append(("QUOTE_EGO", quoted_body, item))
                    continue
                elif in_ego_quote:
                    # 微信引用气泡内部通常只有1~2行紧凑文字，若出现新起头词则回归对方正文
                    if any(txt.startswith(k) for k in ["是啊", "对啊", "哈哈", "我也", "不过", "但是", "确实", "主要是", "没啊", "好的", "行啊"]) or txt.endswith(("。", "！", "？", "!", "?", "，")):
                        in_ego_quote = False
                        elements.append(("TARGET", txt, item))
                    else:
                        elements.append(("QUOTE_EGO", txt, item))
                        in_ego_quote = False
                else:
                    elements.append(("TARGET", txt, item))
    return elements

def _group_turns(elements: List[tuple]) -> List[Dict[str, Any]]:
    """聚合连击短气泡并智能合并中文折行长句，关联时间戳，剥离引用污染"""
    grouped = []
    current_role = None
    current_lines = []
    current_time_hint = None
    current_quote = []

    for role, txt, _ in elements:
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
        else:
            # 中文自然折行判定
            if (current_lines and 
                len(current_lines[-1]) > 0 and 
                not current_lines[-1].endswith(("。", "！", "？", "…", "，", ",", "!", "?", "；", ";")) and
                re.match(r"[\u4e00-\u9fa5]", current_lines[-1][-1]) and
                re.match(r"[\u4e00-\u9fa5]", txt[0])):
                current_lines[-1] += txt
            else:
                current_lines.append(txt)

    if current_role and current_lines:
        grouped.append({
            "role": current_role,
            "text": "\n".join(current_lines),
            "time_hint": current_time_hint,
            "quote": "\n".join(current_quote) if current_quote else None
        })

    return grouped

