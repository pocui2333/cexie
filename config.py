import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
EGO_DIR = os.path.join(DATA_DIR, "ego")
CONTACTS_DIR = os.path.join(DATA_DIR, "contacts")
KNOWLEDGE_DIR = os.path.join(BASE_DIR, "knowledge")
HUD_DIR = os.path.join(BASE_DIR, "hud")
DOCS_DIR = os.path.join(BASE_DIR, "docs")

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8765

WINDOW_EXPANDED_WIDTH = 430
WINDOW_EXPANDED_HEIGHT = 410
WINDOW_CAPSULE_WIDTH = 190
WINDOW_CAPSULE_HEIGHT = 36



# 超时静默自动归档阈值 (秒)
SESSION_TIMEOUT_SECONDS = 1800

# 自动读取项目根目录下的 .env 文件
ENV_PATH = os.path.join(BASE_DIR, ".env")
if os.path.exists(ENV_PATH):
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception:
        pass

# 大模型配置 (支持 DeepSeek / OpenAI / Moonshot / 阿里通义千问等兼容 OpenAI 协议的接口)
LLM_API_KEY = os.getenv("LLM_API_KEY", os.getenv("OPENAI_API_KEY", ""))
LLM_BASE_URL = os.getenv("LLM_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
