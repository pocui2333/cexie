"""
EchoLens Service Layer:
Coordinates capture, memory, dual-track generator, and background workers.
HTTP handlers only parse requests and serialize responses; all business flow lives here.
"""
import logging
import threading
import time
from typing import Any, Dict, List, Optional

import config
from capture import capture_chat_snapshot, is_contact_match
from core import store
from core.contracts import NO_REPLY
from core.generator import DualTrackGenerator
from core.memory import EntityMemoryRetriever
from core.state_machine import SessionStateMachine
from ingestion.contact_profiler import ContactProfiler
from ingestion.episodic_distiller import EpisodicDistiller

logger = logging.getLogger(__name__)

STATS_CACHE_SECONDS = 5.0


def get_default_target() -> str:
    """动态获取默认联系人 (优先历史记忆最丰富的真实联系人，兜底示例好友)"""
    dirs = store.list_contacts()
    user_contacts = [d for d in dirs if d != store.EXAMPLE_CONTACT]
    if user_contacts:
        def _episode_count(name: str) -> int:
            try:
                with store.connect(name) as conn:
                    return conn.execute("SELECT COUNT(*) FROM episode_records").fetchone()[0] if conn else 0
            except Exception:
                return 0
        return max(user_contacts, key=_episode_count)
    return store.EXAMPLE_CONTACT


