"""
Capture package for WeChat desktop window and message extraction.
"""
from capture.wechat_driver import capture_wechat_chat_context, capture_chat_snapshot, is_contact_match
from capture.window import find_wechat_main_window_id
from core.contracts import ChatCaptureResult

__all__ = [
    "capture_wechat_chat_context",
    "capture_chat_snapshot",
    "is_contact_match",
    "find_wechat_main_window_id",
    "ChatCaptureResult"
]
