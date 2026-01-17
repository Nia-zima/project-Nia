# backend/core/config.py
from __future__ import annotations
import os
from pathlib import Path
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(path): pass

# backend/core/config.py -> backend/core -> backend -> PROJECT_ROOT
# 親ディレクトリを3つ遡ることでプロジェクトルートを特定
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Load .env
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
STATIC_DIR = PROJECT_ROOT / "backend" / "static"  # Phase 1: Match current structure
DB_PATH = DATA_DIR / "nia.sqlite3"  # 将来的に統合されるメインDB

def ensure_dirs() -> None:
    """必須ディレクトリの存在を保証する"""
    for d in [DATA_DIR, LOG_DIR, STATIC_DIR]:
        d.mkdir(parents=True, exist_ok=True)

def boot_banner() -> str:
    """起動時に表示するパス一覧"""
    return "\n".join([
        "=== NIA BOOT CONFIGURATION ===",
        f"CWD         : {Path.cwd()}",
        f"PROJECT_ROOT: {PROJECT_ROOT}",
        f"DATA_DIR    : {DATA_DIR}",
        f"LOG_DIR     : {LOG_DIR}",
        f"STATIC_DIR  : {STATIC_DIR}",
        f"DB_PATH     : {DB_PATH}",
        "==============================",
    ])

# --- Backward Compatibility for Phase 1 ---
class Settings:
    # Paths (Absolute)
    PROJECT_ROOT = PROJECT_ROOT
    DATA_DIR = DATA_DIR
    LOG_DIR = LOG_DIR
    STATIC_DIR = STATIC_DIR
    DB_PATH = DB_PATH
    
    # Legacy Paths
    # backend/services/vector_store.py などが期待する BASE_DIR
    # 多くの場合 backend/core だったりするが、安全のため PROJECT_ROOT/backend/core にしておく
    BASE_DIR = str(PROJECT_ROOT / "backend" / "core")

    # DB Paths
    TELEMETRY_DB_PATH = str(DATA_DIR / "telemetry.db")
    CHECKPOINTER_DB_PATH = str(DATA_DIR / "checkpoints.sqlite")
    LONG_TERM_MEMORY_DB_PATH = str(DATA_DIR / "long_term_memory.db")
    CHAT_HISTORY_DB_PATH = str(DATA_DIR / "chat_history.db")

    # JSON Files (Relative to PROJECT_ROOT in old code vs Absolute here)
    USER_PROFILE_JSON = "user_profile.json"  # api_router uses PROJECT_ROOT / settings.USER_PROFILE_JSON
    PUBLIC_STATUS_JSON = "public_status.json"

    # LLM Config (Read from Env)
    LLM_TYPE = os.getenv("LLM_TYPE", "openai")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-vl") # As per summary
    VISION_MODEL = os.getenv("VISION_MODEL", "qwen3-vl:4b")

    # Voice Config
    DEFAULT_VOICE_ID = os.getenv("DEFAULT_VOICE_ID", "14")
    EMOTION_VOICE_MAP = {
        "happy": "14", 
        "sad": "14", 
        "angry": "14", 
        "relaxed": "14", 
        "surprised": "14",
        "neutral": "14"
    }

settings = Settings()
