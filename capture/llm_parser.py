"""
LLM-Powered Chat Screen Parser for WeChat.
复用 wechat_driver 已完成的本地 OCR、气泡归属 (绿底=我方) 与图片描述结果，
交给大模型做语义层面的轮次归并；联系人身份由本地标题栏 OCR 判定，绝不交给模型推断。
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from core import llm_client
from core.contracts import NO_REPLY

logger = logging.getLogger(__name__)

_TAGS = {
    "TIME": "[居中时间戳]",
    "EGO": "[我方发言/绿色气泡]",
    "TARGET": "[对方发言/白色气泡]",
    "QUOTE_EGO": "[对方引用我方的话]",
}


def _ground_truth(elements: List[Tuple[str, str, Dict[str, Any]]]) -> Tuple[str, str]:
    """几何真值：根据最低处的我方 / 对方气泡位置判定是否已回复 (y 越小越靠下越新)"""
    green = [(txt, item.get("y", 0.0)) for role, txt, item in elements if role == "EGO"]
    target = [(txt, item.get("y", 0.0)) for role, txt, item in elements if role == "TARGET"]
    if not green:
        # 屏幕上没有我方绿色气泡 (我方回复已滚出屏幕) -> 待我回复
        return "pending", NO_REPLY
    lowest_green_y = min(y for _, y in green)
    if any(y < lowest_green_y - 0.015 for _, y in target):
        # 对方在我方回复下方发来了新消息 -> 待我回复
        return "pending", NO_REPLY
    # 我方发言在最底部 -> 汇总对方最后发言之后的连续绿色发言
    if target:
        last_target_y = min(y for _, y in target)
        ego_bubbles = [txt for txt, y in green if y < last_target_y]
        if ego_bubbles:
            return "replied", "\n".join(ego_bubbles)
    return "replied", "\n".join(txt for txt, _ in green)


def parse_chat_elements_via_llm(
    elements: List[Tuple[str, str, Dict[str, Any]]],
    contact_name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """elements 为按从上到下排序的 (role, text, item) 列表；失败返回 None 由调用方走本地规则兜底"""
    if not elements:
        return None

    lines = []
    for role, txt, item in elements:
        tag = _TAGS.get(role, f"[{role}]")
        if item.get("is_image"):
            tag += "[图片]"
        lines.append(f"- {tag} y={item.get('y', 0.0):.3f}: {txt}")
    tagged_str = "\n".join(lines)
    who = f"当前聊天对象为「{contact_name}」" if contact_name else "当前聊天对象未知"

    prompt = f"""你是一个专业的微信聊天界面结构化解析器。
以下是从微信主聊天区提取的文字项及气泡属性 (y越大越靠上，越靠前，时间顺序从上到下)。{who}。

{tagged_str}

【核心解析规则】：
1. 【对方消息 (incoming_text)】：
   - 必须展示【我方最新回复之后/下方】对方发送的所有信息！
   - 如果我方最近一次回复（绿色气泡）出现在屏幕上，则对方消息必须只包含【在我方该条回复下方】对方发送的所有内容，严禁包含我方回复之前的旧内容！
   - 如果当前屏幕上全是对面的消息（我方回复已滚出屏幕），则展示当前屏幕中对方发来的所有信息。
   - 已识别的图片以 "[图片: xxx]" 形式给出，请按真实从上到下的顺序与文字气泡换行拼接；若是截图被拆成大量零散碎字/数字，请概括为一行 "[图片: 简述]"，不要逐一输出碎片！
2. 【我方回复 (ego_text)】：
   - 展示对方最新消息之后我方的所有发言；若对方消息之后我方尚未回复，则填 "{NO_REPLY}"。
3. 【reply_status】：若对方最后一条消息之后我方已发言，为 "replied"；若对方消息之后我方尚未发言，为 "pending"。

请根据以上带标签的聊天流，输出严格的 JSON：
{{
  "incoming_text": "我最新回复下方、对方发来的所有信息汇总（多句严格按时间从上到下换行连接）",
  "ego_text": "对方最后消息之后我方的发言汇总，若未回复填'{NO_REPLY}'",
  "reply_status": "pending" 或 "replied",
  "dialogue_context": "最近按时间排序的对话记录文本流水"
}}
严禁输出任何额外说明或 Markdown 标签，仅输出纯合法 JSON。
"""

    try:
        raw = llm_client.chat_completion([{"role": "user", "content": prompt}], temperature=0.1, timeout=12)
    except Exception as e:
        logger.error("[LLM Parser Error] %s", e)
        return None
    parsed = llm_client.extract_json(raw)
    if not isinstance(parsed, dict):
        return None

    # 融合先验几何真值保护 (模型对已回复/待回复的判断不如像素几何可靠)
    gt_status, gt_ego = _ground_truth(elements)
    if gt_status == "pending":
        parsed["ego_text"] = NO_REPLY
        parsed["reply_status"] = "pending"
    else:
        ego_text = parsed.get("ego_text") or ""
        if not ego_text or ego_text == NO_REPLY or len(gt_ego.split("\n")) > len(ego_text.split("\n")):
            parsed["ego_text"] = gt_ego
        parsed["reply_status"] = "replied"
    return parsed
