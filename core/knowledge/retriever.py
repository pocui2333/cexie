"""
Knowledge Retriever:
Dynamically matches incoming dialogue intent against the universal communication
knowledge base (boundary, dynamic, emotional, tactics, psychology) to supply
actionable, high-EQ social strategies without hardcoded assumptions or dogma.
"""
import os
import re
from typing import Dict, Any, Optional, List

class KnowledgeRetriever:
    """
    通用社交与情商知识库检索器
    """
    def __init__(self, knowledge_dir: str):
        self.knowledge_dir = knowledge_dir
        self._strategy_rules = [
            {
                "keywords": ["烦", "累", "骂", "委屈", "难受", "崩溃", "伤心", "倒霉", "不爽", "无语", "气死", "焦虑", "失眠", "郁闷", "加班", "头疼", "生病"],
                "doc": "为他人提供情绪价值：温暖且有效的回应指南.md",
                "title": "情绪共情与无条件偏袒撑腰",
                "principle": "必须先接住情绪，无条件站在对方立场共情撑腰；绝对严禁客观纠错、长辈式说教或理中客分析！"
            },
            {
                "keywords": ["好看", "漂亮", "新买", "新做", "自拍", "穿搭", "发型", "指甲", "首饰", "口红", "试了", "看我", "做好了", "蛋糕", "手艺", "画的"],
                "doc": "万能夸人的话术技巧：真诚认可的实用指南.md",
                "title": "细节看见与品味赞许",
                "principle": "夸具体细节与审美眼光，不假大空；顺着对方的小得意肯定其品味，给足被真诚欣赏与被重视的正向反馈！"
            },
            {
                "keywords": ["哈哈", "逗", "损", "笑死", "调皮", "坏", "扯", "算了吧", "才不", "才怪", "找打"],
                "doc": "幽默接梗与曲解调侃：打破冷场的高情商指南.md",
                "title": "幽默接梗与善意曲解",
                "principle": "善意曲解、反差自嘲或角色互换；把严肃的事情变轻快，平视捧哏，严禁油腻套路或攻击性冷嘲热讽！"
            },
            {
                "keywords": ["去哪", "吃啥", "周末", "放假", "店", "好吃", "想吃", "逛街", "好玩", "电影", "展览", "咖啡", "打卡", "推荐"],
                "doc": "线上微信聊天的节奏把控与话题延伸指南.md",
                "title": "种草埋点与低压力模糊邀约",
                "principle": "顺着事物本身随性畅聊体验与口感，故意留话口；时机适宜时自然抛出低压力共同体验或陪伴意愿！"
            },
            {
                "keywords": ["尴尬", "手滑", "发错", "卡住", "撤回", "忘回", "不好意思", "抱歉", "没看到"],
                "doc": "化解尴尬：轻松救场的实用指南.md",
                "title": "自嘲化解与顺水推舟",
                "principle": "大方自嘲或幽默打趣卸掉严肃感，给足对方面子和台阶，不较真不追问，让气氛立刻回暖松弛。"
            },
            {
                "keywords": ["在吗", "在干嘛", "忙吗", "睡了没", "吃饭了吗", "今天怎么样"],
                "doc": "聊天化被动为主动：引导互动的实用指南.md",
                "title": "状态陈述+细节共鸣",
                "principle": "避免枯燥单字应答或查户口式回问，用真实的生活片段+轻度好奇作为接球点，激发后续双向分享欲。"
            },
            {
                "keywords": ["不想", "拒绝", "不太想", "算了吧", "改天吧", "压力大", "别问了"],
                "doc": "高情商拒绝他人：体面护边界的实用指南.md",
                "title": "体面护界与情绪包容",
                "principle": "尊重对方当下边界，给予充分安全感与自由度，不纠缠不道德绑架，保持体面与从容。"
            }
        ]

    def retrieve_guidance(self, incoming_text: str) -> Optional[Dict[str, str]]:
        """
        根据待回复消息的语义倾向，检索知识库中最契合的高情商沟通策略
        """
        if not incoming_text:
            return None

        clean_text = incoming_text.strip().lower()
        for rule in self._strategy_rules:
            if any(k in clean_text for k in rule["keywords"]):
                return {
                    "source_doc": rule["doc"],
                    "title": rule["title"],
                    "principle": rule["principle"]
                }

        # 默认匹配日常松弛沟通心法
        return {
            "source_doc": "场景感、松弛感与社交校准：从接话到关系推进.md",
            "title": "场景松弛与平视互动",
            "principle": "短句大白话同频畅聊，不刻意端着，顺着当前话题留出轻微话口，让交流自然流淌。"
        }
