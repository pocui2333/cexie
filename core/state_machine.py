import time
from typing import Optional, Callable, List, Dict, Any
from core.contracts import ChatMessage

class SessionStateMachine:
    """
    单目标无感状态机:
    - 待机中 (IDLE) / 监控中 (MONITORING) / 归档中 (ARCHIVING)
    - 纯鼠标交互驱动: 开始监控 / 结束并归档
    - 启动即回溯 (Start-up Backlog Catch-up): 点击开始瞬间自动补齐未读气泡
    - 30分钟静默超时兜底自动归档
    """
    def __init__(self, timeout_seconds: int = 1800, on_archive_callback: Optional[Callable] = None, default_target: str = "示例好友"):
        self.state: str = "待机中"
        self.active_target: str = default_target
        self.timeout_seconds: int = timeout_seconds
        self.on_archive_callback = on_archive_callback
        self.session_start_time: Optional[float] = None
        self.last_activity_time: Optional[float] = None
        self.current_incoming_text: str = ""
        self.last_sender_name: str = default_target
        self.last_incoming_time_str: str = "刚刚"
        self.session_messages: List[ChatMessage] = []

    def start_monitoring(self, target_name: str, backlog_catchup_func: Optional[Callable] = None) -> Dict[str, Any]:
        self.active_target = target_name
        self.state = "监控中"
        self.session_start_time = time.time()
        self.last_activity_time = self.session_start_time
        self.session_messages.clear()

        catchup_count = 0
        if backlog_catchup_func:
            messages = backlog_catchup_func(target_name)
            if messages:
                for msg in messages:
                    self.session_messages.append(msg)
                    self.current_incoming_text = msg.content
                catchup_count = len(messages)
                self.last_activity_time = time.time()

        return {
            "status": "success",
            "state": self.state,
            "target": self.active_target,
            "catchup_count": catchup_count,
            "current_incoming": self.current_incoming_text
        }

    def feed_incoming_message(self, target_name: str, content: str) -> bool:
        # 如果切换了联系人，自动将上一人的未归档会话归档
        if self.active_target != target_name and self.session_messages:
            self.stop_and_archive()
            self.active_target = target_name

        self.active_target = target_name
        self.state = "就绪"

        msg = ChatMessage(
            sender_name=target_name,
            role="target",
            content=content,
            timestamp=__import__("datetime").datetime.now()
        )
        self.session_messages.append(msg)
        self.current_incoming_text = content
        self.last_sender_name = target_name
        self.last_incoming_time_str = msg.timestamp.strftime("%H:%M:%S")
        self.last_activity_time = time.time()
        return True

    def feed_outgoing_reply(self, reply_text: str):
        msg = ChatMessage(
            sender_name="我",
            role="me",
            content=reply_text,
            timestamp=__import__("datetime").datetime.now()
        )
        self.session_messages.append(msg)
        self.last_activity_time = time.time()

    def check_timeout_and_auto_archive(self) -> bool:
        if self.last_activity_time and self.session_messages:
            if time.time() - self.last_activity_time > self.timeout_seconds:
                self.stop_and_archive()
                return True
        return False

    def stop_and_archive(self) -> Dict[str, Any]:
        if not self.session_messages:
            return {"status": "no_messages"}

        archived_count = len(self.session_messages)
        target = self.active_target

        if self.on_archive_callback and self.session_messages:
            try:
                self.on_archive_callback(target, list(self.session_messages))
            except Exception as e:
                print(f"[Archive Error] {e}")

        self.session_messages.clear()
        self.state = "待机中"
        self.session_start_time = None
        self.last_activity_time = None
        self.current_incoming_text = ""

        return {
            "status": "success",
            "state": "待机中",
            "target": target,
            "archived_count": archived_count
        }

    def get_duration_str(self) -> str:
        if self.state != "监控中" or not self.session_start_time:
            return "00:00:00"
        elapsed = int(time.time() - self.session_start_time)
        hrs = elapsed // 3600
        mins = (elapsed % 3600) // 60
        secs = elapsed % 60
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
