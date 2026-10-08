# EchoLens (语镜) 工程实现技术规范 (Engineering Specification)

> **版本**：v2.0.0 (Engineering & Implementation Spec)  
> **项目定位**：面向 macOS 微信的微感双轨言语孪生镜像系统  
> **数据哲学**：单目标沙盒物理隔离 + 实体关联记忆网络 (Chatless) + 纯鼠标驱动极简透明 HUD + 双轨渐进进化  
> **规范目标**：定义工程目录结构、数据契约、字段规范、SQLite DDL 及全量核心伪代码

---

## 一、 全局工程文件树规范 (Directory & File Tree)

彻底重构以往混乱耦合的临时脚本，建立清晰的分层命名体系：

```text
echolens/
├── README.md                      # 项目愿景与架构精要
├── app.py                         # 桌面应用统一启动入口 (兼本地 API 服务)
├── config.py                      # 全局常量、路径配置与 LLM 运行时参数
├── core/                          # 核心业务与双核决策引擎
│   ├── __init__.py
│   ├── contracts.py               # 数据契约与数据模型定义 (Pydantic / Dataclasses)
│   ├── state_machine.py           # 单目标状态机 (待机/监控/30分超时/启动即回溯)
│   ├── memory.py                  # 实体关联记忆与情境检索器
│   └── generator.py               # 双轨 2x3 矩阵生成器 (本真表达 vs 进阶微调)
├── ingestion/                     # 数据摄取与档案建档管道
│   ├── __init__.py
│   ├── folder_scanner.py          # 文件夹递归扫描与多格式解析 (CSV/TXT/JSON)
│   ├── timeline_aligner.py        # 全局时序对齐与高精度去重
│   ├── contact_profiler.py        # 纯填空自由建档与 AI 全息画像提取
│   └── episodic_distiller.py      # 会话切片与情境事实脱水 (Chatless 架构)
├── knowledge/                     # 战术策略库 (完全解耦挂载)
│   ├── emotional/                 # 情绪价值库 (接纳、降压、温暖回应)
│   ├── dynamic/                   # 关系推进库 (校准、松弛感、自然邀约)
│   ├── boundary/                  # 边界与安全库 (理性拒绝、投入失衡判断)
│   └── tactics/                   # 单轮战术编排器 (巧妙接话、化解尴尬)
├── hud/                           # 纯 HTML/CSS/JS 极简半透明悬浮窗
│   ├── index.html                 # 双视图 HTML (A: 监控, B: 导入建档)
│   ├── style.css                  # 纯 CSS 深炭黑磨砂质感 (无 emoji, 无外挂字体)
│   └── app.js                     # 纯鼠标事件驱动 (Click-to-Copy, 折叠胶囊, 视图切换)
├── data/                          # 单目标物理沙盒库
│   ├── ego/                       # 【我】的全局本体
│   │   ├── profile.md             # 我方核心人格底色
│   │   └── rules.json             # 全局硬性语言防线 (逗号流、禁句号感叹号)
│   └── contacts/                  # 独立联系人沙盒
│       └── 示例好友/
│           ├── dossier.md         # 小传与关联实体图谱
│           ├── episodes.md        # 脱水情境事实流 (Chatless)
│           ├── rules.json         # 专属量化偏好与表情契约
│           └── index.db           # 极轻量 SQLite 实体索引
└── docs/                          # 系统架构与工程规范
    ├── MASTER_SYSTEM_DESIGN.md    # 顶层系统架构白皮书
    └── ENGINEERING_SPEC.md        # 完整工程实现规范 (字段定义、DDL、全量伪代码)
```

---

## 二、 数据契约与字段规范 (Data Contracts & Schemas)

