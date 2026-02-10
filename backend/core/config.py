from __future__ import annotations

# backend/core/config.py
from os import getenv

def _env_str(key: str, default: str) -> str:
    v = getenv(key)
    return v if v is not None and str(v).strip() != "" else default

def _env_int(key: str, default: int) -> int:
    v = getenv(key)
    try:
        return int(v) if v is not None and str(v).strip() != "" else default
    except Exception:
        return default

def _env_float(key: str, default: float) -> float:
    v = getenv(key)
    try:
        return float(v) if v is not None and str(v).strip() != "" else default
    except Exception:
        return default

def _env_float_first(keys: list[str], default: float) -> float:
    for key in keys:
        v = getenv(key)
        if v is None or str(v).strip() == "":
            continue
        try:
            return float(v)
        except Exception:
            return default
    return default

def _env_bool(key: str, default: bool) -> bool:
    v = getenv(key)
    if v is None or str(v).strip() == "":
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")
from pathlib import Path
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(path):
        return None

def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    (STATIC_DIR / "audio").mkdir(parents=True, exist_ok=True)

def boot_banner():
    pass

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Load .env
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
STATIC_DIR = PROJECT_ROOT / "backend" / "static"  # Phase 1: Match current structure
DB_PATH = DATA_DIR / "nia.sqlite3"  # 将来的に統合されるメインDB

class LegacySettings:
    BASE_DIR = str(PROJECT_ROOT / "backend" / "core")
    USER_PROFILE_JSON = "user_profile.json"
    PUBLIC_STATUS_JSON = "public_status.json"

