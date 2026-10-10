from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from datetime import datetime

# 「我方在对方最新消息之后尚未发言」的统一占位文案 (UI 展示与各模块判断共用)
NO_REPLY = "暂未回复"

@dataclass
class ChatMessage:
    sender_name: str
    role: str                       # "me" | "target"
    content: str
    timestamp: datetime
    msg_type: str = "text"          # "text" | "system" | "image"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sender_name": self.sender_name,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "msg_type": self.msg_type
        }

@dataclass
class FactEpisode:
    episode_date: str
    theme: str
    entities: List[str]
    facts: List[str]
    relationship_dynamic: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "episode_date": self.episode_date,
            "theme": self.theme,
            "entities": self.entities,
            "facts": self.facts,
            "relationship_dynamic": self.relationship_dynamic
        }

@dataclass
class GenerationOption:
    slot_id: int                    # 1 ~ 4
    sub_goal: str                   # 本条打法标签，由模型按当轮对话现起 (如: "夸她手艺", "接火锅梗")
    reply_text: str
    tactical_rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "sub_goal": self.sub_goal,
            "reply_text": self.reply_text,
            "tactical_rationale": self.tactical_rationale
        }

@dataclass
class DualTrackResult:
    target_name: str
    incoming_context: str
    options: List[GenerationOption]
    # 本轮洞察 [{label, text}]，标签由模型按当轮情况现起 (如: {"label": "在晒手艺", "text": "想被夸，别挑刺"})
    insights: List[Dict[str, str]] = field(default_factory=list)
    risk_alert: str = ""                    # 避雷：本轮我方绝不能说/做的事 (每轮必出，防止说错话)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_name": self.target_name,
            "incoming_context": self.incoming_context,
            "insights": self.insights,
            "risk_alert": self.risk_alert,
            "options": [opt.to_dict() for opt in self.options],
            "timestamp": self.timestamp.isoformat()
        }

@dataclass
class ChatCaptureResult:
    contact_name: Optional[str] = None
    incoming_text: Optional[str] = None
    ego_text: Optional[str] = None
    reply_status: str = "pending"          # "replied" | "pending" | "mismatch"
    dialogue_context: str = ""
    is_mismatch: bool = False
    case_type: int = 2                     # 1: 情况1我回复了，2: 情况2待我回复
    raw_turns: List[Dict[str, Any]] = field(default_factory=list)
    time_hint: Optional[str] = None
    last_ego_text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contact_name": self.contact_name,
            "incoming_text": self.incoming_text,
            "ego_text": self.ego_text,
            "reply_status": self.reply_status,
            "dialogue_context": self.dialogue_context,
            "is_mismatch": self.is_mismatch,
            "case_type": self.case_type,
            "raw_turns": self.raw_turns,
            "time_hint": self.time_hint,
            "last_ego_text": self.last_ego_text
        }

