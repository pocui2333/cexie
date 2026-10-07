"""
macOS WeChat Window detection and silent screenshot utilities.
"""
import subprocess
from typing import Optional

def find_wechat_main_window_id() -> Optional[int]:
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
    except Exception as e:
        print(f"[Window Finder Error] {e}")
    return None

def capture_window_screenshot(win_id: int, output_path: str = "/tmp/echolens_wc_win.png") -> bool:
    """使用 macOS 原生 screencapture 静默截取指定窗口"""
    try:
        subprocess.run(["screencapture", f"-l{win_id}", "-x", output_path], check=True, timeout=2.5)
        return True
    except Exception as e:
        print(f"[Screenshot Error] {e}")
        return False
