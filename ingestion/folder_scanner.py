import os
import re
import csv
import json
import hashlib
from datetime import datetime
from typing import List, Set
from core.contracts import ChatMessage

class MultiFormatFolderScanner:
    """
    文件夹智能扫描器:
    - 递归遍历用户拖入的任意历史目录
    - 自动识别并解析 CSV / TXT / JSON 格式
    - 基于 MD5 指纹精确剔除跨文件重复消息
    """
    def __init__(self, target_name: str, ego_aliases: List[str] = None):
        self.target_name = target_name
        self.ego_aliases: Set[str] = set(ego_aliases or ["我", "小破崔"])
        self.seen_signatures: Set[str] = set()

    def _resolve_target_dir(self, folder_path: str) -> str:
        """
        若用户传入的是微信导出的根目录（包含 index.csv 和 chats/），
        自动根据 target_name 映射到具体的 chats/<子目录>。
        """
        index_csv = os.path.join(folder_path, "index.csv")
        chats_dir = os.path.join(folder_path, "chats")
        if os.path.isfile(index_csv) and os.path.isdir(chats_dir):
            try:
                with open(index_csv, "r", encoding="utf-8-sig", errors="ignore") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        disp_name = row.get("显示名", "").strip()
                        user_name = row.get("用户名", "").strip()
                        sub_dir = row.get("目录", "").strip()
                        if self.target_name in (disp_name, user_name, sub_dir):
                            candidate = os.path.join(chats_dir, sub_dir)
                            if os.path.isdir(candidate):
                                return candidate
            except Exception:
                pass
            candidate = os.path.join(chats_dir, self.target_name)
            if os.path.isdir(candidate):
                return candidate
        return folder_path

    def scan_path(self, path: str) -> List[ChatMessage]:
        if os.path.isfile(path):
            file_lower = path.lower()
            if file_lower.endswith(".csv"):
                msgs = self._parse_csv(path)
            elif file_lower.endswith(".json"):
                msgs = self._parse_json(path)
            elif file_lower.endswith(".txt"):
                msgs = self._parse_txt(path)
            else:
                msgs = []
            msgs.sort(key=lambda m: m.timestamp)
            return self._deduplicate(msgs)
        return self.scan_folder(path)

    def scan_folder(self, folder_path: str) -> List[ChatMessage]:
        messages: List[ChatMessage] = []
        if not os.path.isdir(folder_path):
            return messages

        actual_path = self._resolve_target_dir(folder_path)
        for root, _, files in os.walk(actual_path):
            csv_files = [f for f in files if f.lower().endswith(".csv")]
            json_files = [f for f in files if f.lower().endswith(".json")]
            txt_files = [f for f in files if f.lower().endswith(".txt")]

            # 优先级：若同目录下已有 CSV，优先解析 CSV，避免同时解析 JSON/TXT 造成三倍冗余与内存膨胀
            if csv_files:
                for f in sorted(csv_files):
                    messages.extend(self._parse_csv(os.path.join(root, f)))
            elif json_files:
                for f in sorted(json_files):
                    messages.extend(self._parse_json(os.path.join(root, f)))
            elif txt_files:
                for f in sorted(txt_files):
                    messages.extend(self._parse_txt(os.path.join(root, f)))

        messages.sort(key=lambda m: m.timestamp)
        return self._deduplicate(messages)

    def _parse_csv(self, path: str) -> List[ChatMessage]:
        parsed = []
        try:
            with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sender = (
                        row.get("发送者") or row.get("Sender") or row.get("sender") or
                        row.get("NickName") or row.get("from") or ""
                    ).strip()
                    text = (
                        row.get("内容") or row.get("Message") or row.get("content") or
                        row.get("StrContent") or row.get("msg") or row.get("text") or ""
                    ).strip()
                    time_str = (
                        row.get("时间") or row.get("Date") or row.get("time") or
                        row.get("CreateTime") or row.get("timestamp") or ""
                    ).strip()
                    msg_type = (row.get("类型") or row.get("type") or "").strip()
                    sender_wxid = (row.get("发送者wxid") or "").strip()

                    if not text or not time_str:
                        continue
                    if sender in ("系统", "微信团队") or msg_type in ("系统提示", "系统通知", "拍一拍"):
                        continue
                    if "撤回了一条消息" in text:
                        continue

                    ts = self._parse_datetime(time_str)
                    role = "me" if (sender in self.ego_aliases or sender_wxid == "wxid_hcdcnzt1pp2o22") else "target"
                    parsed.append(ChatMessage(
                        sender_name=sender,
                        role=role,
                        content=text,
                        timestamp=ts
                    ))
        except Exception:
            pass
        return parsed

    def _parse_txt(self, path: str) -> List[ChatMessage]:
        parsed = []
        time_pattern = re.compile(r"^(\d{4}[-/]\d{2}[-/]\d{2}\s+\d{2}:\d{2}:\d{2})\s+([^:\n]+)[:：](.*)$")
        try:
            with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                current_msg = None
                for line in f:
                    match = time_pattern.match(line)
                    if match:
                        if current_msg:
                            parsed.append(current_msg)
                        ts_str, sender, content = match.groups()
                        sender = sender.strip()
                        content = content.strip()
                        if sender in ("系统", "微信团队") or "撤回了一条消息" in content:
                            current_msg = None
                            continue
                        role = "me" if sender in self.ego_aliases else "target"
                        current_msg = ChatMessage(
                            sender_name=sender,
                            role=role,
                            content=content,
                            timestamp=self._parse_datetime(ts_str)
                        )
                    else:
                        if current_msg and line.strip():
                            current_msg.content += "\n" + line.strip()
                if current_msg:
                    parsed.append(current_msg)
        except Exception:
            pass
        return parsed

    def _parse_json(self, path: str) -> List[ChatMessage]:
        parsed = []
        try:
            with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        sender = str(item.get("sender") or item.get("发送者") or item.get("from") or item.get("NickName") or "").strip()
                        text = str(item.get("content") or item.get("内容") or item.get("msg") or item.get("Message") or "").strip()
                        time_str = str(item.get("time") or item.get("时间") or item.get("timestamp") or item.get("CreateTime") or "").strip()
                        msg_type = str(item.get("type_name") or item.get("类型") or "").strip()
                        sender_wxid = str(item.get("sender_wxid") or item.get("发送者wxid") or "").strip()
                        is_self = item.get("is_self", False)

                        if not text or not time_str:
                            continue
                        if sender in ("系统", "微信团队") or msg_type in ("系统提示", "系统通知", "拍一拍"):
                            continue
                        if "撤回了一条消息" in text:
                            continue

                        role = "me" if (is_self or sender in self.ego_aliases or sender_wxid == "wxid_hcdcnzt1pp2o22") else "target"
                        parsed.append(ChatMessage(
                            sender_name=sender,
                            role=role,
                            content=text,
                            timestamp=self._parse_datetime(time_str)
                        ))
        except Exception:
            pass
        return parsed

    def _deduplicate(self, messages: List[ChatMessage]) -> List[ChatMessage]:
        unique = []
        for m in messages:
            sig = hashlib.md5(f"{m.timestamp.isoformat()}_{m.role}_{m.content}".encode()).hexdigest()
            if sig not in self.seen_signatures:
                self.seen_signatures.add(sig)
                unique.append(m)
        return unique

    def _parse_datetime(self, val: str) -> datetime:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                pass
        try:
            return datetime.fromtimestamp(float(val))
        except Exception:
            return datetime.now()