class EchoLensService:
    def __init__(self):
        self.memory = EntityMemoryRetriever(config.CONTACTS_DIR)
        self.generator = DualTrackGenerator(config.EGO_DIR, config.CONTACTS_DIR, config.KNOWLEDGE_DIR)
        self.profiler = ContactProfiler(config.CONTACTS_DIR)
        self.distiller = EpisodicDistiller(config.CONTACTS_DIR)
        self.state_machine = SessionStateMachine(default_target=get_default_target())

        self.current_incoming = ""
        self.current_ego_reply = NO_REPLY
        self.current_reply_status = "pending"
        self.current_context = ""
        self.last_outgoing_time: Optional[float] = None
        self.cached_options: List[Dict[str, Any]] = []
        self.cached_insight: Dict[str, Any] = {"subtext": "", "risk_alert": "", "keywords": []}
        self.webview_window = None

        # 同一时刻只允许一次抓取 (手动抓取与自动循环共用，避免同时截图与重复沉淀)
        self._capture_lock = threading.Lock()
        # 保护 current_* / cached_* 等共享展示状态
        self._state_lock = threading.RLock()
        # 生成任务序号：只有最新一次请求的结果才会写回卡片
        self._gen_seq = 0
        self._gen_inflight = 0
        self._stats_cache: Optional[tuple] = None

        self.auto_loop_enabled = False
        self.auto_loop_interval = 60
        self.auto_loop_countdown = 60
        self.running = True

    def start(self) -> None:
        """启动后台线程；启动探测放到后台执行，悬浮窗无需等待截图与大模型调用"""
        threading.Thread(target=self._startup_probe, daemon=True).start()
        threading.Thread(target=self._auto_loop_worker, daemon=True).start()

    @property
    def active_target(self) -> str:
        return self.state_machine.active_target or get_default_target()

    @property
    def generating(self) -> bool:
        return self._gen_inflight > 0

    # ------------------------------------------------------------------ #
    # 抓取主流程
    # ------------------------------------------------------------------ #
    def _startup_probe(self) -> None:
        """尝试读取微信当前活跃窗口；若正好停在已建档联系人，则直接以其为目标"""
        try:
            snapshot = capture_chat_snapshot()
            matched = next((c for c in store.list_contacts() if is_contact_match(snapshot.contact_name, c)), None)
            if matched:
                with self._state_lock:
                    self.state_machine.active_target = matched
                    self.current_incoming = snapshot.incoming_text or ""
                    self.current_ego_reply = snapshot.ego_text or NO_REPLY
                    self.current_reply_status = snapshot.reply_status
                    self.current_context = snapshot.dialogue_context
        except Exception as e:
            logger.warning("[Init Context Warning] %s", e)
        self.schedule_generation(self.active_target)

    def capture_and_refresh(self, expected_target: Optional[str] = None) -> Dict[str, Any]:
        """
        单次抓取：核验联系人 -> 增量沉淀记忆 -> 更新展示状态 -> 后台重新生成 6 档建议。
        立即返回抓取结果，新的建议卡片由前端轮询 /api/poll 获取 (generating 标记生成中)。
        """
        target = store.validate_contact_name(expected_target or self.active_target)
        if not self._capture_lock.acquire(blocking=False):
            return self._response("busy", target, message="上一轮抓取正在进行中，已自动节流防抖")

        try:
            snapshot = capture_chat_snapshot(expected_target=target)
            if snapshot.is_mismatch:
                detected = snapshot.contact_name or "未识别的窗口"
                return self._response(
                    "mismatch", target, detected=detected,
                    message=f"当前微信窗口为「{detected}」，与目标备注「{target}」不一致！未执行抓取与记录。"
                )
            if not snapshot.raw_turns and not snapshot.incoming_text:
                return self._response("capture_failed", target, message="未抓取到聊天内容，请确认微信窗口未被遮挡或最小化")

            distill_res = self.distiller.record_turns(target, snapshot.raw_turns, time_hint=snapshot.time_hint)
            recorded = distill_res.get("status") == "recorded"
            is_replied = snapshot.case_type == 1

            with self._state_lock:
                self.state_machine.active_target = target
                self.current_incoming = snapshot.incoming_text or self.current_incoming
                self.current_ego_reply = snapshot.ego_text or self.current_ego_reply
                self.current_reply_status = snapshot.reply_status
                self.current_context = snapshot.dialogue_context
                if is_replied:
                    # 情况 1: 最后一条是我的回复 -> 生成【主动推进/延伸话轮】建议
                    if not self.last_outgoing_time:
                        self.last_outgoing_time = time.time()
                else:
                    # 情况 2: 对方有新消息待回复 -> 生成最新 6 档自然回复
                    self.last_outgoing_time = None
                    self.state_machine.feed_incoming_message(target, self.current_incoming)

            self.schedule_generation(
                target, is_replied=is_replied,
                ego_text=snapshot.ego_text if is_replied else None
            )

            if is_replied:
                message = "已抓取并沉淀记忆，正在生成推进建议" if recorded else "已同步最新对话，正在生成推进建议"
            else:
                message = "已抓取并沉淀记忆，正在生成最新推荐" if recorded else "已捕获对方新消息，正在生成最新推荐"
            return self._response(
                "success", target, case_type=snapshot.case_type, recorded=recorded,
                distill_summary=distill_res, message=message
            )
        finally:
            self._capture_lock.release()

    def _response(self, status: str, target: str, **extra) -> Dict[str, Any]:
        with self._state_lock:
            payload = {
                "status": status,
                "target": target,
                "incoming_text": self.current_incoming,
                "ego_text": self.current_ego_reply,
                "reply_status": self.current_reply_status,
                "options": self.cached_options,
                "insight": self.cached_insight,
                "generating": self.generating,
            }
        if status == "success":
            payload["stats"] = self.get_stats(target)
        payload.update(extra)
        return payload

    # ------------------------------------------------------------------ #
    # 建议生成 (后台异步，只保留最新一次请求的结果)
    # ------------------------------------------------------------------ #
    def schedule_generation(self, target_name: str, is_replied: bool = False, ego_text: Optional[str] = None) -> None:
        with self._state_lock:
            self._gen_seq += 1
            self._gen_inflight += 1
            seq = self._gen_seq
            incoming, context = self.current_incoming, self.current_context
        threading.Thread(
            target=self._run_generation,
            args=(seq, target_name, incoming, context, is_replied, ego_text),
            daemon=True
        ).start()

    def _run_generation(self, seq: int, target_name: str, incoming: str, context: str,
                        is_replied: bool, ego_text: Optional[str]) -> None:
        try:
            memory_episodes = self.memory.retrieve_memory(target_name, incoming, context)
            today_memory = self.memory.get_today_working_memory(target_name)
            result = self.generator.generate(
                target_name, incoming, memory_episodes, context,
                today_memory=today_memory, is_replied=is_replied, last_ego_text=ego_text
            )
            with self._state_lock:
                if seq == self._gen_seq:
                    self.cached_options = [opt.to_dict() for opt in result.options]
                    self.cached_insight = {
                        "subtext": result.subtext,
                        "risk_alert": result.risk_alert,
                        "keywords": result.keywords
                    }
        except Exception as e:
            logger.error("[Generation Error] %s", e)
        finally:
            with self._state_lock:
                self._gen_inflight -= 1

    def set_target(self, target: str) -> str:
        target = store.validate_contact_name(target)
        with self._state_lock:
            self.state_machine.active_target = target
        self.schedule_generation(target)
        return target

    def inject_options(self, options: List[Dict[str, Any]]) -> None:
        """外部智能体直接推送 6 档卡片；同时作废尚未完成的内置生成任务，避免被覆盖"""
        with self._state_lock:
            self._gen_seq += 1
            self.cached_options = options

    # ------------------------------------------------------------------ #
    # 自动循环抓取
    # ------------------------------------------------------------------ #
    def _auto_loop_worker(self) -> None:
        """Python 后端自运转循环抓取线程 (不受 WKWebView 节电休眠影响)"""
        while self.running:
            time.sleep(1.0)
            if not self.auto_loop_enabled:
                continue
            self.auto_loop_countdown -= 1
            if self.auto_loop_countdown > 0:
                continue
            self.auto_loop_countdown = self.auto_loop_interval
            try:
                self.capture_and_refresh()
            except Exception as e:
                logger.error("[Auto Loop Background Error] %s", e)

    def set_auto_loop(self, enabled: bool, interval: int = 60) -> dict:
        self.auto_loop_enabled = bool(enabled)
        self.auto_loop_interval = max(10, int(interval))
        self.auto_loop_countdown = self.auto_loop_interval
        return {
            "status": "success",
            "auto_loop_enabled": self.auto_loop_enabled,
            "auto_loop_countdown": self.auto_loop_countdown
        }

    # ------------------------------------------------------------------ #
    # 轮询快照与今日统计
    # ------------------------------------------------------------------ #
    def poll_snapshot(self) -> Dict[str, Any]:
        with self._state_lock:
            snapshot = {
                "target": self.state_machine.active_target,
                "incoming_text": self.current_incoming,
                "ego_text": self.current_ego_reply,
                "reply_status": self.current_reply_status,
                "sender_name": self.state_machine.last_sender_name,
                "message_time": self.state_machine.last_incoming_time_str,
                "options": self.cached_options,
                "insight": self.cached_insight,
                "generating": self.generating,
                "auto_loop_enabled": self.auto_loop_enabled,
                "auto_loop_countdown": self.auto_loop_countdown
            }
        snapshot["stats"] = self.get_stats()
        return snapshot

    def get_stats(self, target: Optional[str] = None) -> dict:
        """今日互动分析 (前端每 1.5s 轮询，按输入状态做短时缓存避免重复查库)"""
        target = target or self.active_target
        with self._state_lock:
            key = (target, self.current_incoming, self.current_ego_reply, self.current_reply_status, self.last_outgoing_time)
        cached = self._stats_cache
        if cached and cached[0] == key and time.time() - cached[1] < STATS_CACHE_SECONDS:
            return cached[2]
        stats = self._compute_stats(target)
        self._stats_cache = (key, time.time(), stats)
        return stats

    def _compute_stats(self, target: str) -> dict:
        """
        计算今日互动分析:
        1. 今日相互发了多少条消息与比例 (我条数 vs TA条数)
        2. 回复时效与节奏时钟 (已发出经过时间)
        3. 今日互动热度与微观分析 (例如: TA分享欲旺盛 / 情绪积极)
        4. 今日话题焦点 (基于今日实聊内容抽取的标签)
        """
        today_ego_msgs: List[str] = []
        today_target_msgs: List[str] = []

        # 1. 从 index.db 读取今天的事实记录
        for line in self.memory.get_today_fact_lines(target):
            if line.startswith("我:"):
                msg = line[2:].strip()
                if len(msg) >= 2 and msg not in today_ego_msgs:
                    today_ego_msgs.append(msg)
            elif line.startswith(f"{target}:"):
                msg = line.split(":", 1)[1].strip()
                if len(msg) >= 2 and msg not in today_target_msgs:
                    today_target_msgs.append(msg)

        # 2. 结合当前活跃上下文补充未入库的今日实时消息
        noise_keys = ["点击复制", "按 Esc", "抓取最新", "小胶囊", "导入建档"]
        with self._state_lock:
            incoming, ego_reply = self.current_incoming, self.current_ego_reply
            reply_status, last_reply_ts = self.current_reply_status, self.last_outgoing_time
        for line in (incoming or "").split("\n"):
            l_c = line.strip()
            if len(l_c) >= 2 and l_c not in today_target_msgs and not any(k in l_c for k in noise_keys):
                today_target_msgs.append(l_c)
        if ego_reply and ego_reply != NO_REPLY:
            for line in ego_reply.split("\n"):
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
            ego_percent = target_percent = 50

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
        topic_keywords = [
            "穿搭", "衣服", "自拍", "出行", "返程", "高铁", "周末", "美食",
            "温差", "天气", "降温", "吃", "火锅", "烧烤", "加班", "工作", "放假",
            "开会", "睡觉", "唠嗑", "电影", "咖啡"
        ]
        today_topics = [kw for kw in topic_keywords if kw in today_corpus][:3] or ["日常", "唠嗑"]

        # 4. 今日动态微观分析 (情商军师视角切入点)
        dynamic_title = "日常松弛互动"
        dynamic_desc = "老友日常碎语交流 · 氛围松弛无压力"
        if any(k in today_corpus for k in ["衣服", "行头", "穿搭", "自拍", "看我"]):
            dynamic_title, dynamic_desc = "主动分享生活", "对方主动分享穿搭自拍 · 情绪积极"
        elif any(k in today_corpus for k in ["车", "赶车", "返程", "到家", "小时", "坐车"]):
            dynamic_title, dynamic_desc = "出行动态交流", "围绕返程出行与路程唠嗑 · 适度关切"
        elif any(k in today_corpus for k in ["加班", "上班", "开会", "活儿", "项目"]):
            dynamic_title, dynamic_desc = "职场解压吐槽", "职场琐事宣泄交流 · 适度同仇敌忾"
        elif any(k in today_corpus for k in ["吃", "饭", "火锅", "烧烤", "奶茶"]):
            dynamic_title, dynamic_desc = "美食生活分享", "轻松美食话题 · 适合自然埋引子"
        elif any(k in today_corpus for k in ["冷", "冻", "温差", "天气", "降温"]):
            dynamic_title, dynamic_desc = "冷暖日常关切", "围绕温差生活细节唠嗑 · 接地气平视"

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
            warmth_badge, warmth_window, warmth_tactic = "高兴趣", "高兴趣窗口", "情绪高位 · 适合顺势拉扯或邀约"
        elif warmth_score >= 70:
            warmth_badge, warmth_window, warmth_tactic = "积极热络", "双向顺畅", "节奏舒适 · 维持双向生活分享"
        elif warmth_score >= 55:
            warmth_badge, warmth_window, warmth_tactic = "平稳温和", "舒适日常", "日常唠嗑 · 适时切断保持神秘"
        else:
            warmth_badge, warmth_window, warmth_tactic = "平淡观望", "窗口收窄", "降低字数 · 保持平视不追问"

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
            "last_reply_timestamp": last_reply_ts if reply_status == "replied" else None,
            "dynamic_title": dynamic_title,
            "dynamic_desc": dynamic_desc,
            "today_topics": today_topics,
            "relationship_stage": "熟络日常"
        }


# 全局单例 (后台线程由 app.main 显式调用 start() 启动，导入本模块不再触发截图与模型调用)
service_instance = EchoLensService()
