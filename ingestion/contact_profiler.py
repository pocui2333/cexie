import os
import json
from typing import Dict, Any, Optional
from core import store
from ingestion.folder_scanner import MultiFormatFolderScanner
from ingestion.episodic_distiller import EpisodicDistiller

class ContactProfiler:
    """
    纯填空自然语言建档引擎:
    - 废除所有死板预设单选项
    - 用户自由输入任何对该人的描述与想怎么聊
    - 自动提取偏好、规则并初始化 contacts/{微信备注}/ 独立物理沙盒
    """
    def __init__(self, contacts_dir: str):
        self.contacts_dir = contacts_dir

    def onboard_contact(self, target_name: str, free_text: str, history_folder: Optional[str] = None) -> Dict[str, Any]:
        try:
            target_name = store.validate_contact_name(target_name)
            sandbox_dir = store.contact_dir(target_name, self.contacts_dir)
        except store.InvalidContactName as e:
            return {"status": "error", "message": str(e)}
        free_text = free_text or ""
        os.makedirs(sandbox_dir, exist_ok=True)

        # 1. 生成 rules.json
        rules_path = os.path.join(sandbox_dir, "rules.json")
        if not os.path.exists(rules_path) or free_text.strip():
            rules = self._synthesize_rules(target_name, free_text)
            with open(rules_path, "w", encoding="utf-8") as f:
                json.dump(rules, f, ensure_ascii=False, indent=2)

        # 2. 生成 dossier.md
        dossier_path = os.path.join(sandbox_dir, "dossier.md")
        if not os.path.exists(dossier_path) or free_text.strip():
            dossier_content = self._synthesize_dossier(target_name, free_text)
            with open(dossier_path, "w", encoding="utf-8") as f:
                f.write(dossier_content)

        # 3. 初始化 episodes.md
        episodes_path = os.path.join(sandbox_dir, "episodes.md")
        if not os.path.exists(episodes_path):
            with open(episodes_path, "w", encoding="utf-8") as f:
                f.write(f"# {target_name} 历史事实故事流\n\n")

        # 4. 初始化 index.db
        store.ensure_schema(os.path.join(sandbox_dir, "index.db"))

        # 5. 若指定了历史记录文件夹/文件，自动扫描并批量脱水蒸馏
        ingest_summary = None
        if history_folder and (os.path.isdir(history_folder) or os.path.isfile(history_folder)):
            scanner = MultiFormatFolderScanner(target_name)
            messages = scanner.scan_path(history_folder)
            if messages:
                distiller = EpisodicDistiller(self.contacts_dir)
                distill_res = distiller.distill_history_stream(target_name, messages)
                ingest_summary = {
                    "parsed_messages": len(messages),
                    "episodes_added": distill_res.get("episodes_added", 0),
                    "total_sessions": distill_res.get("total_sessions", 0)
                }
            else:
                ingest_summary = {
                    "parsed_messages": 0,
                    "episodes_added": 0
                }

        return {
            "status": "success",
            "target_name": target_name,
            "sandbox_dir": sandbox_dir,
            "ingest_summary": ingest_summary
        }

    def _synthesize_rules(self, target_name: str, description: str) -> Dict[str, Any]:
        # 根据描述自适应分析理想句长与语气关键词
        ideal_len = 14
        if "短句" in description or "松弛" in description:
            ideal_len = 10
        elif "长句" in description or "详细" in description:
            ideal_len = 22

        banned_phrases = ["在吗", "亲爱的", "辛苦了", "多喝热水"]
        if "别客套" in description or "不用客气" in description:
            banned_phrases.extend(["您好", "麻烦您", "请问", "好的收到"])

        return {
            "target_name": target_name,
            "sentence_length": {
                "min": max(6, ideal_len - 6),
                "max": ideal_len + 10,
                "ideal": ideal_len
            },
            # 标点 / 表情 / 语气等说话习惯默认继承全局 data/ego/rules.json，这里不预设
            "banned_phrases": banned_phrases
        }

    def _synthesize_dossier(self, target_name: str, description: str) -> str:
        desc_text = description.strip() if description.strip() else "初次建档，边聊边学"
        return f"""# 人物小传：{target_name}

> **阵营**：核心交互目标  
> **档案建立方式**：纯填空自由建档  
> **初始背景描述**：{desc_text}

---

## 一、 人物本质底色与沟通基调
根据用户填空描述自动初始化，后续聊天中逐步补充。

## 二、 核心生活圈与关键关联实体
暂无关联实体，系统将在后续聊天脱水归档时自动捕获并建立索引。

## 三、 终身大事记
- 初始档案创建于系统启动期
"""
