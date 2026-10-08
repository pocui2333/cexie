import os
import sqlite3
import re
from typing import List, Dict, Any, Optional

class EntityMemoryRetriever:
    """
    实体关联记忆检索器:
    - 针对特定联系人沙盒下的 index.db
    - 从最新发言中提取实体标签
    - 毫秒级唤醒该联系人对应的脱水历史事实
    """
    def __init__(self, contacts_dir: str):
        self.contacts_dir = contacts_dir

    def retrieve_memory(self, target_name: str, incoming_text: str, context_text: Optional[str] = None) -> List[Dict[str, Any]]:
        sandbox_dir = os.path.join(self.contacts_dir, target_name)
        db_path = os.path.join(sandbox_dir, "index.db")
        if not os.path.exists(db_path):
            return []

        matched_episodes = []
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()

            # 查出所有已建索引的实体词
            cur.execute("SELECT DISTINCT entity_name FROM entity_inverted_index")
            known_entities = [row[0] for row in cur.fetchall()]

            # 综合当前消息与多轮上下文联合匹配实体 (杜绝单句孤立搜索导致丢失关键背景)
            search_corpus = f"{incoming_text} {context_text or ''}".strip()
            hits = [ent for ent in known_entities if ent in search_corpus]

            if hits:
                placeholders = ",".join(["?"] * len(hits))
                query = f"""
                SELECT r.id, r.episode_date, r.theme, r.facts_summary, r.relationship_dynamic
                FROM episode_records r
                JOIN entity_inverted_index i ON r.id = i.episode_id
                WHERE i.entity_name IN ({placeholders})
                GROUP BY r.id
                ORDER BY r.episode_date DESC
                LIMIT 3
                """
                cur.execute(query, hits)
                for row in cur.fetchall():
                    matched_episodes.append({
                        "id": row[0],
                        "date": row[1],
                        "theme": row[2],
                        "facts": row[3],
                        "dynamic": row[4]
                    })
            else:
                # 默认提取最近的一条事件作为背景
                cur.execute("""
                SELECT id, episode_date, theme, facts_summary, relationship_dynamic
                FROM episode_records
                ORDER BY episode_date DESC
                LIMIT 1
                """)
                row = cur.fetchone()
                if row:
                    matched_episodes.append({
                        "id": row[0],
                        "date": row[1],
                        "theme": row[2],
                        "facts": row[3],
                        "dynamic": row[4]
                    })
            conn.close()
        except Exception:
            pass

        return matched_episodes

    def load_dossier_summary(self, target_name: str) -> str:
        dossier_path = os.path.join(self.contacts_dir, target_name, "dossier.md")
        if os.path.exists(dossier_path):
            with open(dossier_path, "r", encoding="utf-8") as f:
                content = f.read()
                # 截取前 800 字作为关键人设画像
                return content[:800]
        return ""

    def get_recent_ego_utterances(self, target_name: str, limit: int = 8) -> List[str]:
        """动态提取我方对该好友在历史事实记录中的真实发言原句 (Few-Shot 真实说话风格基准)"""
        sandbox_dir = os.path.join(self.contacts_dir, target_name)
        db_path = os.path.join(sandbox_dir, "index.db")
        if not os.path.exists(db_path):
            return []
        results = []
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("""
                SELECT facts_summary FROM episode_records 
                WHERE facts_summary LIKE '%我:%' 
                ORDER BY id DESC LIMIT 50
            """)
            for row in cur.fetchall():
                matches = re.findall(r'我:\s*([^;。\n]+)', row[0])
                for m in matches:
                    cleaned = m.strip()
                    if cleaned and cleaned not in results and 2 <= len(cleaned) <= 60 and "暂未回复" not in cleaned:
                        results.append(cleaned)
                        if len(results) >= limit:
                            break
                if len(results) >= limit:
                    break
            conn.close()
        except Exception:
            pass
        return results

