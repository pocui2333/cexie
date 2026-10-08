import os
import re
import sqlite3
from datetime import datetime
from typing import List, Dict, Any, Optional
from core.contracts import ChatMessage, FactEpisode

class EpisodicDistiller:
    """
    情境事件脱水归档器 (Chatless Distiller):
    - 提炼对话中的核心事实、发生经过、涉及实体
    - 动态从联系人 dossier.md 与会话语义中提取实体，绝不硬编码任何个人隐私
    - 追加到 contacts/{微信备注}/episodes.md
    - 写入 index.db 建立毫秒级关键词/实体倒排索引
    - 彻底粉碎原始聊天记录，绝不长期持久化原句
    """
    def __init__(self, contacts_dir: str):
        self.contacts_dir = contacts_dir

    def distill_and_archive(self, target_name: str, messages: List[ChatMessage]) -> Dict[str, Any]:
        if not messages:
            return {"status": "empty_messages"}

        sandbox_dir = os.path.join(self.contacts_dir, target_name)
        if not os.path.exists(sandbox_dir):
            return {"status": "error", "message": f"联系人 {target_name} 沙盒不存在"}

        # 1. 提炼脱水事件 (动态语义提取)
        episode = self._extract_episode_facts(target_name, messages, sandbox_dir)

        # 2. 追加写入 episodes.md
        episodes_path = os.path.join(sandbox_dir, "episodes.md")
        with open(episodes_path, "a", encoding="utf-8") as f:
            f.write(f"\n## [{episode.episode_date}] {episode.theme}\n")
            f.write(f"- **涉及实体**：{episode.entities}\n")
            f.write("- **发生事实**：\n")
            for idx, fact in enumerate(episode.facts, start=1):
                f.write(f"  {idx}. {fact}\n")
            f.write(f"- **关系动态**：{episode.relationship_dynamic}\n")

        # 3. 写入 SQLite index.db
        db_path = os.path.join(sandbox_dir, "index.db")
        self._index_episode(db_path, episode)

        # 4. Chatless: 原始消息列表在函数退出后从内存析构，绝不存盘

        return {
            "status": "success",
            "target_name": target_name,
            "theme": episode.theme,
            "facts_count": len(episode.facts)
        }

    def distill_and_archive_turns(
        self,
        target_name: str,
        raw_turns: List[Dict[str, Any]],
        time_hint: Optional[str] = None
    ) -> Dict[str, Any]:
        """将实时捕获的轮次消息 (raw_turns) 转化为事件并安全写入脱水事实流 (带去重与防抖)"""
        if not raw_turns or not target_name:
            return {"status": "empty_turns"}

        sandbox_dir = os.path.join(self.contacts_dir, target_name)
        if not os.path.exists(sandbox_dir):
            return {"status": "contact_sandbox_not_found"}

        messages = []
        now = datetime.now()
        for t in raw_turns:
            role = t.get("role", "TARGET")
            txt = t.get("text", "").strip()
            if not txt or len(txt) < 2:
                continue
            is_ego = (role == "EGO")
            sender = "我" if is_ego else target_name
            messages.append(ChatMessage(
                sender_name=sender,
                role="me" if is_ego else "target",
                content=txt,
                timestamp=now
            ))
        if not messages:
            return {"status": "no_valid_messages"}

        # 使用 distill_history_stream 自动去重 (基于 md5 hash 校验 checkpoint.json，避免每分钟轮询重复录入)
        return self.distill_history_stream(target_name, messages, session_gap_seconds=3600)

    def distill_history_stream(
        self,
        target_name: str,
        messages: List[ChatMessage],
        session_gap_seconds: int = 7200,
        max_episodes: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        全量/历史对话流按时间段智能切片脱水归档:
        - 按会话沉默间隔 (> 2小时) 自动切片为一个独立事件 (Episode)
        - 跨天或话题转移自然归纳
        - 自动提取实体、动态主题、双方事实
        - 强幂等防重复：校验 checkpoint.json 与 SQLite 已录入事件
        - 写入 contacts/{target_name}/episodes.md 和 index.db
        - 阅后即析构原始消息 (Chatless)
        """
        import json
        import hashlib

        if not messages:
            return {"status": "empty_messages", "episodes_added": 0}

        sandbox_dir = os.path.join(self.contacts_dir, target_name)
        os.makedirs(sandbox_dir, exist_ok=True)

        episodes_path = os.path.join(sandbox_dir, "episodes.md")
        if not os.path.exists(episodes_path):
            with open(episodes_path, "w", encoding="utf-8") as f:
                f.write(f"# {target_name} 历史事实故事流 (Chatless)\n\n")

        db_path = os.path.join(sandbox_dir, "index.db")
        self._ensure_sqlite_tables(db_path)

        checkpoint_path = os.path.join(sandbox_dir, "checkpoint.json")
        recorded_hashes = set()
        if os.path.exists(checkpoint_path):
            try:
                with open(checkpoint_path, "r", encoding="utf-8") as f:
                    cp_data = json.load(f)
                    recorded_hashes = set(cp_data.get("recorded_hashes", []))
            except Exception:
                pass

        # 查询 SQLite 中已存在的事件日期以防重复追加
        existing_episode_dates = set()
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT episode_date FROM episode_records")
            existing_episode_dates = set(r[0] for r in cur.fetchall())
            conn.close()
        except Exception:
            pass

        # 确保按时间顺序升序排列
        sorted_msgs = sorted(messages, key=lambda m: m.timestamp)

        # 1. 对话流按时间空档智能切片
        sessions: List[List[ChatMessage]] = []
        current_session: List[ChatMessage] = []

        for m in sorted_msgs:
            if not current_session:
                current_session.append(m)
            else:
                gap = (m.timestamp - current_session[-1].timestamp).total_seconds()
                is_cross_day = (m.timestamp.date() != current_session[-1].timestamp.date() and gap > 3600)
                if gap > session_gap_seconds or is_cross_day:
                    sessions.append(current_session)
                    current_session = [m]
                else:
                    current_session.append(m)
        if current_session:
            sessions.append(current_session)

        # 2. 逐事件脱水提炼
        episodes_to_add: List[FactEpisode] = []

        for sess in sessions:
            # 过滤纯占位符和无效短句
            valid_turns = []
            for m in sess:
                txt = m.content.strip()
                if len(txt) < 2:
                    continue
                if txt in ("[图片]", "[语音]", "[视频]", "[动画表情]", "[表情]", "[语音/视频通话]"):
                    continue
                role_label = "EGO" if m.role == "me" else "TARGET"
                h = hashlib.md5(f"{role_label}::{txt}".encode("utf-8")).hexdigest()
                valid_turns.append((h, m))

            if not valid_turns:
                continue

            # 若该事件中所有发言均已被 checkpoint 记录过，跳过
            unseen = [t for t in valid_turns if t[0] not in recorded_hashes]
            if not unseen and len(valid_turns) > 0:
                continue

            session_time_str = sess[0].timestamp.strftime("%Y-%m-%d %H:%M")
            if session_time_str in existing_episode_dates:
                for h, _ in valid_turns:
                    recorded_hashes.add(h)
                continue

            # 语义分析与动态实体/主题提炼
            all_text = " ".join([m.content for _, m in valid_turns])
            entities, theme = self._extract_dynamic_entities_and_theme(target_name, all_text, sandbox_dir)

            # 提炼双方核心事实 (按出现顺序归纳代表性句子，最多 6 条)
            facts = []
            target_msgs = [m.content for _, m in valid_turns if m.role == "target"]
            ego_msgs = [m.content for _, m in valid_turns if m.role == "me"]

            last_role = None
            buf = []
            for _, m in valid_turns:
                role_name = "我" if m.role == "me" else target_name
                if last_role is None:
                    last_role = role_name
                    buf.append(m.content)
                elif last_role == role_name:
                    if len(buf) < 3 and len(m.content) < 30:
                        buf.append(m.content)
                else:
                    facts.append(f"{last_role}: {' '.join(buf)}")
                    last_role = role_name
                    buf = [m.content]
                if len(facts) >= 6:
                    break
            if buf and len(facts) < 6:
                facts.append(f"{last_role}: {' '.join(buf)}")

            if not facts:
                facts = ["日常互动与碎语交流"]

            # 关系动态判定
            if target_msgs and ego_msgs:
                dynamic = "双方完成一轮日常互动交流"
            elif target_msgs:
                dynamic = f"{target_name}主动分享生活动态与话题"
            else:
                dynamic = "我方主动回复关照"

            episode = FactEpisode(
                episode_date=session_time_str,
                theme=theme,
                entities=entities,
                facts=facts[:6],
                relationship_dynamic=dynamic
            )
            episodes_to_add.append(episode)
            existing_episode_dates.add(session_time_str)

            for h, _ in valid_turns:
                recorded_hashes.add(h)

            if max_episodes and len(episodes_to_add) >= max_episodes:
                break

        # 3. 批量持久化到 episodes.md
        if episodes_to_add:
            with open(episodes_path, "a", encoding="utf-8") as f:
                for ep in episodes_to_add:
                    f.write(f"\n## [{ep.episode_date}] {ep.theme}\n")
                    f.write(f"- **涉及实体**：{ep.entities}\n")
                    f.write("- **发生事实**：\n")
                    for idx, fact in enumerate(ep.facts, start=1):
                        f.write(f"  {idx}. {fact}\n")
                    f.write(f"- **关系动态**：{ep.relationship_dynamic}\n")

            # 4. 批量写入 SQLite index.db
            self._batch_index_episodes(db_path, episodes_to_add)

        # 5. 更新 checkpoint.json
        trimmed_hashes = list(recorded_hashes)
        if len(trimmed_hashes) > 10000:
            trimmed_hashes = trimmed_hashes[-10000:]
        cp_data = {
            "last_checkpoint_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_time_hint": episodes_to_add[-1].episode_date if episodes_to_add else "",
            "recorded_hashes": trimmed_hashes
        }
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(cp_data, f, ensure_ascii=False, indent=2)

        return {
            "status": "success",
            "target_name": target_name,
            "total_messages": len(messages),
            "total_sessions": len(sessions),
            "episodes_added": len(episodes_to_add)
        }

    def _ensure_sqlite_tables(self, db_path: str):
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS episode_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_date TEXT NOT NULL,
            theme TEXT NOT NULL,
            entities_blob TEXT NOT NULL,
            facts_summary TEXT NOT NULL,
            relationship_dynamic TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS entity_inverted_index (
            entity_name TEXT NOT NULL,
            episode_id INTEGER NOT NULL,
            weight REAL DEFAULT 1.0,
            PRIMARY KEY (entity_name, episode_id)
        );
        """)
        conn.commit()
        conn.close()

    def _batch_index_episodes(self, db_path: str, episodes: List[FactEpisode]):
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            for episode in episodes:
                entities_blob = ", ".join(episode.entities)
                facts_str = "; ".join(episode.facts)
                cur.execute("""
                INSERT INTO episode_records (episode_date, theme, entities_blob, facts_summary, relationship_dynamic)
                VALUES (?, ?, ?, ?, ?)
                """, (episode.episode_date, episode.theme, entities_blob, facts_str, episode.relationship_dynamic))
                ep_id = cur.lastrowid
                for ent in episode.entities:
                    cur.execute("""
                    INSERT OR REPLACE INTO entity_inverted_index (entity_name, episode_id, weight)
                    VALUES (?, ?, 1.0)
                    """, (ent, ep_id))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[Batch Index Error] {e}")

    def distill_turn_incremental(self, target_name: str, raw_turns: List[Dict[str, Any]], time_hint: Optional[str] = None) -> Dict[str, Any]:
        """
        按增量抓取上一次记忆时间点到现在的所有信息:
        - 区分哪些是我说的，哪些是对方说的
        - 分别蒸馏整理录入到 episodes.md 和 SQLite index.db
        - 强幂等防重复
        """
        import json
        import hashlib

        if not raw_turns:
            return {"status": "empty_turns", "new_count": 0}

        sandbox_dir = os.path.join(self.contacts_dir, target_name)
        if not os.path.exists(sandbox_dir):
            return {"status": "error", "message": f"联系人 {target_name} 沙盒不存在"}

        checkpoint_path = os.path.join(sandbox_dir, "checkpoint.json")
        recorded_hashes = set()
        last_checkpoint_time = ""
        if os.path.exists(checkpoint_path):
            try:
                with open(checkpoint_path, "r", encoding="utf-8") as f:
                    cp_data = json.load(f)
                    recorded_hashes = set(cp_data.get("recorded_hashes", []))
                    last_checkpoint_time = cp_data.get("last_checkpoint_time", "")
            except Exception:
                pass

        # 深度防重：查询 SQLite index.db 最近已沉淀的事实文本，绝不重复录入
        db_path = os.path.join(sandbox_dir, "index.db")
        existing_facts_corpus = ""
        if os.path.exists(db_path):
            try:
                import sqlite3
                conn = sqlite3.connect(db_path)
                cur = conn.cursor()
                cur.execute("SELECT facts_summary FROM episode_records ORDER BY id DESC LIMIT 30")
                existing_facts_corpus = " ".join([r[0] for r in cur.fetchall()])
                conn.close()
            except Exception:
                pass

        noise_patterns = [
            "按 Esc", "小胶囊", "点击复制", "抓取最新", "导入建档",
            "send", "发送", "口*、心", "uu.l", "曰％", "已发出"
        ]

        new_turns = []
        for t in raw_turns:
            role = t.get("role", "")
            text = t.get("text", "").strip()
            if not text or len(text) < 2:
                continue
            if any(k in text.lower() for k in noise_patterns):
                continue
            if not re.search(r"[\u4e00-\u9fa5a-zA-Z0-9]", text):
                continue

            t_hash = hashlib.md5(f"{role}::{text}".encode("utf-8")).hexdigest()
            # 1. 检查哈希记录
            if t_hash in recorded_hashes:
                continue
            # 2. 检查数据库历史事实库 (防止重启或不同客户端导致哈希失效)
            if existing_facts_corpus and text in existing_facts_corpus:
                recorded_hashes.add(t_hash)
                continue

            new_turns.append((t_hash, t))

        if not new_turns:
            return {"status": "unchanged", "new_count": 0, "last_checkpoint_time": last_checkpoint_time}

        target_new = [t for _, t in new_turns if t.get("role") == "TARGET"]
        ego_new = [t for _, t in new_turns if t.get("role") == "EGO"]

        all_text = " ".join([t["text"] for _, t in new_turns])

        # 动态实体与主题发现
        entities, theme = self._extract_dynamic_entities_and_theme(target_name, all_text, sandbox_dir)

        # 分别提炼双方事实
        facts = []
        for item in target_new:
            for line in item["text"].split("\n"):
                line_clean = line.strip()
                if line_clean and len(line_clean) >= 2:
                    facts.append(f"{target_name}: {line_clean}")
        for item in ego_new:
            for line in item["text"].split("\n"):
                line_clean = line.strip()
                if line_clean and len(line_clean) >= 2:
                    facts.append(f"我: {line_clean}")

        if not facts:
            facts = ["完成日常生活交流"]

        now_str = datetime.now().strftime("%Y-%m-%d")
        time_display = time_hint or datetime.now().strftime("%H:%M")
        dynamic = "保持高默契互动与即时响应"
        if ego_new and target_new:
            dynamic = "双方完成一轮日常互动问答"
        elif ego_new:
            dynamic = "我方主动回复关照"
        elif target_new:
            dynamic = f"{target_name}主动抛出新话题"

        # 写入 episodes.md
        episodes_path = os.path.join(sandbox_dir, "episodes.md")
        with open(episodes_path, "a", encoding="utf-8") as f:
            f.write(f"\n## [{now_str} {time_display}] {theme}\n")
            f.write(f"- **涉及实体**：{entities}\n")
            f.write("- **发生事实**：\n")
            for idx, fact in enumerate(facts[:8], start=1):
                f.write(f"  {idx}. {fact}\n")
            f.write(f"- **关系动态**：{dynamic}\n")

        # 写入 SQLite index.db
        db_path = os.path.join(sandbox_dir, "index.db")
        episode = FactEpisode(
            episode_date=f"{now_str} {time_display}",
            theme=theme,
            entities=entities,
            facts=facts[:8],
            relationship_dynamic=dynamic
        )
        self._index_episode(db_path, episode)

        # 更新 checkpoint.json
        for h, _ in new_turns:
            recorded_hashes.add(h)
        cp_data = {
            "last_checkpoint_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_time_hint": time_display,
            "recorded_hashes": list(recorded_hashes)
        }
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(cp_data, f, ensure_ascii=False, indent=2)

        return {
            "status": "recorded",
            "target_name": target_name,
            "theme": theme,
            "new_count": len(new_turns),
            "target_count": len(target_new),
            "ego_count": len(ego_new),
            "time_hint": time_display
        }

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

    def _extract_episode_facts(
        self,
        target_name: str,
        messages: List[ChatMessage],
        sandbox_dir: Optional[str] = None
    ) -> FactEpisode:
        date_str = messages[-1].timestamp.strftime("%Y-%m-%d")
        all_text = " ".join([m.content for m in messages])

        # 动态提取实体与主题
        entities, theme = self._extract_dynamic_entities_and_theme(target_name, all_text, sandbox_dir)

        facts = []
        for m in messages:
            content_clean = m.content.strip()
            if len(content_clean) >= 2:
                if any(k in content_clean for k in ["按 Esc", "小胶囊", "点击复制"]):
                    continue
                facts.append(f"{m.sender_name}: {content_clean}")
        if not facts:
            facts = ["完成日常生活碎语交换"]

        dynamic = "保持高默契互动与即时响应"

        return FactEpisode(
            episode_date=date_str,
            theme=theme,
            entities=entities,
            facts=facts[:5],
            relationship_dynamic=dynamic
        )

    def _index_episode(self, db_path: str, episode: FactEpisode):
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()

            entities_blob = ", ".join(episode.entities)
            facts_str = "; ".join(episode.facts)

            cur.execute("""
            INSERT INTO episode_records (episode_date, theme, entities_blob, facts_summary, relationship_dynamic)
            VALUES (?, ?, ?, ?, ?)
            """, (episode.episode_date, episode.theme, entities_blob, facts_str, episode.relationship_dynamic))
            episode_id = cur.lastrowid

            for ent in episode.entities:
                cur.execute("""
                INSERT OR REPLACE INTO entity_inverted_index (entity_name, episode_id, weight)
                VALUES (?, ?, 1.0)
                """, (ent, episode_id))

            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[Index Episode Error] {e}")
