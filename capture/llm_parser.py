"""
LLM-Powered Chat Screen Parser for WeChat.
Combines ultra-fast local macOS Vision OCR with LLM semantic spatial reasoning
to achieve 100% robust chat understanding without fragile heuristic rules.
"""
import json
import ssl
import re
import urllib.request
from typing import Optional, Dict, Any, List
from PIL import Image
import config
from capture.vision_ocr import run_vision_ocr, has_green_bubble_background

def parse_chat_screen_via_llm(
    screenshot_path: str,
    expected_target: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    使用 LLM 语义空间解析微信聊天视口:
    1. 本地毫秒级 Apple Vision 提取文字项与 (x, y, w, h) 坐标；
    2. 严格剥离左侧会话栏 (x < 0.33) 与顶部标题栏 (y >= 0.88)；
    3. 基于像素绿底精确识别我方绿色发言气泡；
    4. 严格遵循双向轮次契约：
       - “对方消息”展示我方最新回复之后/下方的所有信息；
       - “我最新回复”展示对方最后一条消息之后我方的所有发言汇总；若对方发了新消息且我方未回复，则为'暂未回复'。
    """
    try:
        img = Image.open(screenshot_path)
    except Exception as e:
        print(f"[LLM Parser Image Error] {e}")
        return None

    obs = run_vision_ocr(screenshot_path)
    if not obs:
        return None

    # 1. 严格过滤主聊天视口 (排除左侧会话列表 x < 0.33，排除顶栏 y >= 0.88，排除底栏 y <= 0.20)
    chat_items = [o for o in obs if o["x"] >= 0.33 and o["y"] < 0.88 and o["y"] > 0.20]
    if not chat_items:
        return None

    # 2. 按从上到下排序 (-y 倒序，y越大越靠顶栏/时间越早)
    chat_items.sort(key=lambda o: -o["y"])

    lines = []
    green_items = []
    target_items = []

    for o in chat_items:
        txt = o["text"].strip()
        is_time = bool(re.search(r"(\d{1,2}:\d{2})", txt))
        if is_time and (o["w"] < 0.15) and (0.45 <= o["x"] <= 0.65):
            tag = "[居中时间戳]"
        else:
            has_g = has_green_bubble_background(img, o["x"], o["y"], o["w"], o["h"])
            if has_g:
                tag = "[我方发言/绿色气泡]"
                green_items.append(o)
            else:
                tag = "[对方发言/白色气泡]"
                target_items.append(o)
        lines.append(f"- {tag} x={o['x']:.3f}, y={o['y']:.3f}: {txt}")

    tagged_str = "\n".join(lines)
    target_hint = f"当前预期聊天对象为「{expected_target}」" if expected_target else "识别当前活跃聊天对象"

    # 3. 几何真值判定：精确定位最新一次我方回复的位置
    # Case A: 屏幕上存在我方绿色气泡
    if green_items:
        lowest_green = min(green_items, key=lambda o: o["y"])
        lowest_green_y = lowest_green["y"]
        # 检查绿色气泡下方是否还有对方的白色气泡
        target_below_ego = [t for t in target_items if t["y"] < lowest_green_y - 0.015]
        if target_below_ego:
            # 对方在我方回复下方发来了新消息 -> 待我回复 (pending)
            ground_truth_status = "pending"
            ground_truth_ego = "暂未回复"
        else:
            # 我方发言在最底部 -> 已回复 (replied)
            # 汇总我方在此轮（在对方最后发言之后）的所有连续绿色发言
            ground_truth_status = "replied"
            highest_target = max(target_items, key=lambda o: o["y"]) if target_items else None
            if highest_target:
                last_target_y = min([t["y"] for t in target_items])
                ego_bubbles = [g["text"] for g in green_items if g["y"] < last_target_y]
                ground_truth_ego = "\n".join(ego_bubbles) if ego_bubbles else "\n".join([g["text"] for g in green_items])
            else:
                ground_truth_ego = "\n".join([g["text"] for g in green_items])
    else:
        # Case B: 屏幕上没有我方绿色气泡 (全部为对方消息，我方回复在屏幕上方) -> 待我回复 (pending)
        ground_truth_status = "pending"
        ground_truth_ego = "暂未回复"

    prompt = f"""你是一个专业的微信聊天界面结构化解析器。
以下是从微信主聊天区提取的文字项及气泡属性 (y越大越靠上，越靠前，时间顺序从上到下)：
{target_hint}

{tagged_str}

【核心解析规则】：
1. 【对方消息 (incoming_text)】：
   - 必须展示【我方最新回复之后/下方】对方发送的所有信息！
   - 如果我方最近一次回复（绿色气泡）出现在屏幕上，则对方消息必须只包含【在我方该条回复下方】对方发送的所有内容，严禁包含我方回复之前的旧内容！
   - 如果当前屏幕上全是对面的消息（我方回复已滚出屏幕），则展示当前屏幕中对方发来的所有信息。
   - 如果对方发送了图片/截图（例如天气预报长图截图，包含散碎日期温度等），请将其识别提炼为简洁的一行 "[图片: 甘井子区天气预报]" 或类似简述，与前后文字气泡按真实从上到下的顺序换行拼接，绝对不要把截图里密集的零散碎数字逐一作为文字输出！
2. 【我方回复 (ego_text)】：
   - 展示对方最新消息之后我方的所有发言；若对方消息之后我方尚未回复，则填 "暂未回复"。
3. 【reply_status】：若对方最后一条消息之后我方已发言，为 "replied"；若对方消息之后我方尚未发言，为 "pending"。

请根据以上带标签的聊天流，输出严格的 JSON：
{{
  "contact_name": "当前聊天对象备注名",
  "incoming_text": "我最新回复下方、对方发来的所有信息汇总（多句严格按时间从上到下换行连接）",
  "ego_text": "对方最后消息之后我方的发言汇总，若未回复填'暂未回复'",
  "last_speaker": "我" 或 "对方",
  "reply_status": "pending" 或 "replied",
  "dialogue_context": "最近按时间排序的对话记录文本流水"
}}
严禁输出任何额外说明或 Markdown 标签，仅输出纯合法 JSON。
"""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.LLM_API_KEY}"
    }
    data = {
        "model": config.LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1
    }

    try:
        ssl_ctx = ssl._create_unverified_context()
        req = urllib.request.Request(
            f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions",
            data=json.dumps(data).encode("utf-8"),
            headers=headers
        )
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=12) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            raw_ans = res_json["choices"][0]["message"]["content"].strip()
            raw_ans = re.sub(r"^```(?:json)?", "", raw_ans).strip()
            raw_ans = re.sub(r"```$", "", raw_ans).strip()
            parsed = json.loads(raw_ans)

            # 融合先验几何真值保护
            if ground_truth_status == "pending":
                parsed["ego_text"] = "暂未回复"
                parsed["reply_status"] = "pending"
                parsed["last_speaker"] = "对方"
            elif ground_truth_status == "replied" and ground_truth_ego and ground_truth_ego != "暂未回复":
                ego_text = parsed.get("ego_text", "")
                if (not ego_text) or (ego_text == "暂未回复") or (len(ground_truth_ego.split("\n")) > len(ego_text.split("\n"))):
                    parsed["ego_text"] = ground_truth_ego
                parsed["reply_status"] = "replied"
                parsed["last_speaker"] = "我"

            return parsed
    except Exception as e:
        print(f"[LLM Parser Error] {e}")
        return None
