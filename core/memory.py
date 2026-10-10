import logging
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from core import store
from core.contracts import NO_REPLY

logger = logging.getLogger(__name__)


def _episode_row(row) -> Dict[str, Any]:
    return {"id": row[0], "date": row[1], "theme": row[2], "facts": row[3], "dynamic": row[4]}

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
        try:
            with store.connect(target_name, self.contacts_dir) as conn:
                if conn is None:
                    return []
                known_entities = [r[0] for r in conn.execute("SELECT DISTINCT entity_name FROM entity_inverted_index")]

                # 综合当前消息与多轮上下文联合匹配实体 (杜绝单句孤立搜索导致丢失关键背景)
                search_corpus = f"{incoming_text} {context_text or ''}".strip()
                hits = [ent for ent in known_entities if ent and ent in search_corpus]

                if hits:
                    placeholders = ",".join(["?"] * len(hits))
                    rows = conn.execute(f"""
                        SELECT r.id, r.episode_date, r.theme, r.facts_summary, r.relationship_dynamic
                        FROM episode_records r
                        JOIN entity_inverted_index i ON r.id = i.episode_id
                        WHERE i.entity_name IN ({placeholders})
                        GROUP BY r.id
                        ORDER BY r.episode_date DESC
                        LIMIT 3
                    """, hits).fetchall()
                else:
                    # 默认提取最近的一条事件作为背景
                    rows = conn.execute("""
                        SELECT id, episode_date, theme, facts_summary, relationship_dynamic
                        FROM episode_records ORDER BY episode_date DESC LIMIT 1
                    """).fetchall()
                return [_episode_row(r) for r in rows]
        except Exception as e:
            logger.error("[Memory Retrieve Error] %s", e)
            return []

    def get_today_working_memory(self, target_name: str, limit: int = 8) -> List[Dict[str, Any]]:
        """
        提取今日进行时工作记忆 (Today's Working Memory):
        - 强制常驻，不走概率性的 RAG 实体关键词检索
        - 从 index.db 中抽取当天与昨天双方发生的事实事件流，按时间升序还原故事线
        """
        today_prefix = datetime.now().strftime("%Y-%m-%d")
        yesterday_prefix = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            with store.connect(target_name, self.contacts_dir) as conn:
                if conn is None:
                    return []
                rows = conn.execute("""
                    SELECT id, episode_date, theme, facts_summary, relationship_dynamic
                    FROM episode_records
                    WHERE episode_date LIKE ? OR episode_date LIKE ?
                    ORDER BY episode_date ASC
                    LIMIT ?
                """, (f"{today_prefix}%", f"{yesterday_prefix}%", limit)).fetchall()
                return [_episode_row(r) for r in rows]
        except Exception as e:
            logger.error("[Today Memory Error] %s", e)
            return []

    def get_today_fact_lines(self, target_name: str) -> List[str]:
        """今日全部事实条目 (facts_summary 按 ; 与换行拆分)，供今日互动统计使用"""
        today_prefix = datetime.now().strftime("%Y-%m-%d")
        try:
            with store.connect(target_name, self.contacts_dir) as conn:
                if conn is None:
                    return []
                rows = conn.execute(
                    "SELECT facts_summary FROM episode_records WHERE episode_date LIKE ?", (f"{today_prefix}%",)
                ).fetchall()
        except Exception as e:
            logger.error("[Today Facts Error] %s", e)
            return []
        lines = []
        for (summary,) in rows:
            lines.extend(p.strip() for p in re.split(r"[;\n]", summary) if p.strip())
        return lines

    def get_recent_ego_utterances(self, target_name: str, limit: int = 8) -> List[str]:
        """动态提取我方对该好友在历史事实记录中的真实发言原句 (Few-Shot 真实说话风格基准)"""
        results: List[str] = []
        try:
            with store.connect(target_name, self.contacts_dir) as conn:
                if conn is None:
                    return []
                rows = conn.execute("""
                    SELECT facts_summary FROM episode_records
                    WHERE facts_summary LIKE '%我:%'
                    ORDER BY id DESC LIMIT 50
                """).fetchall()
        except Exception as e:
            logger.error("[Ego Utterances Error] %s", e)
            return []
        for (summary,) in rows:
            for m in re.findall(r"我:\s*([^;。\n]+)", summary):
                cleaned = m.strip()
                if cleaned and cleaned not in results and 2 <= len(cleaned) <= 60 and NO_REPLY not in cleaned:
                    results.append(cleaned)
                    if len(results) >= limit:
                        return results
        return results

    def retrieve_qa_scene_snippets(
        self,
        target_name: str,
        incoming_text: str,
        limit: int = 3
    ) -> List[Dict[str, str]]:
        """
        问答场景切片检索 (Conversational Q-A Snippet Retrieval):
        - 针对对方发来的问题或话题，检索历史记录中对方曾提出的类似问题/发言;
        - 精准提取当时紧随其后【我方的真实应答切片】 (TA说 -> 我答);
        - 组装为多轮问答对话切片作为 Few-Shot 样本，使 AI 拥有我方对该话题的真实回答基准。
        """
        clean_in = re.sub(r"[，。！？\s\n]+", " ", incoming_text).strip()
        keywords = [w for w in re.findall(r"[\u4e00-\u9fa5]{2,6}", clean_in) if w not in ["这个", "那个", "怎么", "什么", "觉得", "感觉", "这样", "那样"]]

        matched_summaries: List[str] = []
        try:
            with store.connect(target_name, self.contacts_dir) as conn:
                if conn is None:
                    return []
                for kw in keywords[:4]:
                    for (summary,) in conn.execute(
                        "SELECT facts_summary FROM episode_records WHERE facts_summary LIKE ? ORDER BY id DESC LIMIT 5",
                        (f"%{kw}%",)
                    ):
                        if summary not in matched_summaries:
                            matched_summaries.append(summary)
                if not matched_summaries:
                    matched_summaries = [r[0] for r in conn.execute(
                        "SELECT facts_summary FROM episode_records ORDER BY id DESC LIMIT 5"
                    )]
        except Exception as e:
            logger.error("[QA Snippet Retrieval Error] %s", e)
            return []

        # 从 facts_summary 中解包连贯的 [TA说 -> 我答] 场景切片
        snippets: List[Dict[str, str]] = []
        for summary in matched_summaries:
            lines = [l.strip() for l in re.split(r"[;\n]", summary) if l.strip()]
            for curr_line, next_line in zip(lines, lines[1:]):
                is_target = curr_line.startswith((f"{target_name}:", "TA:", "对方:"))
                is_ego = next_line.startswith(("我:", "我方:"))
                if not (is_target and is_ego):
                    continue
                target_msg = re.sub(r"^[^:]+:\s*", "", curr_line).strip()
                ego_msg = re.sub(r"^[^:]+:\s*", "", next_line).strip()
                pair = {"target_said": target_msg, "ego_replied": ego_msg}
                if len(target_msg) >= 2 and len(ego_msg) >= 2 and NO_REPLY not in ego_msg and pair not in snippets:
                    snippets.append(pair)
                    if len(snippets) >= limit:
                        return snippets
        return snippets