### 1. 交互偏好与硬性防线契约 (`data/contacts/{微信备注}/rules.json`)
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ContactRules",
  "type": "object",
  "properties": {
    "target_name": {
      "type": "string",
      "description": "微信备注名，沙盒顶层目录标识"
    },
    "sentence_length": {
      "type": "object",
      "properties": {
        "min": { "type": "integer", "default": 8 },
        "max": { "type": "integer", "default": 25 },
        "ideal": { "type": "integer", "default": 16 }
      },
      "required": ["min", "max", "ideal"]
    },
    "cadence": {
      "type": "string",
      "enum": ["comma_separated_flow", "short_bursts", "multi_line"],
      "default": "comma_separated_flow",
      "description": "节奏模式，默认中文逗号断句"
    },
    "forbidden_punctuation": {
      "type": "array",
      "items": { "type": "string" },
      "default": ["。", "！", "!", "."],
      "description": "严禁出现的标点符号"
    },
    "forbidden_emojis": {
      "type": "array",
      "items": { "type": "string" },
      "default": ["[破涕为笑]", "[捂脸]"],
      "description": "严禁使用的微信表情"
    },
    "allowed_emojis": {
      "type": "array",
      "items": { "type": "string" },
      "default": ["[偷笑]"],
      "description": "允许使用的微信表情契约"
    },
    "banned_phrases": {
      "type": "array",
      "items": { "type": "string" },
      "description": "黑名单短语与油腻句式"
    },
    "tone_keywords": {
      "type": "array",
      "items": { "type": "string" },
      "description": "风格关键词，如冷幽默、定海神针、东北口语"
    }
  },
  "required": ["target_name", "sentence_length", "cadence", "forbidden_punctuation"]
}
```

### 2. 实体索引数据库表结构与 DDL (`data/contacts/{微信备注}/index.db`)
每个联系人目录配备独立极轻量 SQLite 索引数据库，不存储聊天原句，仅索引脱水事实：

```sql
-- 情境事件元数据表
CREATE TABLE IF NOT EXISTS episode_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_date TEXT NOT NULL,          -- 格式: YYYY-MM-DD
    theme TEXT NOT NULL,                 -- 情境主题摘要
    entities_blob TEXT NOT NULL,         -- 关联实体关键词列表，逗号分隔，例如: "老李,户外徒步,金毛犬"
    facts_summary TEXT NOT NULL,         -- 提炼出的核心事实描述 (JSON 字符串或纯文本)
    relationship_dynamic TEXT,          -- 关系动态演变
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 实体关键词快查倒排索引表
CREATE TABLE IF NOT EXISTS entity_inverted_index (
    entity_name TEXT NOT NULL,           -- 实体词 (如: "老李", "小刘", "阿黄")
    episode_id INTEGER NOT NULL,         -- 对应 episode_records 的主键 ID
    weight REAL DEFAULT 1.0,             -- 关联权重
    PRIMARY KEY (entity_name, episode_id),
    FOREIGN KEY (episode_id) REFERENCES episode_records(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_entity_name ON entity_inverted_index(entity_name);
CREATE INDEX IF NOT EXISTS idx_episode_date ON episode_records(episode_date);
CREATE INDEX IF NOT EXISTS idx_episode_theme ON episode_records(theme);
```

### 3. 数据契约定义 (`core/contracts.py`)
```python
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime

@dataclass
class ChatMessage:
    sender_name: str
    role: str                       # "me" | "target"
    content: str
    timestamp: datetime
    msg_type: str = "text"          # "text" | "system" | "image"

@dataclass
class ConversationWindow:
    target_name: str
    messages: List[ChatMessage]
    start_time: datetime
    end_time: datetime

@dataclass
class FactEpisode:
    episode_date: str
    theme: str
    entities: List[str]
    facts: List[str]
    relationship_dynamic: str

@dataclass
class GenerationOption:
    slot_id: int                    # 1 ~ 6
    track: str                      # "native" (1~3) | "evolved" (4~6)
    sub_goal: str                   # 如: "直球承接", "事实接话", "肯定+情绪回音"
    reply_text: str
    tactical_rationale: str

@dataclass
class DualTrackResult:
    target_name: str
    incoming_context: str
    options: List[GenerationOption]
    timestamp: datetime = field(default_factory=datetime.now)
```

---

## 三、 核心模块架构与完整伪代码 (Core Algorithms & Pseudocode)

### 1. 文件夹智能递归扫描与去重 (`ingestion/folder_scanner.py`)
```python
import os
import re
import csv
import json
import hashlib
from datetime import datetime
from typing import List, Generator
from core.contracts import ChatMessage

class MultiFormatFolderScanner:
    """
    负责遍历用户拖入的任意历史文件夹
    自动识别多格式、跨文件融合时序、MD5 严格去重
    """
    def __init__(self, target_name: str, ego_aliases: List[str] = None):
        self.target_name = target_name
        self.ego_aliases = set(ego_aliases or ["我", "自己"])
        self.seen_signatures = set()

    def scan_and_normalize(self, folder_path: str) -> List[ChatMessage]:
        raw_messages: List[ChatMessage] = []
        for root, _, files in os.walk(folder_path):
            for file in sorted(files):
                file_lower = file.lower()
                full_path = os.path.join(root, file)
                if file_lower.endswith(".csv"):
                    raw_messages.extend(self._parse_csv(full_path))
                elif file_lower.endswith(".txt"):
                    raw_messages.extend(self._parse_txt(full_path))
                elif file_lower.endswith(".json"):
                    raw_messages.extend(self._parse_json(full_path))

        # 按真实时间戳严格排序
        raw_messages.sort(key=lambda m: m.timestamp)
        return self._deduplicate(raw_messages)

    def _parse_csv(self, path: str) -> List[ChatMessage]:
        messages = []
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sender = row.get("Sender") or row.get("sender") or row.get("NickName") or ""
                text = row.get("Message") or row.get("content") or row.get("StrContent") or ""
                time_str = row.get("Date") or row.get("time") or row.get("CreateTime") or ""
                if not text or not time_str:
                    continue
                ts = self._parse_datetime(time_str)
                role = "me" if sender in self.ego_aliases else "target"
                messages.append(ChatMessage(sender_name=sender, role=role, content=text.strip(), timestamp=ts))
        return messages

    def _parse_txt(self, path: str) -> List[ChatMessage]:
        messages = []
        time_pattern = re.compile(r"^(\d{4}[-/]\d{2}[-/]\d{2}\s+\d{2}:\d{2}:\d{2})\s+([^:\n]+)[:：](.*)$")
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            current_msg = None
            for line in f:
                match = time_pattern.match(line)
                if match:
                    if current_msg:
                        messages.append(current_msg)
                    ts_str, sender, content = match.groups()
                    role = "me" if sender.strip() in self.ego_aliases else "target"
                    current_msg = ChatMessage(
                        sender_name=sender.strip(),
                        role=role,
                        content=content.strip(),
                        timestamp=self._parse_datetime(ts_str)
                    )
                else:
                    if current_msg and line.strip():
                        current_msg.content += "\n" + line.strip()
            if current_msg:
                messages.append(current_msg)
        return messages

    def _parse_json(self, path: str) -> List[ChatMessage]:
        messages = []
        with open(path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        sender = item.get("from") or item.get("sender", "")
                        text = item.get("msg") or item.get("content", "")
                        ts_str = item.get("time") or item.get("timestamp", "")
                        if text and ts_str:
                            role = "me" if sender in self.ego_aliases else "target"
                            messages.append(ChatMessage(
                                sender_name=sender,
                                role=role,
                                content=text,
                                timestamp=self._parse_datetime(str(ts_str))
                            ))
            except Exception:
                pass
        return messages

    def _deduplicate(self, messages: List[ChatMessage]) -> List[ChatMessage]:
        unique_list = []
        for m in messages:
            sig = hashlib.md5(f"{m.timestamp.isoformat()}_{m.role}_{m.content}".encode()).hexdigest()
            if sig not in self.seen_signatures:
                self.seen_signatures.add(sig)
                unique_list.append(m)
        return unique_list

    def _parse_datetime(self, time_val: str) -> datetime:
        # 支持常见标准格式与 UNIX 秒级时间戳
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(time_val, fmt)
            except ValueError:
                pass
        try:
            return datetime.fromtimestamp(float(time_val))
        except Exception:
            return datetime.now()
```

---

### 2. 纯填空自由建档与 AI 全息画像 (`ingestion/contact_profiler.py`)
```python
import os
import json
from typing import Dict, Any

class ContactProfiler:
    """
    负责解析用户在 UI 视图 B 填写的纯自然语言文本
    自动提取性格、沟通契约，初始化 contacts/{微信备注}/ 下的文件沙盒
    """
    def __init__(self, contacts_root: str):
        self.contacts_root = contacts_root

    def create_sandbox(self, target_name: str, free_text_description: str, llm_client=None) -> Dict[str, Any]:
        sandbox_dir = os.path.join(self.contacts_root, target_name)
        os.makedirs(sandbox_dir, exist_ok=True)

        # 1. 调用 LLM 提炼人物画像与专属量化偏好
        profile_data = self._llm_extract_profile(target_name, free_text_description, llm_client)

        # 2. 写入 rules.json
        rules_path = os.path.join(sandbox_dir, "rules.json")
        with open(rules_path, "w", encoding="utf-8") as f:
            json.dump(profile_data["rules"], f, ensure_ascii=False, indent=2)

        # 3. 初始化 dossier.md
        dossier_path = os.path.join(sandbox_dir, "dossier.md")
        with open(dossier_path, "w", encoding="utf-8") as f:
            f.write(profile_data["dossier_markdown"])

        # 4. 初始化空 episodes.md
        episodes_path = os.path.join(sandbox_dir, "episodes.md")
        if not os.path.exists(episodes_path):
            with open(episodes_path, "w", encoding="utf-8") as f:
                f.write(f"# {target_name} 历史事实故事流 (Chatless)\n\n")

        # 5. 初始化 SQLite index.db
        db_path = os.path.join(sandbox_dir, "index.db")
        self._init_sqlite(db_path)

        return {"status": "success", "sandbox_dir": sandbox_dir}

    def _llm_extract_profile(self, target_name: str, description: str, llm_client) -> Dict[str, Any]:
        # 默认离线兜底规则
        rules = {
            "target_name": target_name,
            "sentence_length": {"min": 8, "max": 24, "ideal": 15},
            "cadence": "comma_separated_flow",
            "forbidden_punctuation": ["。", "！", "!", "."],
            "forbidden_emojis": ["[破涕为笑]", "[捂脸]"],
            "allowed_emojis": ["[偷笑]"],
            "banned_phrases": ["在吗", "亲爱的", "辛苦了"],
            "tone_keywords": ["松弛", "幽默", "克制"]
        }
        dossier_md = f"""# 人物小传：{target_name}

> 阵营：交互目标对象  
> 建档描述：{description if description else '初次建档，边聊边学'}

## 一、 人物底色与沟通基调
根据用户自由描述建档，保持真实自然互动，遵循逗号流与无感回复。

## 二、 关键关联实体
暂无关联实体，随日常会话自动抽取记录。
"""
        return {"rules": rules, "dossier_markdown": dossier_md}

    def _init_sqlite(self, db_path: str):
        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS episode_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                episode_date TEXT NOT NULL,
                theme TEXT NOT NULL,
                entities_blob TEXT NOT NULL,
                facts_summary TEXT NOT NULL,
                relationship_dynamic TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entity_inverted_index (
                entity_name TEXT NOT NULL,
                episode_id INTEGER NOT NULL,
                weight REAL DEFAULT 1.0,
                PRIMARY KEY (entity_name, episode_id)
            );
        """)
        conn.commit()
        conn.close()
```

---

### 3. 单目标无感状态机与启动追溯补齐 (`core/state_machine.py`)
```python
import time
from enum import Enum
from typing import Optional, Callable
from core.contracts import ChatMessage

class CopilotState(Enum):
    IDLE = "待机中"
    MONITORING = "监控中"
    ARCHIVING = "归档中"

class SessionStateMachine:
    """
    单目标会话状态机:
    - 纯鼠标点击驱动: 开始监控 / 结束并归档
    - 启动即回溯: 点击开始瞬间追溯微信窗口内积压的历史未读气泡
    - 30分钟静默超时兜底自动归档
    """
    def __init__(self, target_name: str, on_archive_callback: Callable, timeout_seconds: int = 1800):
        self.target_name = target_name
        self.state = CopilotState.IDLE
        self.on_archive_callback = on_archive_callback
        self.timeout_seconds = timeout_seconds
        self.session_start_time: Optional[float] = None
        self.last_activity_time: Optional[float] = None
        self.active_buffer = []

    def start_monitoring(self, probe_catchup_func: Callable):
        self.state = CopilotState.MONITORING
        self.session_start_time = time.time()
        self.last_activity_time = self.session_start_time
        self.active_buffer.clear()
        
        # 启动即回溯: 立即探针拉取最新积压消息
        catchup_messages = probe_catchup_func(self.target_name)
        if catchup_messages:
            self.active_buffer.extend(catchup_messages)
            self.last_activity_time = time.time()

    def feed_message(self, message: ChatMessage):
        if self.state != CopilotState.MONITORING:
            return
        if message.sender_name != self.target_name and message.role != "me":
            return  # 严格单目标沙盒过滤
        self.active_buffer.append(message)
        self.last_activity_time = time.time()

    def check_timeout(self):
        if self.state == CopilotState.MONITORING and self.last_activity_time:
            if time.time() - self.last_activity_time > self.timeout_seconds:
                self.stop_and_archive()

    def stop_and_archive(self):
        if self.state == CopilotState.ARCHIVING:
            return
        self.state = CopilotState.ARCHIVING
        if self.active_buffer:
            self.on_archive_callback(self.target_name, self.active_buffer)
        self.active_buffer.clear()
        self.state = CopilotState.IDLE
        self.session_start_time = None
        self.last_activity_time = None
```

---

### 4. 双核决策与渐进进化推理引擎 (`core/generator.py`)
```python
import os
import re
import json
from typing import List, Dict
from core.contracts import GenerationOption, DualTrackResult

class DualTrackEngine:
    """
    双轨 6 选项生成器:
    - 左栏 3 条本真表达: 100% 忠实于当前语言习惯 (逗号流/冷幽默/保底)
    - 右栏 3 条进阶微调: 外接战术库 + 15% 沟通增量 (温度/关怀/埋钩子)
    """
    def __init__(self, ego_dir: str, contacts_root: str, knowledge_root: str):
        self.ego_dir = ego_dir
        self.contacts_root = contacts_root
        self.knowledge_root = knowledge_root

    def generate_options(self, target_name: str, incoming_text: str, context_facts: List[str]) -> DualTrackResult:
        contact_rules = self._load_rules(target_name)
        ego_profile = self._load_ego_profile()
        knowledge_snippets = self._retrieve_knowledge(incoming_text)

        # 组装 Prompt 调用大模型生成 2x3 矩阵
        # 此处展示标准化生成槽位逻辑
        options = [
            GenerationOption(slot_id=1, track="native", sub_goal="直球承接", 
                             reply_text=self._format_text("哈哈破案了，就说有暗锁", contact_rules),
                             tactical_rationale="直切关键事实，零客套"),
            GenerationOption(slot_id=2, track="native", sub_goal="事实接话", 
                             reply_text=self._format_text("这回可算能吹上风了", contact_rules),
                             tactical_rationale="自然顺应处境"),
            GenerationOption(slot_id=3, track="native", sub_goal="极简实用", 
                             reply_text=self._format_text("稍微开个小缝透气就行", contact_rules),
                             tactical_rationale="生活经验提醒"),
            GenerationOption(slot_id=4, track="evolved", sub_goal="肯定+情绪回音", 
                             reply_text=self._format_text("工程思维没白学，别吹着头[偷笑]", contact_rules),
                             tactical_rationale="增加肯定与关心，微调温度"),
            GenerationOption(slot_id=5, track="evolved", sub_goal="共鸣+脸蛋关心", 
                             reply_text=self._format_text("通上风舒服多了，脸蛋还热不", contact_rules),
                             tactical_rationale="细节回溯，提供安全舒适感"),
            GenerationOption(slot_id=6, track="evolved", sub_goal="幽默解救英雄", 
                             reply_text=self._format_text("全车人都得默默感谢你解救大家", contact_rules),
                             tactical_rationale="抬升价值，营造轻松社交共鸣")
        ]

        return DualTrackResult(
            target_name=target_name,
            incoming_context=incoming_text,
            options=options
        )

    def _format_text(self, text: str, rules: Dict) -> str:
        # 硬性防线过滤: 严禁句号感叹号，统一逗号流
        for p in rules.get("forbidden_punctuation", ["。", "！", "!", "."]):
            text = text.replace(p, " ")
        # 剔除违禁表情
        for emoji in rules.get("forbidden_emojis", []):
            text = text.replace(emoji, "")
        return text.strip()

    def _load_rules(self, target_name: str) -> Dict:
        path = os.path.join(self.contacts_root, target_name, "rules.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"forbidden_punctuation": ["。", "！", "!", "."], "forbidden_emojis": ["[破涕为笑]", "[捂脸]"]}

    def _load_ego_profile(self) -> str:
        path = os.path.join(self.ego_dir, "profile.md")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def _retrieve_knowledge(self, incoming_text: str) -> List[str]:
        # 扫描 knowledge 目录下匹配到的关键知识句段
        matched = []
        for root, _, files in os.walk(self.knowledge_root):
            for file in files:
                if file.endswith(".md"):
                    matched.append(file)
        return matched[:3]
```

---

### 5. 纯前端鼠标事件驱动引擎 (`hud/app.js`)
```javascript
/**
 * EchoLens HUD 前端状态控制器
 * 彻底废除键盘事件，100% 鼠标驱动
 */
class EchoLensApp {
    constructor() {
        this.currentView = 'monitor'; // 'monitor' | 'ingest'
        this.isCollapsed = false;
        this.activeTarget = '';
        this.status = '待机中';
        this.initDOMElements();
        this.bindEvents();
        this.pollServer();
    }

    initDOMElements() {
        this.viewMonitor = document.getElementById('view-monitor');
        this.viewIngest = document.getElementById('view-ingest');
        this.btnSwitchIngest = document.getElementById('btn-switch-ingest');
        this.btnSwitchMonitor = document.getElementById('btn-switch-monitor');
        this.btnFold = document.getElementById('btn-fold');
        this.btnExpand = document.getElementById('btn-expand');
        this.capsulePanel = document.getElementById('capsule-panel');
        this.mainContainer = document.getElementById('main-container');
        this.optionsGrid = document.getElementById('options-grid');
        this.targetSelect = document.getElementById('target-select');
        this.statusLabel = document.getElementById('status-label');
    }

    bindEvents() {
        // 1. 视图切换 (纯鼠标点击)
        this.btnSwitchIngest.addEventListener('click', () => this.switchView('ingest'));
        this.btnSwitchMonitor.addEventListener('click', () => this.switchView('monitor'));

        // 2. 窗口折叠与展开 (平滑收缩为 130x34px 小胶囊)
        this.btnFold.addEventListener('click', () => this.toggleCollapse(true));
        this.btnExpand.addEventListener('click', () => this.toggleCollapse(false));

        // 3. 卡片单击即复制 (Click-to-Copy)
        this.optionsGrid.addEventListener('click', (e) => {
            const card = e.target.closest('.option-card');
            if (!card) return;
            const textToCopy = card.getAttribute('data-reply');
            if (textToCopy) {
                navigator.clipboard.writeText(textToCopy).then(() => {
                    this.showCopyFeedback(card);
                });
            }
        });

        // 4. 文件夹拖拽上传建档 (视图 B)
        const dropZone = document.getElementById('folder-dropzone');
        if (dropZone) {
            dropZone.addEventListener('dragover', (e) => e.preventDefault());
            dropZone.addEventListener('drop', (e) => this.handleFolderDrop(e));
        }
    }

    switchView(viewName) {
        this.currentView = viewName;
        if (viewName === 'ingest') {
            this.viewMonitor.classList.add('hidden');
            this.viewIngest.classList.remove('hidden');
        } else {
            this.viewIngest.classList.add('hidden');
            this.viewMonitor.classList.remove('hidden');
        }
    }

    toggleCollapse(collapse) {
        this.isCollapsed = collapse;
        if (collapse) {
            this.mainContainer.classList.add('hidden');
            this.capsulePanel.classList.remove('hidden');
            // 调用原生后端收缩窗口尺寸为 130x34
            fetch('/api/window/resize?w=130&h=34');
        } else {
            this.capsulePanel.classList.add('hidden');
            this.mainContainer.classList.remove('hidden');
            // 恢复展开尺寸 340x580
            fetch('/api/window/resize?w=340&h=580');
        }
    }

    showCopyFeedback(cardElement) {
        cardElement.classList.add('copied-glow');
        const badge = cardElement.querySelector('.badge');
        const originalText = badge.textContent;
        badge.textContent = '已复制';
        setTimeout(() => {
            cardElement.classList.remove('copied-glow');
            badge.textContent = originalText;
        }, 800);
    }

    handleFolderDrop(e) {
        e.preventDefault();
        const items = e.dataTransfer.items;
        // 传递文件夹路径至后端 /api/ingest
    }

    pollServer() {
        setInterval(() => {
            if (this.currentView === 'monitor' && !this.isCollapsed) {
                fetch('/api/poll')
                    .then(res => res.json())
                    .then(data => this.renderMonitorState(data))
                    .catch(() => {});
            }
        }, 1000);
    }

    renderMonitorState(data) {
        if (!data || !data.options) return;
        // 渲染对方消息与 6 个选项卡片
    }
}

document.addEventListener('DOMContentLoaded', () => new EchoLensApp());
```

---

## 四、 关键性能与安全边界

1. **零进程侵入**：不 Hook 微信进程，不注入内存，仅通过 macOS 原生剪贴板或标准探针通讯
2. **纯鼠标交互防抢键**：彻底移除所有键盘事件监听，无论在 Xcode、VSCode 还是聊天窗口打字，绝对零冲突
3. **Chatless 物理安全**：聊天原始记录完成 Episode 萃取与特征归档后即时解耦粉碎，磁盘不长期留存敏感聊天原文
4. **轻量沙盒占用**：每个联系人仅占用数百 KB 的 Markdown 与 SQLite 文件，系统内存占用低于 45MB
