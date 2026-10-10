"""
联系人名称比对：防串台核心防线。
只接受「归一化后完全相同」的名字，宁可误拦也不误放
(OCR 偶发错字时会提示目标不符，用户重试即可；误放则会把别人的聊天写进当前联系人档案)。
"""
import re
from typing import Optional

# 群聊标题尾部的人数，如 "家人群(12)" / "家人群（12）"
_MEMBER_COUNT = re.compile(r"[（(]\d+[)）]$")


def normalize_contact_name(name: Optional[str]) -> str:
    n = re.sub(r"\s+", "", (name or "")).lower()
    return _MEMBER_COUNT.sub("", n)


def is_contact_match(detected: Optional[str], expected: Optional[str]) -> bool:
    d, e = normalize_contact_name(detected), normalize_contact_name(expected)
    return bool(d) and d == e
