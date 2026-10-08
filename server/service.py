"""
EchoLens Service Layer:
Coordinates core state machine, memory, dual-track generator, and background workers.
"""
import os
import time
import threading
import subprocess
from typing import Optional, List, Dict, Any
import config
from core.state_machine import SessionStateMachine
from core.memory import EntityMemoryRetriever
from core.generator import DualTrackGenerator
from ingestion.contact_profiler import ContactProfiler
from ingestion.episodic_distiller import EpisodicDistiller
from capture import capture_chat_snapshot

def get_macos_clipboard() -> str:
    """使用 macOS 原生 pbpaste 读取剪贴板"""
    try:
        res = subprocess.check_output(['pbpaste'], text=True, stderr=subprocess.DEVNULL)
        return res.strip()
    except Exception:
        return ""

def get_default_target() -> str:
    """动态获取默认联系人 (优先历史记忆最丰富/最活跃真实联系人，兜底示例好友)"""
    if os.path.exists(config.CONTACTS_DIR):
        dirs = [
            d for d in os.listdir(config.CONTACTS_DIR)
            if os.path.isdir(os.path.join(config.CONTACTS_DIR, d)) and not d.startswith('.')
        ]
        user_contacts = [d for d in dirs if d != "示例好友"]
        if user_contacts:
            def _get_episode_count(name):
                import sqlite3
                db_path = os.path.join(config.CONTACTS_DIR, name, "index.db")
                if os.path.exists(db_path):
                    try:
                        conn = sqlite3.connect(db_path)
                        cur = conn.cursor()
                        cur.execute("SELECT COUNT(*) FROM episode_records")
                        cnt = cur.fetchone()[0]
                        conn.close()
                        return cnt
                    except Exception:
                        pass
                return 0
            user_contacts.sort(key=_get_episode_count, reverse=True)
            return user_contacts[0]
        if "示例好友" in dirs:
            return "示例好友"
        if dirs:
            return dirs[0]
    return "示例好友"

