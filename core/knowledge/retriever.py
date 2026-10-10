import os
import json
from typing import Dict, Any, Optional, List

class KnowledgeRetriever:
    """
    通用社交与情商情景微策略卡库检索器 (Micro-Playbooks Retriever)
    """
    def __init__(self, knowledge_dir: str):
        self.knowledge_dir = knowledge_dir
        self.playbooks: List[Dict[str, Any]] = []
        self._load_playbooks()

    def _load_playbooks(self):
        json_path = os.path.join(self.knowledge_dir, "playbooks.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    self.playbooks = json.load(f)
            except Exception as e:
                print(f"[KnowledgeRetriever Error] Failed to load playbooks.json: {e}")

    def retrieve_guidance(self, incoming_text: str) -> Optional[Dict[str, str]]:
        """
        根据待回复消息的语义倾向，从 31 张微策略卡中按触发词密度加权检索最契合的策略
        """
        if not incoming_text:
            return None

        clean_text = incoming_text.strip().lower()

        best_match = None
        best_score = 0

        for pb in self.playbooks:
            triggers = pb.get("triggers", [])
            matched_count = sum(1 for kw in triggers if kw.lower() in clean_text)
            if matched_count > best_score:
                best_score = matched_count
                best_match = pb

        if best_match:
            return {
                "source_doc": best_match.get("title", ""),
                "title": best_match.get("title", ""),
                "principle": best_match.get("principle", ""),
                "taboo": best_match.get("taboo", ""),
                "tactics": best_match.get("tactics", "")
            }

        # 默认匹配日常松弛沟通心法
        return {
            "source_doc": "场景松弛与体感校准推进",
            "title": "场景松弛与体感校准推进",
            "principle": "短句大白话同频畅聊，不刻意端着，顺着当前话题留出轻微话口，让交流自然流淌。",
            "taboo": "严禁越级推进关系，严禁对方客气当真爱、对方冷淡硬撩",
            "tactics": "识别对方温度信号，给予同频或微高于对方的热情反馈，保持进退自如的体面"
        }
