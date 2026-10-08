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

def detect_input_divider_y(img: Image.Image) -> int:
    """动态扫描微信聊天气泡区与输入框之间的水平物理分割线纵坐标 (跨屏幕与分辨率自适应)"""
    w, h = img.size
    x_start = int(w * 0.35)
    x_end = int(w * 0.90)
    # 扫描窗口 55% ~ 82% 高度范围
    for y in range(int(h * 0.55), int(h * 0.82)):
        pixels = [img.getpixel((x, y))[:3] for x in range(x_start, x_end, 6)]
        r_vals = [p[0] for p in pixels]
        g_vals = [p[1] for p in pixels]
        b_vals = [p[2] for p in pixels]
        avg_r = sum(r_vals) / len(r_vals)
        avg_g = sum(g_vals) / len(g_vals)
        avg_b = sum(b_vals) / len(b_vals)
        var = sum((r - avg_r)**2 + (g - avg_g)**2 + (b - avg_b)**2 for r, g, b in pixels) / len(pixels)
        if var < 15:  # 纯色水平横线特征
            p_above = img.getpixel((int(w * 0.5), y - 2))[:3]
            p_curr = img.getpixel((int(w * 0.5), y))[:3]
            diff = sum(abs(a - b) for a, b in zip(p_above, p_curr))
            if diff > 15:
                return y
    return int(h * 0.73)  # 兜底安全边界

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

        # 3. 动态自适应裁剪聊天消息气泡区域 (精准停在输入框分割线上方，跨屏幕与分辨率自适应)
        img = Image.open(tmp_win)
        w, h = img.size
        divider_y = detect_input_divider_y(img)
        crop_bottom = min(divider_y - 2, int(h * 0.74))
        crop_box = (int(w * 0.32), int(h * 0.09), int(w * 0.98), crop_bottom)
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
    noise_keywords = [
        "send", "发送", "按 enter", "ctrl+enter", "按 esc", "小胶囊", "点击复制",
        "抓取最新", "导入建档", "④", "口*、心", "uu.l", "曰％", "已发出"
    ]

    elements = []
    in_quote = False

    for item in obs_list:
        txt = item["txt"].strip()
        low = txt.lower()

        # 1. 强特征语义过滤：绝对排除输入框按钮词与无意义乱码
        if any(k in low for k in noise_keywords):
            continue
        if not re.search(r"[\u4e00-\u9fa5a-zA-Z0-9]", txt):
            continue
        # 过滤底部单字或残损标点
        if len(txt) == 1 and item["y"] < 0.15:
            continue

        # 2. 时间戳与系统日期判定
        if re.search(r"(\d{1,2}:\d{2})", txt) and 0.22 <= item["x"] <= 0.78:
            elements.append(("TIME", txt, item))
            in_quote = False
            continue

        # 3. 角色判定：绿色气泡或靠右对齐严格判定为我方 (EGO)
        is_ego = item["has_green"] or (item["r_x"] > 0.75 and item["x"] > 0.12)
        if is_ego:
            elements.append(("EGO", txt, item))
            in_quote = False
        else:
            # 4. 对方 (TARGET) 气泡内引用判定 (单聊中任何 `xxx：` 均为对方引用我方发言)
            m = re.match(r"^([^\n：:]{1,16})[：:](.*)", txt)
            if m:
                in_quote = True
                quoted_body = m.group(2).strip()
                elements.append(("QUOTE_EGO", quoted_body or txt, item))
                continue
            elif in_quote:
                # 引用块通常较短且为前置引用
                if item["w"] < 0.50 and not any(txt.startswith(k) for k in ["要么", "但是", "不过", "其实", "而且", "主要是", "哈哈", "是啊", "对啊"]):
                    elements.append(("QUOTE_EGO", txt, item))
                    continue
                else:
                    in_quote = False
                    elements.append(("TARGET", txt, item))
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

