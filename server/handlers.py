"""
HTTP Handler for EchoLens HUD frontend.
Dispatches REST APIs and serves static UI assets.
仅负责请求校验、参数解析与响应序列化，业务流程统一在 server.service 中实现。
"""
import logging
import os
import json
import time
import threading
from urllib.parse import urlparse, parse_qs
from http.server import SimpleHTTPRequestHandler
import config
from core import store
from server.service import service_instance

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_KNOWLEDGE_FILE_BYTES = 1 * 1024 * 1024
KNOWLEDGE_FILE_EXTS = (".md", ".txt", ".markdown")


def _read_text(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class EchoLensHTTPHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=config.HUD_DIR, **kwargs)

    # ------------------------------------------------------------------ #
    # 访问控制：接口会暴露聊天内容与本地文件，只允许本机 HUD 页面与本机命令行工具调用
    # ------------------------------------------------------------------ #
    def _allowed_hosts(self) -> set:
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _check_access(self) -> bool:
        """
        - Host 必须是本机回环地址 (防 DNS rebinding)
        - 若带 Origin (浏览器发起)，必须是 HUD 自身源 (防任意网页跨站读取 / 调用接口)；
          curl 等本机命令行工具不带 Origin，可正常调用 (如 /api/inject_options)
        """
        allowed = self._allowed_hosts()
        if self.headers.get("Host", "") not in allowed:
            self._send_json({"error": "forbidden_host"}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {f"http://{h}" for h in allowed}:
            self._send_json({"error": "forbidden_origin"}, 403)
            return False
        return True

    def _target_param(self, value) -> str:
        """解析并校验联系人参数 (缺省为当前目标)，非法时抛 InvalidContactName"""
        return store.validate_contact_name(value or service_instance.active_target)

    # ------------------------------------------------------------------ #
    # GET
    # ------------------------------------------------------------------ #
    def do_GET(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            return super().do_GET()
        if not self._check_access():
            return
        try:
            self._dispatch_get(parsed)
        except store.InvalidContactName as e:
            self._send_json({"status": "error", "message": str(e)}, 400)

    def _dispatch_get(self, parsed):
        if parsed.path == "/api/contacts":
            contacts = store.list_contacts()
            active = service_instance.active_target
            self._send_json({"contacts": contacts or [active], "active_target": active})

        elif parsed.path == "/api/poll":
            self._send_json(service_instance.poll_snapshot())

        elif parsed.path == "/api/profile":
            qs = parse_qs(parsed.query)
            target = self._target_param(qs.get("target", [None])[0])
            target_dir = store.contact_dir(target)
            rules_obj = {}
            try:
                rules_obj = json.loads(_read_text(os.path.join(target_dir, "rules.json")) or "{}")
            except ValueError:
                pass
            self._send_json({
                "target": target,
                "dossier": _read_text(os.path.join(target_dir, "dossier.md")),
                "episodes": _read_text(os.path.join(target_dir, "episodes.md")),
                "rules": rules_obj
            })

        elif parsed.path == "/api/playbooks":
            playbooks = service_instance.generator.knowledge_retriever.playbooks
            self._send_json({
                "total": len(playbooks),
                "playbooks": [{"id": p.get("id"), "title": p.get("title"), "category": p.get("category")} for p in playbooks]
            })
        else:
            self._send_json({"error": "not_found"}, 404)

    # ------------------------------------------------------------------ #
    # POST
    # ------------------------------------------------------------------ #
    def do_POST(self):
        parsed = urlparse(self.path)
        if not self._check_access():
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > MAX_BODY_BYTES:
            self._send_json({"error": "payload_too_large"}, 413)
            return
        payload = {}
        if length > 0:
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except ValueError:
                self._send_json({"error": "invalid_json"}, 400)
                return
        if not isinstance(payload, dict):
            self._send_json({"error": "invalid_json"}, 400)
            return
        try:
            self._dispatch_post(parsed, payload)
        except store.InvalidContactName as e:
            self._send_json({"status": "error", "message": str(e)}, 400)

    def _dispatch_post(self, parsed, payload: dict):
        if parsed.path == "/api/target":
            if not payload.get("target"):
                self._send_json({"error": "missing_target"}, 400)
                return
            target = service_instance.set_target(payload["target"])
            self._send_json({"status": "updated", "target": target})

        elif parsed.path == "/api/trigger":
            self._send_json(service_instance.capture_and_refresh(payload.get("target")))

        elif parsed.path == "/api/autoloop":
            enabled = payload.get("enabled", not service_instance.auto_loop_enabled)
            interval = payload.get("interval", 60)
            self._send_json(service_instance.set_auto_loop(enabled, interval))

        elif parsed.path == "/api/inject_options":
            options = payload.get("options", [])
            valid = (
                isinstance(options, list) and len(options) == 6 and
                all(isinstance(o, dict) and isinstance(o.get("reply_text"), str) for o in options)
            )
            if valid:
                service_instance.inject_options(options)
                self._send_json({"status": "success", "message": "已成功注入外部大模型生成的 6 档建议卡片"})
            else:
                self._send_json({
                    "error": "invalid_format",
                    "message": "需提供包含 6 个卡片对象的 options 数组 (每个对象包含 slot_id, sub_goal, reply_text)"
                }, 400)

        elif parsed.path == "/api/create_contact":
            res = service_instance.profiler.onboard_contact(
                payload.get("target_name", ""), payload.get("free_text", ""), payload.get("folder_path")
            )
            self._send_json(res)

        elif parsed.path == "/api/ingest_history":
            target = self._target_param(payload.get("target"))
            folder_path = (payload.get("folder_path") or "").strip()
            if not folder_path:
                self._send_json({"status": "error", "message": "请提供有效的聊天记录文件夹或文件路径"}, 400)
                return
            from ingestion.folder_scanner import MultiFormatFolderScanner
            msgs = MultiFormatFolderScanner(target).scan_path(os.path.expanduser(folder_path))
            if not msgs:
                self._send_json({"status": "error", "message": "未能从指定路径解析出有效聊天消息，请核验格式 (支持包含 index.csv 的导出目录、或单文件 CSV/JSON/TXT)"})
                return
            distill_res = service_instance.distiller.distill_history_stream(target, msgs)
            added = distill_res.get("episodes_added", 0)
            self._send_json({
                "status": "success",
                "target": target,
                "parsed_messages": len(msgs),
                "episodes_added": added,
                "message": f"成功为 {target} 增量解析 {len(msgs)} 条消息，沉淀 {added} 个事实故事流！"
            })

        elif parsed.path == "/api/ingest_knowledge":
            self._handle_ingest_knowledge(payload)

        elif parsed.path == "/api/quit":
            self._send_json({"status": "quitting"})
            def _shutdown():
                time.sleep(0.15)
                if service_instance.webview_window:
                    try:
                        service_instance.webview_window.destroy()
                    except Exception:
                        pass
                os._exit(0)
            threading.Thread(target=_shutdown, daemon=True).start()

        elif parsed.path == "/api/window/resize":
            mode = payload.get("mode", "expanded")
            window = service_instance.webview_window
            if window:
                try:
                    if mode == "capsule":
                        window.resize(config.WINDOW_CAPSULE_WIDTH, config.WINDOW_CAPSULE_HEIGHT)
                    elif mode == "custom" and payload.get("width") and payload.get("height"):
                        w = min(max(int(payload["width"]), 120), 1600)
                        h = min(max(int(payload["height"]), 30), 1600)
                        window.resize(w, h)
                    else:
                        window.resize(config.WINDOW_EXPANDED_WIDTH, config.WINDOW_EXPANDED_HEIGHT)
                except (TypeError, ValueError) as e:
                    logger.error("[Resize Error] %s", e)
            self._send_json({"status": "resized", "mode": mode})

        else:
            self._send_json({"error": "not_found"}, 404)

    def _handle_ingest_knowledge(self, payload: dict):
        text = (payload.get("text") or "").strip()
        source_title = (payload.get("source_title") or "").strip()
        file_path = os.path.expanduser((payload.get("file_path") or "").strip())
        if file_path:
            # 仅允许读取文本类文档，且限制大小 (内容会发送给大模型提炼)
            if not os.path.isfile(file_path) or not file_path.lower().endswith(KNOWLEDGE_FILE_EXTS):
                self._send_json({"status": "error", "message": f"仅支持导入 {' / '.join(KNOWLEDGE_FILE_EXTS)} 文本文件"}, 400)
                return
            if os.path.getsize(file_path) > MAX_KNOWLEDGE_FILE_BYTES:
                self._send_json({"status": "error", "message": "文件超过 1MB，请拆分后再导入"}, 400)
                return
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                source_title = source_title or os.path.basename(file_path)
            except OSError as e:
                self._send_json({"status": "error", "message": f"读取文件失败: {e}"}, 400)
                return
        from ingestion.knowledge_ingester import distill_knowledge_to_playbook
        res = distill_knowledge_to_playbook(text, source_title)
        if res.get("status") == "success":
            service_instance.generator.knowledge_retriever._load_playbooks()
        self._send_json(res)

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return
