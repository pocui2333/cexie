"""
Linguistic guardrails for conversational output.
Ensures zero AI stiffness, enforces pure comma-delimited phrasing, and removes punctuation / emojis.
"""
import re
from typing import Dict, Any

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
    for taboo in taboo_phrases:
        clean = clean.replace(taboo, "")

    # 2. 标点净化：严禁句号和感叹号，全转为逗号
    clean = clean.replace("。", "，").replace("！", "，").replace("!", "，").replace(".", "，")
    # 消除多重逗号
    clean = re.sub(r"，+", "，", clean)
    clean = clean.strip("，").strip()

    # 3. 严格剔除一切 emoji
    clean = re.sub(r"[\U00010000-\U0010ffff]", "", clean)

    # 4. 遵守联系人自定义禁用词
    for word in rules.get("taboo_words", []):
        clean = clean.replace(word, "")

    return clean
