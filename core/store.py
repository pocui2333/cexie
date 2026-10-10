"""
联系人沙盒存储层 (ContactStore):
统一负责 data/contacts/{备注}/ 目录的路径校验、SQLite 连接与建表、以及写入互斥锁，
避免各模块各自拼路径 / 各自 connect / 重复维护建表语句。
"""
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator, List, Optional

import config

EXAMPLE_CONTACT = "示例好友"

# 所有对 episodes.md / index.db / checkpoint.json 的写入共用一把锁
# (手动抓取、自动循环、超时归档与历史导入可能并发执行)
write_lock = threading.RLock()

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS episode_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        episode_date TEXT NOT NULL,
        theme TEXT NOT NULL,
        entities_blob TEXT NOT NULL,
        facts_summary TEXT NOT NULL,
        relationship_dynamic TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS entity_inverted_index (
        entity_name TEXT NOT NULL,
        episode_id INTEGER NOT NULL,
        weight REAL DEFAULT 1.0,
        PRIMARY KEY (entity_name, episode_id)
    );
    """,
)


class InvalidContactName(ValueError):
    pass


def validate_contact_name(name: Optional[str]) -> str:
    """校验微信备注名可安全作为单级目录名（拒绝路径分隔符、隐藏目录与 .. 穿越）"""
    name = (name or "").strip()
    if not name or len(name) > 64:
        raise InvalidContactName("联系人备注名为空或过长")
    if name.startswith(".") or any(ch in name for ch in ("/", "\\", "\x00")):
        raise InvalidContactName(f"联系人备注名包含非法字符: {name!r}")
    return name


def contact_dir(name: str, contacts_dir: Optional[str] = None) -> str:
    base = os.path.realpath(contacts_dir or config.CONTACTS_DIR)
    path = os.path.realpath(os.path.join(base, validate_contact_name(name)))
    if os.path.dirname(path) != base:
        raise InvalidContactName(f"联系人路径越界: {name!r}")
    return path


def list_contacts(contacts_dir: Optional[str] = None) -> List[str]:
    base = contacts_dir or config.CONTACTS_DIR
    if not os.path.isdir(base):
        return []
    return sorted(
        d for d in os.listdir(base)
        if not d.startswith(".") and os.path.isdir(os.path.join(base, d))
    )


def db_path(name: str, contacts_dir: Optional[str] = None) -> str:
    return os.path.join(contact_dir(name, contacts_dir), "index.db")


def ensure_schema(path: str) -> None:
    conn = sqlite3.connect(path)
    try:
        for stmt in _SCHEMA:
            conn.execute(stmt)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def connect(name: str, contacts_dir: Optional[str] = None, create: bool = False) -> Iterator[Optional[sqlite3.Connection]]:
    """打开联系人 index.db；库不存在且 create=False 时产出 None，便于调用方静默跳过"""
    path = db_path(name, contacts_dir)
    if not os.path.exists(path):
        if not create:
            yield None
            return
        ensure_schema(path)
    conn = sqlite3.connect(path, timeout=5.0)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
