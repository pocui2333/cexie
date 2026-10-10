"""
Linguistic guardrails for conversational output.
Ensures zero AI stiffness, enforces pure comma-delimited phrasing, and removes punctuation / emojis.
"""
import re
from typing import Dict, Any

_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]")

def apply_linguistic_guardrails(text: str, rules: Dict[str, Any]) -> str:
    """
    过滤一切书面语、自媒体鸡汤腔与伪人心理咨询词，强制逗号与空格断句，严禁感叹号、句号和 emoji
    """
    clean = text.strip()

    # 1. 消除书面客套词与假模假样的鸡汤/心理分析词
    taboo_phrases = [
        "此外", "综上所述", "确实是这么回事", "辛苦了", "愿你", "加油",
        "作为你的朋友", "别给自己太大压力哈", "祝你", "谨记", "分析来看",
        "你心思挺细腻", "你挺懂生活", "你其实是个细腻的人", "理解你的感受", "希望一切顺利",
        "松弛感", "挺通透", "遵从本心", "心头舒坦", "大财主上线", "接纳自己", "千金难买心头好",
        "顺着你自己舒服的节奏来就行", "情绪价值"
    ]
    # 联系人 / 全局自定义禁用词 (rules.json 中 taboo_words 与 banned_phrases 均生效)
    taboo_phrases = taboo_phrases + list(rules.get("taboo_words", [])) + list(rules.get("banned_phrases", []))
    for taboo in taboo_phrases:
        if taboo:
            clean = clean.replace(taboo, "")

    # 2. 标点净化：严禁句号和感叹号，全转为逗号
    #    英文句点仅在不夹于字母数字之间时替换，保留 "3.5折"、网址等
    clean = clean.replace("。", "，").replace("！", "，").replace("!", "，")
    clean = re.sub(r"(?<![0-9A-Za-z])\.|\.(?![0-9A-Za-z])", "，", clean)

    # 3. 剔除 emoji (仅匹配 emoji 区段，避免误删生僻汉字等其他非 BMP 字符)
    clean = _EMOJI_RE.sub("", clean)

    # 4. 删除禁词后可能残留多重逗号 / 首尾逗号与空白
    clean = re.sub(r"\s*，[\s，]*", "，", clean)
    clean = clean.strip("，").strip()

    return clean
