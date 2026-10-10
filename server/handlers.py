"""
HTTP Handler for EchoLens HUD frontend.
Dispatches REST APIs and serves static UI assets.
"""
import os
import json
import time
import threading
from urllib.parse import urlparse, parse_qs
from http.server import SimpleHTTPRequestHandler
import config
from server.service import service_instance, get_macos_clipboard, get_default_target
from capture import capture_chat_snapshot, is_contact_match

class EchoLensHTTPHandler(SimpleHTTPRequestHandler):
    _trigger_lock = threading.Lock()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=config.HUD_DIR, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/contacts":
            contacts = []
            if os.path.exists(config.CONTACTS_DIR):
                contacts = [
                    d for d in os.listdir(config.CONTACTS_DIR)
                    if os.path.isdir(os.path.join(config.CONTACTS_DIR, d)) and not d.startswith('.')
                ]
            active = service_instance.state_machine.active_target or get_default_target()
            self._send_json({
                "contacts": contacts or [get_default_target()],
                "active_target": active
            })

        elif parsed.path == "/api/poll":
            self._send_json({
                "state": service_instance.state_machine.state,
                "target": service_instance.state_machine.active_target,
                "timer": service_instance.state_machine.get_duration_str(),
                "incoming_text": service_instance.current_incoming,
                "ego_text": service_instance.current_ego_reply,
                "reply_status": service_instance.current_reply_status,
                "sender_name": service_instance.state_machine.last_sender_name,
                "message_time": service_instance.state_machine.last_incoming_time_str,
                "options": service_instance.cached_options,
                "insight": service_instance.cached_insight,
                "stats": service_instance.get_stats(),
                "auto_loop_enabled": service_instance.auto_loop_enabled,
                "auto_loop_countdown": service_instance.auto_loop_countdown
            })

        elif parsed.path == "/api/profile":
            qs = parse_qs(parsed.query)
            target = qs.get("target", [service_instance.state_machine.active_target or get_default_target()])[0]
            target_dir = os.path.join(config.CONTACTS_DIR, target)
            dossier_text = ""
            episodes_text = ""
            rules_obj = {}
            if os.path.exists(target_dir):
                dossier_path = os.path.join(target_dir, "dossier.md")
                episodes_path = os.path.join(target_dir, "episodes.md")
                rules_path = os.path.join(target_dir, "rules.json")
                if os.path.exists(dossier_path):
                    with open(dossier_path, "r", encoding="utf-8") as f:
                        dossier_text = f.read()
                if os.path.exists(episodes_path):
                    with open(episodes_path, "r", encoding="utf-8") as f:
                        episodes_text = f.read()
                if os.path.exists(rules_path):
                    try:
                        with open(rules_path, "r", encoding="utf-8") as f:
                            rules_obj = json.load(f)
                    except Exception:
                        pass
            self._send_json({
                "target": target,
                "dossier": dossier_text,
                "episodes": episodes_text,
                "rules": rules_obj
            })
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(length) if length > 0 else b'{}'
        payload = {}
        try:
            payload = json.loads(post_data.decode('utf-8'))
        except Exception:
            pass

        if parsed.path == "/api/target":
            target = payload.get("target")
            if target:
                service_instance.state_machine.active_target = target
                service_instance.manual_target_locked = True
                service_instance._refresh_options(target, service_instance.current_incoming)
                self._send_json({"status": "updated", "target": target})
            else:
                self._send_json({"error": "missing_target"}, 400)

        elif parsed.path == "/api/start":
            target = payload.get("target", get_default_target())
            res = service_instance.state_machine.start_monitoring(target, service_instance.probe_catchup)
            self._send_json(res)

        elif parsed.path == "/api/stop":
            res = service_instance.state_machine.stop_and_archive()
            self._send_json(res)

        elif parsed.path == "/api/outgoing":
            text = payload.get("text", "")
            service_instance.last_outgoing_reply = text
            service_instance.state_machine.feed_outgoing_reply(text)
            self._send_json({"status": "recorded"})

        elif parsed.path == "/api/trigger":
            self._handle_trigger(payload)

        elif parsed.path == "/api/autoloop":
            enabled = payload.get("enabled", not service_instance.auto_loop_enabled)
            interval = payload.get("interval", 60)
            res = service_instance.set_auto_loop(enabled, interval)
            self._send_json(res)

        elif parsed.path == "/api/inject_options":
            options = payload.get("options", [])
            if isinstance(options, list) and len(options) == 6:
                service_instance.cached_options = options
                self._send_json({"status": "success", "message": "已成功注入外部大模型生成的 6 档建议卡片"})
            else:
                self._send_json({
                    "error": "invalid_format",
                    "message": "需提供包含 6 个卡片对象的 options 数组 (每个对象包含 slot_id, sub_goal, reply_text)"
                }, 400)

        elif parsed.path == "/api/create_contact":
            target_name = payload.get("target_name", "")
            free_text = payload.get("free_text", "")
            folder_path = payload.get("folder_path", None)
            res = service_instance.profiler.onboard_contact(target_name, free_text, folder_path)
            self._send_json(res)

        elif parsed.path == "/api/ingest_history":
            target = payload.get("target") or service_instance.state_machine.active_target or get_default_target()
            folder_path = payload.get("folder_path") or "/Users/mac/微信导出"
            from ingestion.folder_scanner import MultiFormatFolderScanner
            scanner = MultiFormatFolderScanner(target)
            msgs = scanner.scan_path(folder_path)
            distill_res = service_instance.distiller.distill_history_stream(target, msgs)
            self._send_json(distill_res)

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
            custom_w = payload.get("width")
            custom_h = payload.get("height")
            if service_instance.webview_window:
                try:
                    if mode == "capsule":
                        service_instance.webview_window.resize(config.WINDOW_CAPSULE_WIDTH, config.WINDOW_CAPSULE_HEIGHT)
                    elif mode == "custom" and custom_w and custom_h:
                        service_instance.webview_window.resize(int(custom_w), int(custom_h))
                    else:
                        service_instance.webview_window.resize(config.WINDOW_EXPANDED_WIDTH, config.WINDOW_EXPANDED_HEIGHT)
                except Exception as e:
                    print(f"[Resize Error] {e}")
            self._send_json({"status": "resized", "mode": mode})

        else:
            self._send_json({"error": "not_found"}, 404)

    def _handle_trigger(self, payload: dict):
        acquired = EchoLensHTTPHandler._trigger_lock.acquire(blocking=False)
        if not acquired:
            self._send_json({
                "status": "busy",
                "message": "上一轮抓取正在进行中，已自动节流防抖",
                "target": payload.get("target") or service_instance.state_machine.active_target or get_default_target(),
                "incoming_text": service_instance.current_incoming,
                "ego_text": service_instance.current_ego_reply,
                "reply_status": service_instance.current_reply_status,
                "options": service_instance.cached_options
            })
            return

        try:
            expected_target = payload.get("target") or service_instance.state_machine.active_target or get_default_target()
            snapshot = capture_chat_snapshot(expected_target=expected_target)

            # 核心防线：核对当前微信窗口与目标备注
            if snapshot.is_mismatch or (snapshot.contact_name and not is_contact_match(snapshot.contact_name, expected_target)):
                self._send_json({
                    "status": "mismatch",
                    "target": expected_target,
                    "detected": snapshot.contact_name or "未知窗口",
                    "incoming_text": service_instance.current_incoming,
                    "ego_text": service_instance.current_ego_reply,
                    "reply_status": service_instance.current_reply_status,
                    "options": service_instance.cached_options,
                    "message": f"当前微信窗口为「{snapshot.contact_name or '其他群聊/窗口'}」，与目标备注「{expected_target}」不一致！未执行抓取与记录。"
                })
                return

            target = expected_target

            # 1. 增量蒸馏与长期记忆录入 (按时间断点与哈希差量分别蒸馏双方事实)
            distill_res = service_instance.distiller.distill_turn_incremental(
                target,
                snapshot.raw_turns,
                time_hint=snapshot.time_hint
            )
            recorded = (distill_res.get("status") == "recorded")

            # 2. 将最新对话状态同步到服务层与 UI 展示看板
            service_instance.current_incoming = snapshot.incoming_text or service_instance.current_incoming
            service_instance.current_ego_reply = snapshot.ego_text or service_instance.current_ego_reply
            service_instance.current_reply_status = snapshot.reply_status
            service_instance.current_context = snapshot.dialogue_context

            if snapshot.case_type == 1:
                # 情况 1: 最后一条是我的回复 -> 标记为已回复，清空下方旧推荐选项
                service_instance.cached_options = []
                if not getattr(service_instance, "last_outgoing_time", None):
                    service_instance.last_outgoing_time = time.time()
                if snapshot.ego_text and snapshot.ego_text != "暂未回复":
                    service_instance.last_outgoing_reply = snapshot.ego_text
                    service_instance.state_machine.feed_outgoing_reply(snapshot.ego_text)

                msg_tip = "已抓取并沉淀记忆（当前已回复）" if recorded else "已同步最新对话（当前已回复）"
                self._send_json({
                    "status": "success",
                    "target": target,
                    "case_type": 1,
                    "recorded": recorded,
                    "distill_summary": distill_res,
                    "incoming_text": service_instance.current_incoming,
                    "ego_text": service_instance.current_ego_reply,
                    "reply_status": "replied",
                    "options": [],
                    "stats": service_instance.get_stats(target),
                    "message": msg_tip
                })

            else:
                # 情况 2: 最后一条不是我的回复（对方有新消息待回复）
                # 带着上下文去命中记录知识库，生成最新的 6 档自然回复推荐！
                service_instance.last_outgoing_time = None
                service_instance.state_machine.feed_incoming_message(target, service_instance.current_incoming)
                service_instance._refresh_options(target, service_instance.current_incoming, snapshot.dialogue_context)

                msg_tip = "已抓取并沉淀记忆，已生成最新推荐" if recorded else "已捕获对方新消息并生成最新推荐"
                self._send_json({
                    "status": "success",
                    "target": target,
                    "case_type": 2,
                    "recorded": recorded,
                    "distill_summary": distill_res,
                    "incoming_text": service_instance.current_incoming,
                    "ego_text": service_instance.current_ego_reply,
                    "reply_status": "pending",
                    "options": service_instance.cached_options,
                    "stats": service_instance.get_stats(target),
                    "message": msg_tip
                })
        finally:
            EchoLensHTTPHandler._trigger_lock.release()


    def _send_json(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def log_message(self, format, *args):
        return