class Settings:
    PROJECT_ROOT: Path = PROJECT_ROOT
    DATA_DIR: Path = DATA_DIR
    LOG_DIR: Path = LOG_DIR
    STATIC_DIR: Path = STATIC_DIR
    DB_PATH: Path = DB_PATH
    CHECKPOINTER_DB_PATH: str = str(DATA_DIR / "checkpointer.sqlite3")
    USER_PROFILE_JSON: str = "data/user_profile.json"
    PUBLIC_STATUS_JSON: str = "public_status.json"

    # --- Retention profile ---
    RETENTION_PROFILE: str

    # Boot full sweep
    RETENTION_BOOT_FULL: bool
    RETENTION_BOOT_SINCE_H: int

    # Background full sweeper
    RETENTION_FULL_SWEEPER_ENABLED: bool
    RETENTION_FULL_SWEEPER_INTERVAL_SEC: int
    RETENTION_FULL_SWEEPER_SINCE_H: int

    # Thresholds (env override allowed)
    RETENTION_TH_PROMOTE: float
    RETENTION_TH_BACKGROUND: float
    RETENTION_GRACE_DAYS: float

    # Half-life days (profile-based defaults, env override allowed)
    RETENTION_HL_CONSENT_DAYS: float
    RETENTION_HL_PONDERING_DAYS: float
    RETENTION_HL_DISSONANCE_DAYS: float
    RETENTION_HL_DEFAULT_DAYS: float

    def __init__(self) -> None:
        # プロファイルのデフォルト（env上書きの“土台”）
        profile = _env_str("RETENTION_PROFILE", "prod").strip().lower()
        if profile == "test_fast":
            profile = "fast"
        if profile not in ("prod", "fast"):
            profile = "prod"
        if profile == "fast":
            # 早回し（例：日→分単位相当。テストが回る）
            base = dict(consent=0.25, pondering=0.10, dissonance=0.05, default=0.08)
        else:
            # prod 本値
            base = dict(consent=30.0, pondering=7.0, dissonance=3.0, default=5.0)

        # env があればそっちを優先
        self.RETENTION_HALF_LIFE_CONSENT = _env_float_first(
            ["RETENTION_HALF_LIFE_CONSENT", "RETENTION_HL_CONSENT_DAYS"],
            base["consent"],
        )
        self.RETENTION_HALF_LIFE_PONDERING = _env_float_first(
            ["RETENTION_HALF_LIFE_PONDERING", "RETENTION_HL_PONDERING_DAYS"],
            base["pondering"],
        )
        self.RETENTION_HALF_LIFE_DISSONANCE = _env_float_first(
            ["RETENTION_HALF_LIFE_DISSONANCE", "RETENTION_HL_DISSONANCE_DAYS"],
            base["dissonance"],
        )
        self.RETENTION_HALF_LIFE_DEFAULT = _env_float_first(
            ["RETENTION_HALF_LIFE_DEFAULT", "RETENTION_HL_DEFAULT_DAYS"],
            base["default"],
        )

        self.RETENTION_PROFILE = profile
        self.RETENTION_BOOT_FULL = _env_bool("RETENTION_BOOT_FULL", True)
        self.RETENTION_BOOT_SINCE_H = _env_int("RETENTION_BOOT_SINCE_H", 72)

        self.RETENTION_FULL_SWEEPER_ENABLED = _env_bool("RETENTION_FULL_SWEEPER_ENABLED", True)
        self.RETENTION_FULL_SWEEPER_INTERVAL_SEC = _env_int("RETENTION_FULL_SWEEPER_INTERVAL_SEC", 1800)
        self.RETENTION_FULL_SWEEPER_SINCE_H = _env_int("RETENTION_FULL_SWEEPER_SINCE_H", 24)

        self.RETENTION_PROMOTE_TH = _env_float_first(
            ["RETENTION_PROMOTE_TH", "RETENTION_TH_PROMOTE"],
            0.70,
        )
        self.RETENTION_BACKGROUND_TH = _env_float_first(
            ["RETENTION_BACKGROUND_TH", "RETENTION_TH_BACKGROUND"],
            0.10,
        )
        self.RETENTION_GRACE_DAYS = _env_float("RETENTION_GRACE_DAYS", 1.0)
        self.RETENTION_LIGHT_LIMIT = _env_int("RETENTION_LIGHT_LIMIT", 25)
        self.RETENTION_LIGHT_EVERY_N = _env_int("RETENTION_LIGHT_EVERY_N", 1)

        # Compatibility aliases
        self.RETENTION_TH_PROMOTE = self.RETENTION_PROMOTE_TH
        self.RETENTION_TH_BACKGROUND = self.RETENTION_BACKGROUND_TH
        self.RETENTION_HL_CONSENT_DAYS = self.RETENTION_HALF_LIFE_CONSENT
        self.RETENTION_HL_PONDERING_DAYS = self.RETENTION_HALF_LIFE_PONDERING
        self.RETENTION_HL_DISSONANCE_DAYS = self.RETENTION_HALF_LIFE_DISSONANCE
        self.RETENTION_HL_DEFAULT_DAYS = self.RETENTION_HALF_LIFE_DEFAULT
        self.RETENTION_HL_CONSENT = self.RETENTION_HALF_LIFE_CONSENT
        self.RETENTION_HL_PONDERING = self.RETENTION_HALF_LIFE_PONDERING
        self.RETENTION_HL_DISSONANCE = self.RETENTION_HALF_LIFE_DISSONANCE
        self.RETENTION_HL_DEFAULT = self.RETENTION_HALF_LIFE_DEFAULT

        # Normalization
        self.RETENTION_LIGHT_EVERY_N = max(1, self.RETENTION_LIGHT_EVERY_N)
        self.RETENTION_LIGHT_LIMIT = max(1, min(500, self.RETENTION_LIGHT_LIMIT))
        self.RETENTION_BOOT_SINCE_H = max(1, min(24 * 30, self.RETENTION_BOOT_SINCE_H))

        # OpenAI / LLM settings
        self.OPENAI_MODEL = _env_str("OPENAI_MODEL", "gpt-4o-mini")
        self.OPENAI_API_KEY = _env_str("OPENAI_API_KEY", "")
        self.OPENAI_BASE_URL = _env_str("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.TEMPERATURE = _env_float("TEMPERATURE", 0.7)
        self.PRESENCE_PENALTY = _env_float("PRESENCE_PENALTY", 0.3)
        self.REPETITION_PENALTY = _env_float("REPETITION_PENALTY", 1.12)

        # Vision / Ollama settings
        self.OLLAMA_BASE_URL = _env_str("OLLAMA_BASE_URL", "http://localhost:11434")
        self.OLLAMA_MODEL = _env_str("OLLAMA_MODEL", "qwen3-vl")
        self.VISION_MODEL = _env_str("VISION_MODEL", "qwen3-vl:4b")
        self.VISION_PROVIDER = _env_str("VISION_PROVIDER", "ollama")
        self.VISION_BASE_URL = _env_str("VISION_BASE_URL", "")
        self.VISION_API_KEY = _env_str("VISION_API_KEY", "")

        # History / Tool settings
        self.MAX_HISTORY_MESSAGES = _env_int("MAX_HISTORY_MESSAGES", 60)
        self.MAX_TOOL_CALLS_PER_TURN = _env_int("MAX_TOOL_CALLS_PER_TURN", 3)
        # SSE throttling (ms)
        self.SSE_MIN_INTERVAL_MS = max(0, _env_int("SSE_MIN_INTERVAL_MS", 120))
        # Inner monologue logging (chars)
        self.INNER_MONOLOGUE_MAX_CHARS = max(0, _env_int("INNER_MONOLOGUE_MAX_CHARS", 240))
        self.INNER_MONOLOGUE_FULL = _env_bool("INNER_MONOLOGUE_FULL", False)

        # Voice settings
        self.DEFAULT_VOICE_ID = _env_str("DEFAULT_VOICE_ID", "14")
        self.TTS_FINALIZE_TIMEOUT_SEC = _env_float("TTS_FINALIZE_TIMEOUT_SEC", 30.0)
        self.TTS_SENTENCE_CHUNKING = _env_bool("TTS_SENTENCE_CHUNKING", True)
        self.TTS_SENTENCE_MAX_CHARS = _env_int("TTS_SENTENCE_MAX_CHARS", 90)
        self.EMOTION_VOICE_MAP = {
            "happy": "14",
            "sad": "14",
            "angry": "14",
            "relaxed": "14",
            "surprised": "14",
            "neutral": "14",
        }

        # Legacy compatibility
        self.BASE_DIR = str(PROJECT_ROOT / "backend" / "core")
        self.USER_PROFILE_JSON = _env_str("USER_PROFILE_JSON", "data/user_profile.json")
        self.PUBLIC_STATUS_JSON = _env_str("PUBLIC_STATUS_JSON", "public_status.json")

        # Post-Phase5: Policy and DSPy modes
        # Phase 3 (Gymnasium) と Phase 4 (DSPy) は無効化
        # 理由: 固定化・収束を引き起こすため（Body Constitution B.9「揺らぎの源泉」）
        self.POLICY_MODE = _env_str("POLICY_MODE", "confidence")  # "confidence" | "learned" | "hybrid"
        self.DSPY_MODE = _env_str("DSPY_MODE", "disabled")        # "disabled" | "enabled" | "hybrid"

        # Post-Phase5.5: Experiment Mode
        # 制約をオフにして、自然さを確認する実験用モード
        # ONにすると Body Constitution チェック、steering_risk、結論制約などをスキップ
        self.EXPERIMENT_MODE = _env_bool("EXPERIMENT_MODE", False)
        # Identity tone policy level: "soft" | "balanced" | "strict"
        self.IDENTITY_TONE_LEVEL = _env_str("IDENTITY_TONE_LEVEL", "balanced").strip().lower()
        if self.IDENTITY_TONE_LEVEL not in {"soft", "balanced", "strict"}:
            self.IDENTITY_TONE_LEVEL = "balanced"

        # Post-Phase5.5: Layer B Mode
        # "proposal": 全ての変更が承認待ち（デフォルト）
        # "adaptive": 重要度判定で小さな変化は自動適用、大きな変化は承認待ち
        self.LAYER_B_MODE = _env_str("LAYER_B_MODE", "proposal")

        # Step6: legacy memory tables (episodic_captures/long_term_memories) read-only mode
        self.LEGACY_MEMORY_READ_ONLY = _env_bool("LEGACY_MEMORY_READ_ONLY", False)
        # Step7: keep creating legacy memory tables in init_schema (migration compatibility switch)
        self.LEGACY_MEMORY_TABLES_ENABLED = _env_bool("LEGACY_MEMORY_TABLES_ENABLED", False)
        # Memory event payload guard (bytes, UTF-8 JSON)
        self.MEMORY_EVENT_MAX_PAYLOAD_BYTES = max(2048, _env_int("MEMORY_EVENT_MAX_PAYLOAD_BYTES", 65536))
        # External data pipeline (default OFF)
        self.EXTERNAL_DATA_ENABLED = _env_bool("EXTERNAL_DATA_ENABLED", False)
        self.EXTERNAL_DATA_MIN_DEPTH = max(0, _env_int("EXTERNAL_DATA_MIN_DEPTH", 3))
        self.EXTERNAL_SEARCH_PROVIDER = _env_str("EXTERNAL_SEARCH_PROVIDER", "auto").strip().lower()
        self.EXTERNAL_SEARCH_TIMEOUT_SEC = max(1, _env_int("EXTERNAL_SEARCH_TIMEOUT_SEC", 8))
        self.EXTERNAL_SEARCH_RESULT_LIMIT = max(1, min(5, _env_int("EXTERNAL_SEARCH_RESULT_LIMIT", 3)))
        self.EXTERNAL_MIN_CONFIDENCE = max(0.0, min(1.0, _env_float("EXTERNAL_MIN_CONFIDENCE", 0.65)))
        self.GOOGLE_API_KEY = _env_str("GOOGLE_API_KEY", "")
        self.GOOGLE_CSE_ID = _env_str("GOOGLE_CSE_ID", "")

# OLLAMA/ビジョン/音声などの追加設定（グローバルスコープで定義）
OLLAMA_BASE_URL = getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = getenv("OLLAMA_MODEL", "qwen3-vl") # As per summary
VISION_MODEL = getenv("VISION_MODEL", "qwen3-vl:4b")

# Voice Config
DEFAULT_VOICE_ID = getenv("DEFAULT_VOICE_ID", "14")
EMOTION_VOICE_MAP = {
    "happy": "14",
    "sad": "14",
    "angry": "14",
    "relaxed": "14",
    "surprised": "14",
    "neutral": "14",
}
# TTS finalize timeout (seconds). Prevents streaming from hanging while waiting for audio.
TTS_FINALIZE_TIMEOUT_SEC = float(getenv("TTS_FINALIZE_TIMEOUT_SEC", "30.0"))
# Tool-call loop guard (per user turn)
MAX_TOOL_CALLS_PER_TURN = int(getenv("MAX_TOOL_CALLS_PER_TURN", "3"))
# History window size for prompt context
MAX_HISTORY_MESSAGES = int(getenv("MAX_HISTORY_MESSAGES", "60"))
# SSE throttling (ms)
SSE_MIN_INTERVAL_MS = int(getenv("SSE_MIN_INTERVAL_MS", "120"))
# Inner monologue logging (chars)
INNER_MONOLOGUE_MAX_CHARS = int(getenv("INNER_MONOLOGUE_MAX_CHARS", "240"))
INNER_MONOLOGUE_FULL = getenv("INNER_MONOLOGUE_FULL", "").strip().lower() in ("1", "true", "yes", "y", "on")
# Translation guardrails for memory UI
MAX_TRANSLATE_ITEMS = int(getenv("MAX_TRANSLATE_ITEMS", "10"))
MAX_TRANSLATE_CHARS = int(getenv("MAX_TRANSLATE_CHARS", "2000"))

# Legacy compatibility (keep until refactor complete)
legacy = LegacySettings()
BASE_DIR = legacy.BASE_DIR

from backend.core.config_patch import _apply_retention_profile

settings = Settings()
_apply_retention_profile(settings)

# Legacy compatibility (aliases)
USER_PROFILE_JSON = settings.USER_PROFILE_JSON
PUBLIC_STATUS_JSON = settings.PUBLIC_STATUS_JSON
RETENTION_BOOT_FULL = settings.RETENTION_BOOT_FULL
RETENTION_BOOT_SINCE_H = settings.RETENTION_BOOT_SINCE_H
RETENTION_LIGHT_LIMIT = max(1, min(500, settings.RETENTION_LIGHT_LIMIT))
RETENTION_LIGHT_EVERY_N = max(1, settings.RETENTION_LIGHT_EVERY_N)
RETENTION_PROMOTE_TH = settings.RETENTION_PROMOTE_TH
RETENTION_BACKGROUND_TH = settings.RETENTION_BACKGROUND_TH
RETENTION_GRACE_DAYS = settings.RETENTION_GRACE_DAYS
RETENTION_HALF_LIFE_CONSENT = settings.RETENTION_HALF_LIFE_CONSENT
RETENTION_HALF_LIFE_PONDERING = settings.RETENTION_HALF_LIFE_PONDERING
RETENTION_HALF_LIFE_DISSONANCE = settings.RETENTION_HALF_LIFE_DISSONANCE
RETENTION_HALF_LIFE_DEFAULT = settings.RETENTION_HALF_LIFE_DEFAULT
SSE_MIN_INTERVAL_MS = settings.SSE_MIN_INTERVAL_MS
INNER_MONOLOGUE_MAX_CHARS = settings.INNER_MONOLOGUE_MAX_CHARS
INNER_MONOLOGUE_FULL = settings.INNER_MONOLOGUE_FULL

