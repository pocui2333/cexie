#!/usr/bin/env python3
"""
侧写 (Cexie / EchoLens) - macOS Desktop Wingman
Main Entry Point.
"""
import threading
from http.server import ThreadingHTTPServer
import config
from server import service_instance, EchoLensHTTPHandler

def main():
    port = config.SERVER_PORT
    httpd = ThreadingHTTPServer((config.SERVER_HOST, port), EchoLensHTTPHandler)
    url = f"http://{config.SERVER_HOST}:{port}/index.html"
    print(f"[侧写] 服务已启动: {url}")

    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

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
    except Exception as e:
        print(f"[EchoLens] pywebview 运行退出: {e}")
    finally:
        print("\n[EchoLens] 服务安全退出")
        service_instance.running = False
        httpd.server_close()

if __name__ == "__main__":
    main()