class EchoLensService:
    def __init__(self):
        self.memory = EntityMemoryRetriever(config.CONTACTS_DIR)
        self.generator = DualTrackGenerator(config.EGO_DIR, config.CONTACTS_DIR, config.KNOWLEDGE_DIR)
        self.profiler = ContactProfiler(config.CONTACTS_DIR)
        self.distiller = EpisodicDistiller(config.CONTACTS_DIR)

        self.last_clipboard_seen = ""
        self.last_outgoing_reply = ""
        self.cached_options: List[Dict[str, Any]] = []
        self.manual_target_locked = False
        self.current_ego_reply = "暂未回复"
        self.current_reply_status = "pending"
        self.current_context = ""
        self.current_incoming = ""
        self.webview_window = None
        self.recorded_signatures = set()

        default_target = get_default_target()

        # 启动状态机
        self.state_machine = SessionStateMachine(
            timeout_seconds=config.SESSION_TIMEOUT_SECONDS,
            on_archive_callback=self._on_archive,
            default_target=default_target
        )

        # 启动时优先静默探测微信活跃窗口
        self._init_active_context()

        # 预计算默认卡片
        active_target = self.state_machine.active_target or default_target
        self._refresh_options(active_target, self.current_incoming, self.current_context)

        # 启动后台守护工作线程
        self.running = True
        self.worker_thread = threading.Thread(target=self._background_worker, daemon=True)
        self.worker_thread.start()

    def _init_active_context(self):
        """尝试读取微信当前活跃窗口与消息"""
        try:
            snapshot = capture_chat_snapshot()
            known_contacts = [
                d for d in os.listdir(config.CONTACTS_DIR)
                if os.path.isdir(os.path.join(config.CONTACTS_DIR, d))
            ]
            if snapshot.contact_name and (snapshot.contact_name in known_contacts):
                if snapshot.incoming_text:
                    self.current_incoming = snapshot.incoming_text
                if snapshot.ego_text:
                    self.current_ego_reply = snapshot.ego_text
                if snapshot.reply_status:
                    self.current_reply_status = snapshot.reply_status
                if snapshot.dialogue_context:
                    self.current_context = snapshot.dialogue_context
                self.state_machine.active_target = snapshot.contact_name
        except Exception as e:
            print(f"[Init Context Warning] {e}")

    def _on_archive(self, target_name: str, messages):
        res = self.distiller.distill_and_archive(target_name, messages)
        print(f"[EchoLens Archive] {target_name} 归档完毕: {res}")

    def record_and_distill_turn(self, target_name: str, incoming_text: str, ego_text: Optional[str] = None) -> bool:
        """
        每次抓取到新消息或新回复时，即时脱水沉淀为长期记忆（防重复追加）
        """
        import hashlib
        from datetime import datetime
        from core.contracts import ChatMessage

        inc = (incoming_text or "").strip()
        ego = (ego_text or "").strip()
        if not inc and not ego:
            return False

        if ego in ["暂未回复", "无 (暂未回复)", "无（暂未回复）"]:
            ego = ""

        sig_raw = f"{target_name}::{inc}::{ego}"
        sig = hashlib.md5(sig_raw.encode("utf-8")).hexdigest()

        if sig in self.recorded_signatures:
            return False  # 已沉淀过，避免重复追加

        now = datetime.now()
        messages = []
        if inc:
            messages.append(ChatMessage(
                sender_name=target_name,
                role="target",
                content=inc,
                timestamp=now
            ))
        if ego:
            messages.append(ChatMessage(
                sender_name="我",
                role="me",
                content=ego,
                timestamp=now
            ))

        if not messages:
            return False

        # 立即脱水并追加写入 episodes.md 以及 SQLite index.db
        res = self.distiller.distill_and_archive(target_name, messages)
        self.recorded_signatures.add(sig)
        print(f"[EchoLens Memory] 已即时沉淀长期记忆: {res.get('theme', '')} (涉及 {len(messages)} 条消息)")
        return True

    def _refresh_options(self, target_name: str, incoming_text: str, context_text: Optional[str] = None):
        if self.current_reply_status == "replied":
            self.cached_options = []
            return
        self.current_incoming = incoming_text
        if context_text is not None:
            self.current_context = context_text
        memory_episodes = self.memory.retrieve_memory(target_name, incoming_text, self.current_context)
        result = self.generator.generate(target_name, incoming_text, memory_episodes, self.current_context)
        self.cached_options = [opt.to_dict() for opt in result.options]

    def _background_worker(self):
        while self.running:
            try:
                # 1. 超时自动归档巡检
                self.state_machine.check_timeout_and_auto_archive()

                # 2. 仅在主动开启「监控中」时才捕获剪贴板，平时待机彻底静默降频
                if self.state_machine.state == "监控中":
                    cb = get_macos_clipboard()
                    if cb and cb != self.last_clipboard_seen and cb != self.last_outgoing_reply and "按 Esc" not in cb:
                        self.last_clipboard_seen = cb
                        target = self.state_machine.active_target or get_default_target()
                        self.state_machine.feed_incoming_message(target, cb)
                        self._refresh_options(target, cb)
                    time.sleep(0.5)
                else:
                    # 待机态大幅拉长休眠周期，CPU 接近绝对 0%
                    time.sleep(2.0)
            except Exception as e:
                print(f"[Worker Error] {e}")
                time.sleep(2.0)

    def get_stats(self, target: Optional[str] = None) -> dict:
        """
        计算今日互动分析与毫秒级新数据指标:
        1. 今日相互发了多少条消息与比例 (我条数 vs TA条数)
        2. 回复时效与节奏时钟 (已发出经过时间)
        3. 今日互动热度与微观分析 (例如: TA分享欲旺盛 / 情绪积极)
        4. 今日话题焦点 (基于今日实聊内容抽取的标签)
        """
        import re
        from datetime import datetime
        target = target or self.state_machine.active_target or get_default_target()
        today_str = datetime.now().strftime("%Y-%m-%d")

        today_ego_msgs = []
        today_target_msgs = []

        # 1. 从 SQLite index.db 读取今天的事件事实记录 (条数与内容)
        if target and os.path.exists(config.CONTACTS_DIR):
            db_path = os.path.join(config.CONTACTS_DIR, target, "index.db")
            if os.path.exists(db_path):
                try:
                    import sqlite3
                    conn = sqlite3.connect(db_path)
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT facts_summary FROM episode_records 
                        WHERE episode_date LIKE ?
                    """, (f"{today_str}%",))
                    for row in cur.fetchall():
                        summary = row[0]
                        parts = re.split(r'[;\n]', summary)
                        for p in parts:
                            p_clean = p.strip()
                            if p_clean.startswith("我:"):
                                msg_txt = p_clean[2:].strip()
                                if msg_txt and msg_txt not in today_ego_msgs and len(msg_txt) >= 2:
                                    today_ego_msgs.append(msg_txt)
                            elif f"{target}:" in p_clean:
                                msg_txt = p_clean.split(":", 1)[1].strip()
                                if msg_txt and msg_txt not in today_target_msgs and len(msg_txt) >= 2:
                                    today_target_msgs.append(msg_txt)
                    conn.close()
                except Exception:
                    pass

        # 2. 结合当前活跃上下文补充未入库的今日实时消息
        noise_keys = ["点击复制", "按 Esc", "抓取最新", "小胶囊", "导入建档"]
        if self.current_incoming and len(self.current_incoming) >= 2:
            for line in self.current_incoming.split("\n"):
                l_c = line.strip()
                if l_c and l_c not in today_target_msgs and not any(k in l_c for k in noise_keys):
                    today_target_msgs.append(l_c)

        if self.current_ego_reply and self.current_ego_reply != "暂未回复":
            for line in self.current_ego_reply.split("\n"):
                l_c = line.strip()
                if l_c and l_c not in today_ego_msgs and not any(k in l_c for k in noise_keys):
                    today_ego_msgs.append(l_c)

        ego_count = len(today_ego_msgs)
        target_count = len(today_target_msgs)
        total_count = ego_count + target_count

        if total_count > 0:
            ego_percent = round((ego_count / total_count) * 100)
            target_percent = 100 - ego_percent
        else:
            ego_percent = 50
            target_percent = 50

        # 今日互动评价标签与比重分析
        if total_count >= 15:
            msg_heat_tip = "高频畅聊"
        elif total_count >= 6:
            msg_heat_tip = "互动热络"
        elif total_count >= 2:
            msg_heat_tip = "双向互动"
        else:
            msg_heat_tip = "今日预热"

        if target_percent >= 65:
            ratio_desc = f"TA 分享欲旺盛 · 今日累计 {total_count} 条互动"
        elif ego_percent >= 65:
            ratio_desc = f"我方相对主动 · 今日累计 {total_count} 条互动"
        else:
            ratio_desc = f"双向投入对等 · 今日累计 {total_count} 条互动"

        # 3. 今日话题与微观动态分析 (基于今日真实语料)
        today_corpus = " ".join(today_target_msgs + today_ego_msgs)

        today_topics = []
        topic_keywords = [
            "穿搭", "衣服", "自拍", "出行", "返程", "高铁", "周末", "美食",
            "温差", "天气", "降温", "吃", "火锅", "烧烤", "加班", "工作", "放假",
            "开会", "睡觉", "唠嗑", "电影", "咖啡"
        ]
        for kw in topic_keywords:
            if kw in today_corpus and kw not in today_topics:
                today_topics.append(kw)
            if len(today_topics) >= 3:
                break

        if not today_topics:
            today_topics = ["日常", "唠嗑"]

        # 4. 今日动态微观分析 (情商军师视角切入点)
        dynamic_title = "日常松弛互动"
        dynamic_desc = "老友日常碎语交流 · 氛围松弛无压力"

        if any(k in today_corpus for k in ["衣服", "行头", "穿搭", "自拍", "看我"]):
            dynamic_title = "主动分享生活"
            dynamic_desc = "对方主动分享穿搭自拍 · 情绪积极"
        elif any(k in today_corpus for k in ["车", "赶车", "返程", "到家", "小时", "坐车"]):
            dynamic_title = "出行动态交流"
            dynamic_desc = "围绕返程出行与路程唠嗑 · 适度关切"
        elif any(k in today_corpus for k in ["加班", "上班", "开会", "活儿", "项目"]):
            dynamic_title = "职场解压吐槽"
            dynamic_desc = "职场琐事宣泄交流 · 适度同仇敌忾"
        elif any(k in today_corpus for k in ["吃", "饭", "火锅", "烧烤", "奶茶"]):
            dynamic_title = "美食生活分享"
            dynamic_desc = "轻松美食话题 · 适合自然埋引子"
        elif any(k in today_corpus for k in ["冷", "冻", "温差", "天气", "降温"]):
            dynamic_title = "冷暖日常关切"
            dynamic_desc = "围绕温差生活细节唠嗑 · 接地气平视"

        # 5. 互动热度与兴趣窗口算法 (0 - 100 分数模型)
        base_score = 65
        if total_count >= 10:
            base_score += 15
        elif total_count >= 6:
            base_score += 10
        elif total_count >= 2:
            base_score += 6
        elif total_count == 0:
            base_score = 50

        if target_percent >= 55:
            base_score += 7

        target_corpus = " ".join(today_target_msgs)
        high_interest_triggers = [
            "自拍", "衣服", "穿搭", "看我", "照片", "视频", "哈哈", "嘻嘻", "好看",
            "发你", "推荐", "喜欢", "好吃", "想吃", "好玩", "逛街"
        ]
        curiosity_triggers = ["吗", "呢", "啥", "什么", "怎么", "?", "？"]

        if any(k in target_corpus for k in high_interest_triggers):
            base_score += 8
        if any(k in target_corpus for k in curiosity_triggers):
            base_score += 5

        if ego_percent >= 70 and ego_count >= 4:
            base_score -= 10

        warmth_score = max(35, min(98, base_score))

        if warmth_score >= 80:
            warmth_badge = "高兴趣"
            warmth_window = "高兴趣窗口"
            warmth_tactic = "情绪高位 · 适合顺势拉扯或邀约"
        elif warmth_score >= 70:
            warmth_badge = "积极热络"
            warmth_window = "双向顺畅"
            warmth_tactic = "节奏舒适 · 维持双向生活分享"
        elif warmth_score >= 55:
            warmth_badge = "平稳温和"
            warmth_window = "舒适日常"
            warmth_tactic = "日常唠嗑 · 适时切断保持神秘"
        else:
            warmth_badge = "平淡观望"
            warmth_window = "窗口收窄"
            warmth_tactic = "降低字数 · 保持平视不追问"

        last_reply_ts = getattr(self, "last_outgoing_time", None)
        if not last_reply_ts and self.current_reply_status == "replied":
            self.last_outgoing_time = time.time()
            last_reply_ts = self.last_outgoing_time

        return {
            "today_ego_count": ego_count,
            "today_target_count": target_count,
            "today_total_count": total_count,
            "ego_percent": ego_percent,
            "target_percent": target_percent,
            "msg_heat_tip": msg_heat_tip,
            "ratio_desc": ratio_desc,
            "warmth_score": warmth_score,
            "warmth_badge": warmth_badge,
            "warmth_window": warmth_window,
            "warmth_tactic": warmth_tactic,
            "last_reply_timestamp": last_reply_ts,
            "dynamic_title": dynamic_title,
            "dynamic_desc": dynamic_desc,
            "today_topics": today_topics,
            "relationship_stage": "熟络日常"
        }

    def probe_catchup(self, target_name: str):
        cb = get_macos_clipboard()
        if cb and "按 Esc" not in cb and cb != self.last_outgoing_reply:
            self.last_clipboard_seen = cb
            self._refresh_options(target_name, cb)
            msg = __import__("core.contracts", fromlist=["ChatMessage"]).ChatMessage(
                sender_name=target_name,
                role="target",
                content=cb,
                timestamp=__import__("datetime").datetime.now()
            )
            return [msg]
        return []

# 全局单例
service_instance = EchoLensService()
