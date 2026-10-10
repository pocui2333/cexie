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
        self.cached_options: List[Dict[str, Any]] = []
        self.cached_insights: List[Dict[str, str]] = []
        self.cached_risk_alert = ""
        self.webview_window = None

        # 同一时刻只允许一次抓取 (手动抓取与自动循环共用，避免同时截图与重复沉淀)
        self._capture_lock = threading.Lock()
        # 保护 current_* / cached_* 等共享展示状态
        self._state_lock = threading.RLock()
        # 生成任务序号：只有最新一次请求的结果才会写回卡片
        self._gen_seq = 0
        self._gen_inflight = 0

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
        单次抓取：核验联系人 -> 增量沉淀记忆 -> 更新展示状态 -> 后台重新生成 4 条建议。
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
                # 以本次抓取为准整体覆盖，不回退到上一轮的旧值 (否则会展示过期的对方消息 / 我方回复)
                incoming_changed = (snapshot.incoming_text or "") != self.current_incoming
                self.current_incoming = snapshot.incoming_text or ""
                self.current_ego_reply = snapshot.ego_text or NO_REPLY
                self.current_reply_status = snapshot.reply_status
                self.current_context = snapshot.dialogue_context
                # 情况 1: 最后一条是我的回复 -> 生成【主动推进/延伸话轮】建议
                # 情况 2: 对方有新消息待回复 -> 生成最新 4 条自然回复
                if not is_replied and incoming_changed:
                    # 仅在对方消息真正变化时刷新时间，避免每次轮询抓取都把时间刷成"刚刚"
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
                "insights": self.cached_insights,
                "risk_alert": self.cached_risk_alert,
                "generating": self.generating,
            }
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
                    self.cached_insights = result.insights
                    self.cached_risk_alert = result.risk_alert
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
        """外部智能体直接推送建议卡片；同时作废尚未完成的内置生成任务，避免被覆盖"""
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
    # 轮询快照
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
                "insights": self.cached_insights,
                "risk_alert": self.cached_risk_alert,
                "generating": self.generating,
                "auto_loop_enabled": self.auto_loop_enabled,
                "auto_loop_countdown": self.auto_loop_countdown
            }
        return snapshot


# 全局单例 (后台线程由 app.main 显式调用 start() 启动，导入本模块不再触发截图与模型调用)
service_instance = EchoLensService()
