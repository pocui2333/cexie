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
    """动态获取默认联系人 (优先已有活跃真实联系人，兜底示例好友)"""
    if os.path.exists(config.CONTACTS_DIR):
        dirs = [
            d for d in os.listdir(config.CONTACTS_DIR)
            if os.path.isdir(os.path.join(config.CONTACTS_DIR, d)) and not d.startswith('.')
        ]
        user_contacts = [d for d in dirs if d != "示例好友"]
        if user_contacts:
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

                # 2. 监控中自动毫秒级捕获微信复制文字
                if self.state_machine.state == "监控中":
                    cb = get_macos_clipboard()
                    if cb and cb != self.last_clipboard_seen and cb != self.last_outgoing_reply and "按 Esc" not in cb:
                        self.last_clipboard_seen = cb
                        target = self.state_machine.active_target or get_default_target()
                        self.state_machine.feed_incoming_message(target, cb)
                        self._refresh_options(target, cb)
            except Exception as e:
                print(f"[Worker Error] {e}")
            time.sleep(0.2)

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
