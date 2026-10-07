"""
微信导出历史记录通用脱水归档执行脚本 (Generic WeChat Export Ingestion CLI)

功能:
- 从指定微信导出根目录或联系人子目录智能解析对话记录 (CSV / JSON / TXT)
- 过滤群聊 (@chatroom)、企微营销号 (@openim)、系统公众号及本人账号
- 过滤少于指定句数（默认 > 50 句）的非深度联系人
- 按时间段与沉默间隔切片为离散对话情境 (Episodes)
- 提取涉及实体、核心事实、关系动态，录入联系人沙盒 (episodes.md 与 SQLite 倒排索引)
- 纯动态提炼，绝不硬编码任何私人信息或固定代码逻辑
"""
import os
import sys
import argparse
import csv

# 确保项目根目录在 sys.path 中
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import config
from ingestion.folder_scanner import MultiFormatFolderScanner
from ingestion.episodic_distiller import EpisodicDistiller
from ingestion.contact_profiler import ContactProfiler

def ingest_contact(export_dir: str, target_name: str, contacts_dir: str, chat_sub_dir: str = None, max_episodes: int = None):
    print(f"\n==========================================")
    print(f"[*] 开始处理联系人: {target_name}")
    print(f"[*] 导出数据路径: {export_dir}")
    print(f"[*] 沙盒存储目录: {contacts_dir}/{target_name}")
    print(f"==========================================")

    profiler = ContactProfiler(contacts_dir)
    sandbox_dir = os.path.join(contacts_dir, target_name)
    if not os.path.exists(sandbox_dir):
        print(f"[*] 正在为「{target_name}」自动初始化基础沙盒...")
        profiler.onboard_contact(target_name, f"微信联系人 {target_name}")

    scanner = MultiFormatFolderScanner(target_name)
    if chat_sub_dir:
        resolved_path = os.path.join(export_dir, "chats", chat_sub_dir)
    else:
        resolved_path = scanner._resolve_target_dir(export_dir)

    print(f"[*] 解析到目标聊天记录目录: {resolved_path}")

    msgs = scanner.scan_path(resolved_path)
    print(f"[*] 成功扫描并解析出 {len(msgs)} 条有效对话消息")
    if not msgs:
        print(f"[-] 未在对应目录下找到有效消息，跳过蒸馏。")
        return

    print(f"[*] 消息起止时间: {msgs[0].timestamp} ~ {msgs[-1].timestamp}")
    print(f"[*] 正在进行情境切片与语义事实脱水归档...")

    distiller = EpisodicDistiller(contacts_dir)
    res = distiller.distill_history_stream(
        target_name=target_name,
        messages=msgs,
        session_gap_seconds=7200,
        max_episodes=max_episodes
    )

    print(f"[+] 蒸馏归档完成:")
    print(f"    - 总分析消息数: {res.get('total_messages', 0)}")
    print(f"    - 识别会话切片数: {res.get('total_sessions', 0)}")
    print(f"    - 新增录入事实事件: {res.get('episodes_added', 0)}")
    print(f"    - 档案位置: {sandbox_dir}/episodes.md")
    print(f"    - 索引数据库: {sandbox_dir}/index.db")

def list_export_contacts(export_dir: str, min_messages: int = 50, exclude_targets: list = None):
    index_csv = os.path.join(export_dir, "index.csv")
    if not os.path.isfile(index_csv):
        print(f"[-] 未在 {export_dir} 下找到 index.csv 索引文件")
        return []

    exclude_set = set(exclude_targets or [])
    contacts = []
    with open(index_csv, "r", encoding="utf-8-sig", errors="ignore") as f:
        reader = csv.DictReader(f)
        for r in reader:
            username = r.get("用户名", "").strip()
            disp = r.get("显示名", "").strip()
            msg_count = r.get("消息数", "0").strip()
            dir_name = r.get("目录", "").strip()
            count = int(msg_count) if msg_count.isdigit() else 0

            # 过滤群聊、企微客服/游戏推送、系统功能账号
            if "@chatroom" in username or "@openim" in username or username.startswith("gh_"):
                continue
            if disp in ("微信团队", "文件传输助手", "QQ邮箱提醒"):
                continue
            if disp in exclude_set or username in exclude_set:
                continue

            # 过滤消息数 <= 阈值的浅层联系人
            if count <= min_messages:
                continue

            contacts.append({
                "name": disp,
                "username": username,
                "count": count,
                "dir": dir_name
            })
    return contacts

def main():
    parser = argparse.ArgumentParser(description="微信导出记录批量脱水蒸馏工具")
    parser.add_argument("--export_dir", default="/Users/mac/微信导出", help="微信导出根目录路径")
    parser.add_argument("--target", default="all", help="要处理的目标联系人备注名 (默认 'all' 处理全部符合条件的单聊联系人)")
    parser.add_argument("--contacts_dir", default=config.CONTACTS_DIR, help="联系人沙盒根目录")
    parser.add_argument("--min_messages", type=int, default=50, help="最小消息数过滤门槛 (默认 50)")
    parser.add_argument("--max_episodes", type=int, default=None, help="最大处理事件数 (默认全部)")
    parser.add_argument("--exclude", default="", help="可选：动态排除特定联系人备注，以逗号分隔 (如: --exclude '张三,李四')")
    parser.add_argument("--list", action="store_true", help="列出导出数据中的所有符合条件的单聊联系人")

    args = parser.parse_args()

    exclude_targets = [x.strip() for x in args.exclude.split(",") if x.strip()]
    contacts = list_export_contacts(args.export_dir, min_messages=args.min_messages, exclude_targets=exclude_targets)

    if args.list:
        print(f"共发现 {len(contacts)} 位单聊有效联系人 (消息数 > {args.min_messages}):")
        for idx, c in enumerate(contacts, 1):
            print(f"  {idx:2d}. {c['name']:<15} (消息数: {c['count']:>6}) -> {c['dir']}")
        return

    if args.target.lower() == "all":
        print(f"准备全量处理 {len(contacts)} 位单聊有效联系人 (已过滤群聊与 <= {args.min_messages} 句联系人)...")
        for idx, c in enumerate(contacts, 1):
            print(f"\n[{idx}/{len(contacts)}] 处理: {c['name']} (消息数: {c['count']})")
            ingest_contact(
                export_dir=args.export_dir,
                target_name=c["name"],
                contacts_dir=args.contacts_dir,
                chat_sub_dir=c["dir"],
                max_episodes=args.max_episodes
            )
    else:
        # 单独处理某个联系人
        matched = [c for c in contacts if c["name"] == args.target]
        chat_sub_dir = matched[0]["dir"] if matched else None
        ingest_contact(
            export_dir=args.export_dir,
            target_name=args.target,
            contacts_dir=args.contacts_dir,
            chat_sub_dir=chat_sub_dir,
            max_episodes=args.max_episodes
        )

if __name__ == "__main__":
    main()
