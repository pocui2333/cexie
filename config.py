import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
EGO_DIR = os.path.join(DATA_DIR, "ego")
CONTACTS_DIR = os.path.join(DATA_DIR, "contacts")
KNOWLEDGE_DIR = os.path.join(BASE_DIR, "knowledge")
HUD_DIR = os.path.join(BASE_DIR, "hud")
DOCS_DIR = os.path.join(BASE_DIR, "docs")

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

# 服务仅允许绑定本机回环地址 (HUD 接口会暴露聊天内容，绝不对局域网开放)
SERVER_HOST = "127.0.0.1"
SERVER_PORT = int(os.getenv("PORT", 8765))

# 日志级别 (DEBUG / INFO / WARNING / ERROR)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

WINDOW_EXPANDED_WIDTH = 430
WINDOW_EXPANDED_HEIGHT = 410
WINDOW_CAPSULE_WIDTH = 190
WINDOW_CAPSULE_HEIGHT = 36

# 大模型配置 (支持 DeepSeek / OpenAI / Moonshot / 阿里通义千问等兼容 OpenAI 协议的接口)
LLM_API_KEY = os.getenv("LLM_API_KEY", os.getenv("OPENAI_API_KEY", ""))
LLM_BASE_URL = os.getenv("LLM_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
# 图片气泡描述所用的多模态模型；留空则跳过云端看图，仅使用 macOS 本地 Vision 分类
# (注意: deepseek-chat 等纯文本模型不支持图片输入)
LLM_VISION_MODEL = os.getenv("LLM_VISION_MODEL", "")


def private_tmp_dir() -> str:
    """当前用户私有 (0700) 的临时目录，用于存放聊天窗口截图等敏感中间文件"""
    import tempfile
    path = os.path.join(tempfile.gettempdir(), f"cexie-{os.getuid()}")
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return path
