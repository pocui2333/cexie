#!/usr/bin/env python3
"""
侧写 (Cexie / EchoLens) - macOS Desktop Wingman
Main Entry Point.
"""
import logging
import threading
from http.server import ThreadingHTTPServer
import config
from server import service_instance, EchoLensHTTPHandler

logger = logging.getLogger("echolens")

def main():
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    port = config.SERVER_PORT
    httpd = None
    for try_p in dict.fromkeys([port, port + 1, port + 2, 8766, 8767]):
        try:
            httpd = ThreadingHTTPServer((config.SERVER_HOST, try_p), EchoLensHTTPHandler)
            port = try_p
            break
        except OSError:
            continue
    if not httpd:
        logger.error("无法绑定本地 HTTP 端口")
        return

    url = f"http://{config.SERVER_HOST}:{port}/index.html"
    logger.info("服务已启动: %s", url)

    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    service_instance.start()

    try:
        import webview
        window = webview.create_window(
            title="侧写",
            url=url,
            width=config.WINDOW_EXPANDED_WIDTH,
            height=config.WINDOW_EXPANDED_HEIGHT,
            resizable=False,
            frameless=True,
            on_top=True,
            transparent=True,
            easy_drag=True
        )
        service_instance.webview_window = window
        webview.start()
        # 若悬浮窗关闭但未通过 /api/quit 显式退出，保持后台服务持续常驻
        if service_instance.running:
            logger.info("悬浮窗已关闭，HTTP 后台服务持续常驻运行: %s", url)
            server_thread.join()
    except Exception as e:
        logger.exception("运行异常: %s", e)
        if service_instance.running:
            server_thread.join()
    finally:
        logger.info("服务安全退出")
        service_instance.running = False
        try:
            httpd.server_close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
