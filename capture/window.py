import os
import time
import subprocess
from typing import Optional

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

def find_wechat_main_window_id(retry_unminimize: bool = True) -> Optional[int]:
    """通过 Quartz CGWindowList 获取微信主聊天窗口 ID"""
    try:
        from Quartz import (
            CGWindowListCopyWindowInfo,
            kCGWindowListExcludeDesktopElements,
            kCGNullWindowID,
            kCGWindowOwnerName,
            kCGWindowNumber,
            kCGWindowBounds,
            kCGWindowLayer
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
                    candidates.append((w.get(kCGWindowNumber), width * height))

        if candidates:
            # 选面积最大、最像主窗口的
            candidates.sort(key=lambda x: -x[1])
            return candidates[0][0]

        # 若未找到且允许重试，尝试静默恢复最小化窗口
        if retry_unminimize:
            ensure_wechat_unminimized()
            time.sleep(0.2)
            return find_wechat_main_window_id(retry_unminimize=False)

    except Exception as e:
        print(f"[Window Finder Error] {e}")
    return None

def capture_window_screenshot(win_id: int, output_path: str = "/tmp/echolens_wc_win.png") -> bool:
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
        print(f"[Screenshot Error] {e}")
        return False

def scroll_wechat_chat_panel(win_id: int, lines_delta: int) -> bool:
    """
    通过 CoreGraphics 向微信主聊天窗口消息气泡区域发送平滑滚轮事件:
    - lines_delta > 0: 向上滚动 (回溯上一屏/顶上去的历史消息)
    - lines_delta < 0: 向下滚动 (秒级还原视口至最底部)
    """
    try:
        import Quartz
        windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListExcludeDesktopElements, Quartz.kCGNullWindowID)
        win_info = next((w for w in windows if w.get(Quartz.kCGWindowNumber) == win_id), None)
        if not win_info:
            return False

        b = win_info.get(Quartz.kCGWindowBounds, {})
        wx = b.get("X", 0)
        wy = b.get("Y", 0)
        ww = b.get("Width", 0)
        wh = b.get("Height", 0)

        # 微信右侧主聊天消息气泡区域的几何中心
        cx = wx + ww * 0.65
        cy = wy + wh * 0.45

        orig_pos = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        Quartz.CGWarpMouseCursorPosition(Quartz.CGPoint(cx, cy))

        evt = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, lines_delta)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, evt)

        time.sleep(0.04)
        Quartz.CGWarpMouseCursorPosition(orig_pos)
        return True
    except Exception as e:
        print(f"[Scroll Error] {e}")
        return False

