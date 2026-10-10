import logging
import os
import time
import subprocess
from typing import Optional
from capture.names import is_contact_match

logger = logging.getLogger(__name__)

def ensure_wechat_unminimized():
    """若微信窗口被最小化到 Dock 栏，静默恢复其窗口 (无需置顶夺取焦点)"""
    script = """
    tell application "System Events"
        if exists (process "WeChat") then
            tell process "WeChat"
                set minWins to (every window whose value of attribute "AXMinimized" is true)
                if (count of minWins) > 0 then
                    repeat with w in minWins
                        set value of attribute "AXMinimized" of w to false
                    end repeat
                end if
            end tell
        end if
    end tell
    """
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=1.5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def find_wechat_main_window_id(expected_target: Optional[str] = None, retry_unminimize: bool = True) -> Optional[int]:
    """通过 Quartz CGWindowList 获取微信主聊天窗口 ID (支持独立窗口与屏幕在显优化)"""
    try:
        from Quartz import (
            CGWindowListCopyWindowInfo,
            kCGWindowListExcludeDesktopElements,
            kCGNullWindowID,
            kCGWindowOwnerName,
            kCGWindowNumber,
            kCGWindowBounds,
            kCGWindowLayer,
            kCGWindowName,
            kCGWindowIsOnscreen
        )
        windows = CGWindowListCopyWindowInfo(kCGWindowListExcludeDesktopElements, kCGNullWindowID)
        candidates = []
        for w in windows:
            owner = w.get(kCGWindowOwnerName, "")
            layer = w.get(kCGWindowLayer, 0)
            if owner == "WeChat" and layer == 0:
                b = w.get(kCGWindowBounds, {})
                width = b.get("Width", 0)
                height = b.get("Height", 0)
                # 排除微型小图标或悬浮窗，保留主聊天大窗口
                if width > 400 and height > 400:
                    priority = 0
                    w_name = w.get(kCGWindowName, "") or ""
                    # 若独立单聊窗口名直接命中目标备注，赋予极高优先级
                    if expected_target and is_contact_match(w_name, expected_target):
                        priority += 1000
                    # 屏幕在显窗口加分
                    if w.get(kCGWindowIsOnscreen, False):
                        priority += 100
                    candidates.append((w.get(kCGWindowNumber), priority, width * height))

        if candidates:
            # 选优先级最高、面积最大的
            candidates.sort(key=lambda x: (-x[1], -x[2]))
            return candidates[0][0]

        # 若未找到且允许重试，尝试静默恢复最小化窗口
        if retry_unminimize:
            ensure_wechat_unminimized()
            time.sleep(0.2)
            return find_wechat_main_window_id(expected_target=expected_target, retry_unminimize=False)

    except Exception as e:
        logger.error("[Window Finder Error] %s", e)
    return None

def capture_window_screenshot(win_id: int, output_path: str) -> bool:
    """使用 macOS 原生 screencapture 静默截取指定窗口 (含最小化恢复重试)"""
    try:
        subprocess.run(["screencapture", f"-l{win_id}", "-x", output_path], check=True, timeout=2.5)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 5000:
            return True
        # 若图片过小或截取失败，可能是刚恢复或被最小化，尝试唤醒后重试
        ensure_wechat_unminimized()
        time.sleep(0.2)
        subprocess.run(["screencapture", f"-l{win_id}", "-x", output_path], check=True, timeout=2.5)
        return os.path.exists(output_path) and os.path.getsize(output_path) > 5000
    except Exception as e:
        logger.error("[Screenshot Error] %s", e)
        return False
