import logging
import os
import re
import json
import hashlib
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from core import store
from core.contracts import ChatMessage, FactEpisode

logger = logging.getLogger(__name__)

# checkpoint.json 中保留的已沉淀消息指纹上限 (按写入顺序淘汰最旧的)
MAX_CHECKPOINT_HASHES = 20000

_NOISE_PATTERNS = [
    "按 esc", "小胶囊", "点击复制", "抓取最新", "导入建档",
    "send", "发送", "口*、心", "uu.l", "曰％", "已发出"
]
_PLACEHOLDER_MESSAGES = ("[图片]", "[语音]", "[视频]", "[动画表情]", "[表情]", "[语音/视频通话]")


def turn_hash(role: str, text: str) -> str:
    """单条发言指纹 (role 为 EGO / TARGET)，与历史 checkpoint.json 格式保持兼容"""
    return hashlib.md5(f"{role}::{text}".encode("utf-8")).hexdigest()


class EpisodicDistiller:
    """
    情境事件归档器:
    - 提炼对话中的核心事实、发生经过、涉及实体
    - 动态从联系人 dossier.md 与会话语义中提取实体，绝不硬编码任何个人隐私
    - 追加到 contacts/{微信备注}/episodes.md，并写入 index.db 建立实体倒排索引
    - 所有写入经由 store.write_lock 串行化，并以 checkpoint.json 指纹去重，保证幂等
    """
    def __init__(self, contacts_dir: str):
        self.contacts_dir = contacts_dir

    # ------------------------------------------------------------------ #
    # 实时抓取：增量沉淀
    # ------------------------------------------------------------------ #
    def record_turns(self, target_name: str, raw_turns: List[Dict[str, Any]], time_hint: Optional[str] = None) -> Dict[str, Any]:
        """
        将实时抓取到的轮次 (role=EGO/TARGET) 中尚未沉淀过的发言写入记忆:
        - 区分我方与对方发言，合并为一个事件
        - 指纹 + 已有事实双重去重，手动抓取 / 自动循环反复抓到同一屏也只记录一次
        """
        if not raw_turns:
            return {"status": "empty_turns", "new_count": 0}

        sandbox_dir = store.contact_dir(target_name, self.contacts_dir)
        if not os.path.isdir(sandbox_dir):
            return {"status": "error", "message": f"联系人 {target_name} 沙盒不存在"}

        with store.write_lock:
            recorded_hashes, last_checkpoint_time = self._load_checkpoint(sandbox_dir)
            recorded_set = set(recorded_hashes)
            existing_facts = self._recent_fact_texts(target_name)

            new_turns: List[Tuple[str, Dict[str, Any]]] = []
            for t in raw_turns:
                role = t.get("role", "")
                text = (t.get("text") or "").strip()
                if role not in ("EGO", "TARGET") or len(text) < 2:
                    continue
                if any(k in text.lower() for k in _NOISE_PATTERNS):
                    continue
                if not re.search(r"[\u4e00-\u9fa5a-zA-Z0-9]", text):
                    continue
                h = turn_hash(role, text)
                if h in recorded_set:
                    continue
                # 指纹丢失 (如 checkpoint 被截断) 时，以已沉淀事实逐句精确比对兜底
                if all(line.strip() in existing_facts for line in text.split("\n") if line.strip()):
                    recorded_hashes.append(h)
                    recorded_set.add(h)
                    continue
                new_turns.append((h, t))
                recorded_set.add(h)

            if not new_turns:
                self._save_checkpoint(sandbox_dir, recorded_hashes, None)
                return {"status": "unchanged", "new_count": 0, "last_checkpoint_time": last_checkpoint_time}

            target_new = [t for _, t in new_turns if t["role"] == "TARGET"]
            ego_new = [t for _, t in new_turns if t["role"] == "EGO"]
            all_text = " ".join(t["text"] for _, t in new_turns)
            entities, theme = self._extract_dynamic_entities_and_theme(target_name, all_text, sandbox_dir)

            # 按真实先后顺序记录双方事实
            facts = []
            for _, t in new_turns:
                speaker = "我" if t["role"] == "EGO" else target_name
                facts.extend(f"{speaker}: {line.strip()}" for line in t["text"].split("\n") if len(line.strip()) >= 2)
            if not facts:
                facts = ["完成日常生活交流"]

            if ego_new and target_new:
                dynamic = "双方完成一轮日常互动问答"
            elif ego_new:
                dynamic = "我方主动回复关照"
            else:
                dynamic = f"{target_name}主动抛出新话题"

            time_display = time_hint or datetime.now().strftime("%H:%M")
            episode = FactEpisode(
                episode_date=f"{datetime.now():%Y-%m-%d} {time_display}",
                theme=theme,
                entities=entities,
                facts=facts[:8],
                relationship_dynamic=dynamic
            )
            self._persist_episodes(target_name, sandbox_dir, [episode])
            recorded_hashes.extend(h for h, _ in new_turns)
            self._save_checkpoint(sandbox_dir, recorded_hashes, time_display)

        return {
            "status": "recorded",
            "target_name": target_name,
            "theme": theme,
            "new_count": len(new_turns),
            "target_count": len(target_new),
            "ego_count": len(ego_new),
            "time_hint": time_display
        }

    # ------------------------------------------------------------------ #
    # 历史导入：按会话切片批量沉淀
    # ------------------------------------------------------------------ #
    def distill_history_stream(
        self,
        target_name: str,
        messages: List[ChatMessage],
        session_gap_seconds: int = 7200,
        max_episodes: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        全量/历史对话流按时间段智能切片归档:
        - 按会话沉默间隔 (> 2小时) 或跨天自动切片为独立事件 (Episode)
        - 只对尚未沉淀过的发言 (checkpoint 指纹) 生成事实，重复导入不会重复写入
        """
        if not messages:
            return {"status": "empty_messages", "episodes_added": 0}

        sandbox_dir = store.contact_dir(target_name, self.contacts_dir)
        os.makedirs(sandbox_dir, exist_ok=True)

        with store.write_lock:
            recorded_hashes, _ = self._load_checkpoint(sandbox_dir)
            recorded_set = set(recorded_hashes)

            # 1. 对话流按时间空档智能切片
            sessions: List[List[ChatMessage]] = []
            for m in sorted(messages, key=lambda m: m.timestamp):
                if sessions:
                    prev = sessions[-1][-1]
                    gap = (m.timestamp - prev.timestamp).total_seconds()
                    is_cross_day = m.timestamp.date() != prev.timestamp.date() and gap > 3600
                    if gap <= session_gap_seconds and not is_cross_day:
                        sessions[-1].append(m)
                        continue
                sessions.append([m])

            # 2. 逐事件提炼 (仅使用未沉淀过的发言)
            episodes_to_add: List[FactEpisode] = []
            new_hashes: List[str] = []
            for sess in sessions:
                fresh: List[ChatMessage] = []
                for m in sess:
                    txt = m.content.strip()
                    if len(txt) < 2 or txt in _PLACEHOLDER_MESSAGES:
                        continue
                    h = turn_hash("EGO" if m.role == "me" else "TARGET", txt)
                    if h in recorded_set:
                        continue
                    recorded_set.add(h)
                    new_hashes.append(h)
                    fresh.append(m)
                if not fresh:
                    continue

                all_text = " ".join(m.content for m in fresh)
                entities, theme = self._extract_dynamic_entities_and_theme(target_name, all_text, sandbox_dir)

                # 提炼双方核心事实 (同一人连续短句合并，最多 6 条)
                facts: List[str] = []
                last_role, buf = None, []
                for m in fresh:
                    role_name = "我" if m.role == "me" else target_name
                    if role_name == last_role:
                        if len(buf) < 3 and len(m.content) < 30:
                            buf.append(m.content)
                        continue
                    if last_role is not None:
                        facts.append(f"{last_role}: {' '.join(buf)}")
                        if len(facts) >= 6:
                            buf = []
                            break
                    last_role, buf = role_name, [m.content]
                if buf and len(facts) < 6:
                    facts.append(f"{last_role}: {' '.join(buf)}")

                has_target = any(m.role != "me" for m in fresh)
                has_ego = any(m.role == "me" for m in fresh)
                if has_target and has_ego:
                    dynamic = "双方完成一轮日常互动交流"
                elif has_target:
                    dynamic = f"{target_name}主动分享生活动态与话题"
                else:
                    dynamic = "我方主动回复关照"

                episodes_to_add.append(FactEpisode(
                    episode_date=fresh[0].timestamp.strftime("%Y-%m-%d %H:%M"),
                    theme=theme,
                    entities=entities,
                    facts=facts or ["日常互动与碎语交流"],
                    relationship_dynamic=dynamic
                ))
                if max_episodes and len(episodes_to_add) >= max_episodes:
                    break

            if episodes_to_add:
                self._persist_episodes(target_name, sandbox_dir, episodes_to_add)
            recorded_hashes.extend(new_hashes)
            self._save_checkpoint(sandbox_dir, recorded_hashes, episodes_to_add[-1].episode_date if episodes_to_add else None)

        return {
            "status": "success",
            "target_name": target_name,
            "total_messages": len(messages),
            "total_sessions": len(sessions),
            "episodes_added": len(episodes_to_add)
        }

    # ------------------------------------------------------------------ #
    # 持久化与 checkpoint
    # ------------------------------------------------------------------ #
    def _persist_episodes(self, target_name: str, sandbox_dir: str, episodes: List[FactEpisode]) -> None:
        """追加写入 episodes.md 并同步建立 index.db 倒排索引 (调用方需持有 write_lock)"""
        episodes_path = os.path.join(sandbox_dir, "episodes.md")
        is_new = not os.path.exists(episodes_path)
        with open(episodes_path, "a", encoding="utf-8") as f:
            if is_new:
                f.write(f"# {target_name} 历史事实故事流\n\n")
            for ep in episodes:
                f.write(f"\n## [{ep.episode_date}] {ep.theme}\n")
                f.write(f"- **涉及实体**：{ep.entities}\n")
                f.write("- **发生事实**：\n")
                for idx, fact in enumerate(ep.facts, start=1):
                    f.write(f"  {idx}. {fact}\n")
                f.write(f"- **关系动态**：{ep.relationship_dynamic}\n")

        with store.connect(target_name, self.contacts_dir, create=True) as conn:
            for ep in episodes:
                cur = conn.execute("""
                    INSERT INTO episode_records (episode_date, theme, entities_blob, facts_summary, relationship_dynamic)
                    VALUES (?, ?, ?, ?, ?)
                """, (ep.episode_date, ep.theme, ", ".join(ep.entities), "; ".join(ep.facts), ep.relationship_dynamic))
                conn.executemany("""
                    INSERT OR REPLACE INTO entity_inverted_index (entity_name, episode_id, weight)
                    VALUES (?, ?, 1.0)
                """, [(ent, cur.lastrowid) for ent in ep.entities])

    def _recent_fact_texts(self, target_name: str, limit: int = 30) -> set:
        """最近若干事件中的事实正文 (去掉 "说话人: " 前缀)，用于指纹缺失时的精确去重"""
        texts = set()
        try:
            with store.connect(target_name, self.contacts_dir) as conn:
                if conn is None:
                    return texts
                for (summary,) in conn.execute(
                    "SELECT facts_summary FROM episode_records ORDER BY id DESC LIMIT ?", (limit,)
                ):
                    for part in summary.split("; "):
                        texts.add(part.split(": ", 1)[-1].strip())
        except Exception as e:
            logger.error("[Recent Facts Error] %s", e)
        return texts

    @staticmethod
    def _load_checkpoint(sandbox_dir: str) -> Tuple[List[str], str]:
        path = os.path.join(sandbox_dir, "checkpoint.json")
        if not os.path.exists(path):
            return [], ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return list(data.get("recorded_hashes", [])), data.get("last_checkpoint_time", "")
        except Exception as e:
            logger.warning("[Checkpoint Load Warning] %s", e)
            return [], ""

    @staticmethod
    def _save_checkpoint(sandbox_dir: str, recorded_hashes: List[str], last_time_hint: Optional[str]) -> None:
        """按写入顺序只保留最新的指纹；先写临时文件再原子替换，避免中途崩溃损坏 checkpoint"""
        path = os.path.join(sandbox_dir, "checkpoint.json")
        data = {
            "last_checkpoint_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_time_hint": last_time_hint or "",
            "recorded_hashes": list(dict.fromkeys(recorded_hashes))[-MAX_CHECKPOINT_HASHES:]
        }
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)

    # ------------------------------------------------------------------ #
    # 实体与主题提炼
    # ------------------------------------------------------------------ #
    def _extract_dynamic_entities_and_theme(
        self,
        target_name: str,
        all_text: str,
        sandbox_dir: Optional[str] = None
    ) -> (List[str], str):
        entities = [target_name]

        # 1. 动态从联系人自身 dossier.md 中解析已知实体 (如有)
        if sandbox_dir and os.path.exists(sandbox_dir):
            dossier_path = os.path.join(sandbox_dir, "dossier.md")
            if os.path.exists(dossier_path):
                try:
                    with open(dossier_path, "r", encoding="utf-8") as f:
                        d_text = f.read()
                    # 匹配已知实体列表 known_entities: ["老李", "小刘"]
                    m_list = re.search(r'known_entities:\s*\[(.*?)\]', d_text)
                    if m_list:
                        items = [x.strip().strip('"').strip("'") for x in m_list.group(1).split(",") if x.strip()]
                        for it in items:
                            if it in all_text and it not in entities:
                                entities.append(it)
                    # 匹配加粗的人物实体条目 - **小刘**：...
                    bold_items = re.findall(r'-\s*\*\*([^*]+)\*\*', d_text)
                    for it in bold_items:
                        it = it.strip()
                        if 1 < len(it) <= 8 and it in all_text and it not in entities:
                            entities.append(it)
                except Exception:
                    pass

        # 2. 动态发现称谓与社交实体 (如 老李、小王、张总、李姐、室友、同事、领导、老板等)
        surnames = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐费岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅齐康伍余元顾孟平黄穆萧姚邵汪毛成戴宋庞熊董梁杜江童颜郭林徐高夏蔡田胡凌万卢莫房丁邓单洪包诸左石崔吉龚刘陆叶关程沈潘"
        title_pattern = rf"(?:[老小大二三][{surnames}]|[{surnames}](?:哥|姐|总|叔|姨|主管|经理|主任|老师|老板)|(?:室友|同事|领导|老板|领队|同学))"
        title_matches = re.findall(title_pattern, all_text)
        for m in title_matches:
            if m not in entities and len(m) >= 2:
                entities.append(m)

        # 3. 通用生活事件主题词
        common_topic_words = [
            "工作", "加班", "项目", "开会", "周末", "假期", "旅行", "出差",
            "聚餐", "火锅", "烧烤", "外卖", "买衣服", "电影", "健身", "游戏",
            "降温", "天气", "休息", "睡觉", "搬家", "快递"
        ]
        for w in common_topic_words:
            if w in all_text and w not in entities:
                entities.append(w)

        # 4. 动态分类主题
        theme = "日常互动与生活交流"
        if any(k in all_text for k in ["加班", "上班", "开会", "工位", "打工", "项目", "活儿"]):
            theme = "职场工作进展与日常吐槽"
        elif any(k in all_text for k in ["吃", "火锅", "烧烤", "奶茶", "外卖", "大餐", "馆子"]):
            theme = "美食餐饮分享与聚餐讨论"
        elif any(k in all_text for k in ["买衣服", "试衣服", "穿搭", "挑衣服", "审美", "风格"]):
            theme = "生活选品与穿搭审美交流"
        elif any(k in all_text for k in ["坐车", "赶车", "高铁", "飞机", "旅行", "返程", "到家", "车"]):
            theme = "出行动态与返程休整"
        elif any(k in all_text for k in ["周末", "放假", "休息", "补觉", "躺平"]):
            theme = "周末假期休整与生活安排"
        elif any(k in all_text for k in ["电视剧", "追剧", "电影", "游戏", "通关"]):
            theme = "文娱追剧与休闲兴趣分享"
        elif any(k in all_text for k in ["发工资", "犒劳", "破费", "购物", "买东西", "消费"]):
            theme = "生活消费与犒劳分享"
        elif any(k in all_text for k in ["气死", "离谱", "无语", "糟心", "烦"]):
            theme = "心情倾诉与老友解压"
        elif any(k in all_text for k in ["想当年", "以前", "那会儿", "翻篇"]):
            theme = "往事回顾与豁达畅谈"
        elif any(k in all_text for k in ["变天", "降温", "冷", "热", "下雨"]):
            theme = "天气变化与日常关切"

        return entities, theme
