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

def boot_banner() -> str:
    return (
        f"=== Nia Boot === model={settings.OPENAI_MODEL} "
        f"vision={settings.VISION_PROVIDER} db={settings.DB_PATH}"
    )

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Load .env
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
STATIC_DIR = PROJECT_ROOT / "backend" / "static"  # Phase 1: Match current structure
DB_PATH = DATA_DIR / "nia.sqlite3"  # 将来的に統合されるメインDB

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
    RETENTION_GRACE_DAYS: float

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
            base = dict(consent=30.0, pondering=7.0, dissonance=3.0, default=7.0)

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

        # Compatibility aliases (used by config_patch.py)
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
        self.MODEL_FAMILY = _env_str("MODEL_FAMILY", "")  # 空=自動検出, qwen/gpt-oss/openai/generic
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

        # Identity Manager secret key
        self.IDENTITY_SECRET_KEY = _env_str("IDENTITY_SECRET_KEY", "INTERNAL_SLEEP_PROCESS_ONLY")
        if self.IDENTITY_SECRET_KEY == "INTERNAL_SLEEP_PROCESS_ONLY":
            import warnings
            warnings.warn(
                "IDENTITY_SECRET_KEY is using the default value. "
                "Set a unique value in .env for production.",
                stacklevel=1,
            )

        # Post-Phase5: DSPy mode (disabled — 固定化・収束を引き起こすため)
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
        # Translation guardrails for memory UI
        self.MAX_TRANSLATE_ITEMS = _env_int("MAX_TRANSLATE_ITEMS", 10)
        self.MAX_TRANSLATE_CHARS = _env_int("MAX_TRANSLATE_CHARS", 2000)

        # Phase D: Context Builder settings
        self.CONTEXT_MAX_PINNED = _env_int("CONTEXT_MAX_PINNED", 5)
        self.CONTEXT_MAX_WORKING = _env_int("CONTEXT_MAX_WORKING", 5)
        self.CONTEXT_MAX_SEMANTIC = _env_int("CONTEXT_MAX_SEMANTIC", 8)

        # Phase M: Memory Retrieval
        self.RETRIEVAL_ENABLED = _env_bool("RETRIEVAL_ENABLED", True)
        self.RETRIEVAL_CANDIDATE_N = _env_int("RETRIEVAL_CANDIDATE_N", 30)
        self.RETRIEVAL_MIN_SCORE = _env_float("RETRIEVAL_MIN_SCORE", 0.1)
        self.RETRIEVAL_W_SIM = _env_float("RETRIEVAL_W_SIM", 0.45)
        self.RETRIEVAL_W_CONF = _env_float("RETRIEVAL_W_CONF", 0.25)
        self.RETRIEVAL_W_REC = _env_float("RETRIEVAL_W_REC", 0.15)
        self.RETRIEVAL_W_INTENT = _env_float("RETRIEVAL_W_INTENT", 0.15)
        self.RETRIEVAL_LOG_ENABLED = _env_bool("RETRIEVAL_LOG_ENABLED", True)
        self.JANOME_ENABLED = _env_bool("JANOME_ENABLED", True)
        self.PINNED_SORT_MODE = _env_str("PINNED_SORT_MODE", "relevance")
        self.EMBEDDING_AT_SAVE = _env_bool("EMBEDDING_AT_SAVE", True)
        self.RETRIEVAL_QUALITY_EVAL = _env_bool("RETRIEVAL_QUALITY_EVAL", True)

        # N.0: Awareness Core
        self.AWARENESS_CORE_ENABLED = _env_bool("AWARENESS_CORE_ENABLED", True)
        self.AWARENESS_SIGNAL_THRESHOLD = _env_float("AWARENESS_SIGNAL_THRESHOLD", 0.3)
        self.AWARENESS_KEYWORD_OVERLAP_MIN = _env_float("AWARENESS_KEYWORD_OVERLAP_MIN", 0.1)
        self.GROWTH_SIGNAL_CAP = _env_float("GROWTH_SIGNAL_CAP", 0.6)
        self.GROWTH_SIGNAL_BOOST = _env_float("GROWTH_SIGNAL_BOOST", 0.1)
        self.AUTHENTICITY_BASE = _env_float("AUTHENTICITY_BASE", 1.0)
        self.AUTHENTICITY_PENALTY = _env_float("AUTHENTICITY_PENALTY", 0.4)

        # N.1: Metacognitive check
        self.METACOG_ENABLED = _env_bool("METACOG_ENABLED", True)
        self.METACOG_GROUNDING_THRESHOLD = _env_float("METACOG_GROUNDING_THRESHOLD", 0.4)
        self.SANKAI_CHECK_ENABLED = _env_bool("SANKAI_CHECK_ENABLED", True)

        # N.2: Contradiction Detection
        self.CONTRADICTION_SCAN_ENABLED = _env_bool("CONTRADICTION_SCAN_ENABLED", True)
        self.CONTRADICTION_MAX_PAIRS = _env_int("CONTRADICTION_MAX_PAIRS", 10)

        # N.3: Self-Model Generation
        self.SELF_MODEL_ENABLED = _env_bool("SELF_MODEL_ENABLED", True)
        self.SELF_MODEL_ARCHIVE_DIR = _env_str("SELF_MODEL_ARCHIVE_DIR", "sleep_outputs")
        self.SELF_MODEL_IDENTITY_PATH = _env_str("SELF_MODEL_IDENTITY_PATH", "identity.md")
        self.SELF_MODEL_PROMPT_TIMEOUT = _env_int("SELF_MODEL_PROMPT_TIMEOUT", 30)
        self.SELF_MODEL_INSIGHTS_LIMIT = _env_int("SELF_MODEL_INSIGHTS_LIMIT", 10)
        self.SELF_MODEL_UPDATE_ON_CHANGE_ONLY = _env_bool("SELF_MODEL_UPDATE_ON_CHANGE_ONLY", True)
        self.SELF_MODEL_MAX_STALE_DAYS = _env_int("SELF_MODEL_MAX_STALE_DAYS", 3)
        self.CONTRADICTION_HOLD_TTL_DAYS = _env_int("CONTRADICTION_HOLD_TTL_DAYS", 3)
        self.CONTRADICTION_SIMILARITY_THRESHOLD = _env_float("CONTRADICTION_SIMILARITY_THRESHOLD", 0.7)

        # N.4: State-Driven Reflection Triggers
        self.STATE_TRIGGER_ENABLED = _env_bool("STATE_TRIGGER_ENABLED", True)
        self.STATE_TRIGGER_COOLDOWN_MINUTES = _env_int("STATE_TRIGGER_COOLDOWN_MINUTES", 60)
        self.STATE_TRIGGER_MIN_IDLE_MINUTES = _env_int("STATE_TRIGGER_MIN_IDLE_MINUTES", 5)

        # N.5: Self-Narrative
        self.SELF_NARRATIVE_ENABLED = _env_bool("SELF_NARRATIVE_ENABLED", True)

        # S.1: Somatic Self-Awareness
        self.SOMATIC_ENABLED = _env_bool("SOMATIC_ENABLED", True)
        self.SOMATIC_FEEDBACK_ENABLED = _env_bool("SOMATIC_FEEDBACK_ENABLED", True)
        self.SOMATIC_ADAPTIVE_ENABLED = _env_bool("SOMATIC_ADAPTIVE_ENABLED", False)

        # P.1: Pip (Mechanical Dog Pet)
        self.PIP_ENABLED = _env_bool("PIP_ENABLED", False)

        # P.2: Room (Nia's Room)
        self.ROOM_UPDATE_ENABLED = _env_bool("ROOM_UPDATE_ENABLED", False)

        # NiaCore: Experience Replay Buffer recording
        self.NIACORE_EXPERIENCE_ENABLED = _env_bool("NIACORE_EXPERIENCE_ENABLED", False)
        # NiaCore: Shadow inference (CfC runs alongside rule-based, log only)
        self.NIACORE_SHADOW_ENABLED = _env_bool("NIACORE_SHADOW_ENABLED", False)
        # NiaCore: Batch training during Sleep Cycle
        self.NIACORE_TRAINING_ENABLED = _env_bool("NIACORE_TRAINING_ENABLED", False)

        # Memory Governance: Phase 0 observability (governance_events recording)
        self.GOVERNANCE_OBSERVE_ENABLED = _env_bool("GOVERNANCE_OBSERVE_ENABLED", False)
        # Memory Governance: Phase A candidate harvesting (raw_promotion_candidates recording)
        self.GOVERNANCE_CANDIDATE_ENABLED = _env_bool("GOVERNANCE_CANDIDATE_ENABLED", False)
        # Memory Governance: Phase A evidence aggregation (memory_evidence recording)
        self.GOVERNANCE_EVIDENCE_ENABLED = _env_bool("GOVERNANCE_EVIDENCE_ENABLED", False)

        # Temporal Somatic Contrast: fingerprint recording (observation only)
        self.FINGERPRINT_RECORD_ENABLED = _env_bool("FINGERPRINT_RECORD_ENABLED", False)

        # SkeletonCore: 会話骨格の記録（DB保存のみ、LLM注入なし）
        self.SKELETON_RECORD_ENABLED = _env_bool("SKELETON_RECORD_ENABLED", False)
        # SkeletonCore: 体感テキストの LLM コンテキスト注入
        self.SKELETON_SOMATIC_ENABLED = _env_bool("SKELETON_SOMATIC_ENABLED", False)

        # Phase R: Autonomous Reflection
        self.IDLE_DETECTION_ENABLED = _env_bool("IDLE_DETECTION_ENABLED", True)
        self.REFLECTION_MIN_TURNS = _env_int("REFLECTION_MIN_TURNS", 10)
        self.REFLECTION_TOKEN_THRESHOLD = _env_int("REFLECTION_TOKEN_THRESHOLD", 5000)
        self.IDLE_THRESHOLD_MINUTES = _env_int("IDLE_THRESHOLD_MINUTES", 30)
        self.IDLE_CHECK_INTERVAL_SEC = _env_int("IDLE_CHECK_INTERVAL_SEC", 120)

        # Phase R.4: Cross-day Distillation
        self.REFLECTION_LOOKBACK_DAYS = _env_int("REFLECTION_LOOKBACK_DAYS", 7)
        self.REFLECTION_CROSS_MIN_DAYS = _env_int("REFLECTION_CROSS_MIN_DAYS", 3)
        if self.REFLECTION_CROSS_MIN_DAYS > self.REFLECTION_LOOKBACK_DAYS:
            import warnings
            warnings.warn(
                f"REFLECTION_CROSS_MIN_DAYS ({self.REFLECTION_CROSS_MIN_DAYS}) > "
                f"REFLECTION_LOOKBACK_DAYS ({self.REFLECTION_LOOKBACK_DAYS}): "
                f"cross-day distillation will never trigger. "
                f"Setting CROSS_MIN_DAYS = LOOKBACK_DAYS."
            )
            self.REFLECTION_CROSS_MIN_DAYS = self.REFLECTION_LOOKBACK_DAYS

        # Phase E: Guardrail v2 settings
        # HOLD_POLICY: "pii_only" = PII + G1 + G6 のみ, "strict" = 全トリガー
        self.HOLD_POLICY = _env_str("HOLD_POLICY", "pii_only")
        self.GUARDRAIL_V2_ENABLED = _env_bool("GUARDRAIL_V2_ENABLED", True)
        self.GUARDRAIL_STAGNATION_TURNS = _env_int("GUARDRAIL_STAGNATION_TURNS", 3)
        self.GUARDRAIL_THIN_COVERAGE_TH = _env_float("GUARDRAIL_THIN_COVERAGE_TH", 0.4)

        # Phase F: Orchestrator S5
        self.ORCHESTRATOR_S5_ENABLED = _env_bool("ORCHESTRATOR_S5_ENABLED", True)
        self.DEPTH2_MIN_TURNS = _env_int("DEPTH2_MIN_TURNS", 100)

        # Episodic compression & archival
        self.EPISODIC_ARCHIVE_AFTER_DAYS = _env_int("EPISODIC_ARCHIVE_AFTER_DAYS", 7)
        self.EPISODIC_SUMMARY_ENABLED = _env_bool("EPISODIC_SUMMARY_ENABLED", True)

        # Checkpointer retention
        self.CHECKPOINTER_RETENTION_DAYS = _env_int("CHECKPOINTER_RETENTION_DAYS", 7)

        # Safety gate
        self.SAFETY_GATE_ENABLED = _env_bool("SAFETY_GATE_ENABLED", True)
        self.SAFETY_BLOCK_PII = _env_bool("SAFETY_BLOCK_PII", True)
        self.SAFETY_LOG_INJECTION = _env_bool("SAFETY_LOG_INJECTION", True)

        # API documentation exposure (disable for production)
        self.API_DOCS_ENABLED = _env_bool("API_DOCS_ENABLED", False)

        # CORS allowed origins (comma-separated, or "*" for all)
        self.CORS_ALLOWED_ORIGINS = _env_str(
            "CORS_ALLOWED_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000,"
            "http://localhost:3001,http://127.0.0.1:3001",
        )

        # WebSocket security
        self.WS_RECEIVE_TIMEOUT_SEC = _env_float("WS_RECEIVE_TIMEOUT_SEC", 300.0)
        self.WS_MAX_MESSAGE_BYTES = _env_int("WS_MAX_MESSAGE_BYTES", 512 * 1024)

        # Rate Limiting
        self.RATE_LIMIT_ENABLED = _env_bool("RATE_LIMIT_ENABLED", True)
        self.RATE_LIMIT_CHAT = _env_str("RATE_LIMIT_CHAT", "30/minute")
        self.RATE_LIMIT_LIVESTREAM = _env_str("RATE_LIMIT_LIVESTREAM", "60/minute")
        self.RATE_LIMIT_VOICE = _env_str("RATE_LIMIT_VOICE", "10/minute")

        # Minecraft Bot Integration
        self.MINECRAFT_ENABLED = _env_bool("MINECRAFT_ENABLED", False)
        self.MINECRAFT_BOT_URL = _env_str("MINECRAFT_BOT_URL", "http://localhost:3100")
        self.MINECRAFT_BOT_WS_URL = _env_str("MINECRAFT_BOT_WS_URL", "ws://localhost:3101")
        self.MINECRAFT_STATE_POLL_SEC = _env_float("MINECRAFT_STATE_POLL_SEC", 2.0)
        self.MINECRAFT_CONTEXT_DEPTH0_CHARS = _env_int("MINECRAFT_CONTEXT_DEPTH0_CHARS", 200)
        self.MINECRAFT_CONTEXT_FULL_CHARS = _env_int("MINECRAFT_CONTEXT_FULL_CHARS", 800)

        # Minecraft Voyager Skill System
        self.MINECRAFT_SKILL_ENABLED = _env_bool("MINECRAFT_SKILL_ENABLED", True)
        self.MINECRAFT_CODE_TIMEOUT = _env_int("MINECRAFT_CODE_TIMEOUT", 30000)

        # Minecraft Autonomous Game Loop (Phase C)
        self.GAME_LOOP_ENABLED = _env_bool("GAME_LOOP_ENABLED", False)
        self.GAME_LOOP_INTERVAL_SEC = _env_int("GAME_LOOP_INTERVAL_SEC", 15)
        self.GAME_LOOP_IDLE_MULTIPLIER = _env_int("GAME_LOOP_IDLE_MULTIPLIER", 4)
        self.GAME_LOOP_MAX_CONSECUTIVE_FAILS = _env_int("GAME_LOOP_MAX_CONSECUTIVE_FAILS", 3)

        # Video Learning (Phase F)
        self.VIDEO_LEARNING_ENABLED = _env_bool("VIDEO_LEARNING_ENABLED", True)
        self.VIDEO_FRAME_INTERVAL_SEC = _env_int("VIDEO_FRAME_INTERVAL_SEC", 5)
        self.VIDEO_MAX_FRAMES = _env_int("VIDEO_MAX_FRAMES", 20)
        self.VIDEO_VISION_CONCURRENCY = _env_int("VIDEO_VISION_CONCURRENCY", 4)

        # Twitter (X) Integration
        self.TWITTER_ENABLED = _env_bool("TWITTER_ENABLED", True)
        self.TWITTER_API_KEY = _env_str("TWITTER_API_KEY", "")
        self.TWITTER_API_SECRET = _env_str("TWITTER_API_SECRET", "")
        self.TWITTER_ACCESS_TOKEN = _env_str("TWITTER_ACCESS_TOKEN", "")
        self.TWITTER_ACCESS_TOKEN_SECRET = _env_str("TWITTER_ACCESS_TOKEN_SECRET", "")
        self.TWITTER_MAX_CHARS = _env_int("TWITTER_MAX_CHARS", 280)
        self.TWITTER_AUTO_PROPOSE = _env_bool("TWITTER_AUTO_PROPOSE", True)
        self.TWITTER_DAILY_MAX = _env_int("TWITTER_DAILY_MAX", 3)

        # Nero webhook (fire-and-forget notification on sleep cycle completion)
        self.NERO_WEBHOOK_URL = _env_str("NERO_WEBHOOK_URL", "")  # e.g. "http://127.0.0.1:8001"
        self.NERO_MEETING_REQUEST_ENABLED = _env_bool("NERO_MEETING_REQUEST_ENABLED", False)

        # Diary (Sleep Cycle)
        self.DIARY_ENABLED = _env_bool("DIARY_ENABLED", True)

        # Canonical training dataset snapshots
        self.TRAINING_DATASET_SNAPSHOT_ENABLED = _env_bool("TRAINING_DATASET_SNAPSHOT_ENABLED", True)
        self.TRAINING_DATASET_SNAPSHOT_BOOT = _env_bool("TRAINING_DATASET_SNAPSHOT_BOOT", True)
        self.TRAINING_DATASET_SNAPSHOT_INTERVAL_SEC = max(300, _env_int("TRAINING_DATASET_SNAPSHOT_INTERVAL_SEC", 3600))
        self.TRAINING_DATASET_SNAPSHOT_HOUR_LOCAL = max(0, min(23, _env_int("TRAINING_DATASET_SNAPSHOT_HOUR_LOCAL", 4)))
        self.TRAINING_DATASET_SNAPSHOT_FORMAT = _env_str("TRAINING_DATASET_SNAPSHOT_FORMAT", "jsonl").strip().lower()
        if self.TRAINING_DATASET_SNAPSHOT_FORMAT not in {"jsonl", "csv"}:
            self.TRAINING_DATASET_SNAPSHOT_FORMAT = "jsonl"
        self.TRAINING_DATASET_SNAPSHOT_THREAD_ID = _env_str("TRAINING_DATASET_SNAPSHOT_THREAD_ID", "").strip() or None
        self.TRAINING_DATASET_SNAPSHOT_DIR = _env_str("TRAINING_DATASET_SNAPSHOT_DIR", "data/training_exports")

        # Chat Bridge (YouTube / Twitch)
        self.CHAT_BRIDGE_ENABLED = _env_bool("CHAT_BRIDGE_ENABLED", False)
        self.YOUTUBE_LIVE_ENABLED = _env_bool("YOUTUBE_LIVE_ENABLED", False)
        self.YOUTUBE_VIDEO_ID = _env_str("YOUTUBE_VIDEO_ID", "")
        self.YOUTUBE_POLL_INTERVAL_SEC = _env_int("YOUTUBE_POLL_INTERVAL_SEC", 0)  # 0=API推奨値
        self.TWITCH_LIVE_ENABLED = _env_bool("TWITCH_LIVE_ENABLED", False)
        self.TWITCH_CHANNEL = _env_str("TWITCH_CHANNEL", "")
        self.TWITCH_NICK = _env_str("TWITCH_NICK", "justinfan12345")
        self.TWITCH_OAUTH_TOKEN = _env_str("TWITCH_OAUTH_TOKEN", "")

        # Screen-based Game Integration
        self.SCREEN_GAME_ENABLED = _env_bool("SCREEN_GAME_ENABLED", False)
        self.GAME_VISION_PROVIDER = _env_str("GAME_VISION_PROVIDER", "gemini")
        self.GEMINI_MODEL = _env_str("GEMINI_MODEL", "gemini-3.0-flash")
        self.SCREEN_CAPTURE_REGION = _env_str("SCREEN_CAPTURE_REGION", "")  # "x,y,w,h" or ""=fullscreen
        self.SCREEN_GAME_LOOP_INTERVAL_SEC = _env_int("SCREEN_GAME_LOOP_INTERVAL_SEC", 3)
        self.SCREEN_GAME_FRAME_BUFFER_SIZE = _env_int("SCREEN_GAME_FRAME_BUFFER_SIZE", 3)

from backend.core.config_patch import _apply_retention_profile


def _validate_feature_flags(s: Settings) -> None:
    """Detect contradictory feature flag combinations and auto-correct."""
    import warnings

    # SKELETON_SOMATIC requires SKELETON_RECORD
    if s.SKELETON_SOMATIC_ENABLED and not s.SKELETON_RECORD_ENABLED:
        warnings.warn(
            "SKELETON_SOMATIC_ENABLED=true requires SKELETON_RECORD_ENABLED=true. "
            "Forcing SKELETON_RECORD_ENABLED=true.",
            stacklevel=2,
        )
        s.SKELETON_RECORD_ENABLED = True

    # NIACORE_TRAINING requires NIACORE_EXPERIENCE
    if s.NIACORE_TRAINING_ENABLED and not s.NIACORE_EXPERIENCE_ENABLED:
        warnings.warn(
            "NIACORE_TRAINING_ENABLED=true requires NIACORE_EXPERIENCE_ENABLED=true. "
            "Forcing NIACORE_EXPERIENCE_ENABLED=true.",
            stacklevel=2,
        )
        s.NIACORE_EXPERIENCE_ENABLED = True

    # NIACORE_SHADOW requires NIACORE_EXPERIENCE
    if s.NIACORE_SHADOW_ENABLED and not s.NIACORE_EXPERIENCE_ENABLED:
        warnings.warn(
            "NIACORE_SHADOW_ENABLED=true requires NIACORE_EXPERIENCE_ENABLED=true. "
            "Forcing NIACORE_EXPERIENCE_ENABLED=true.",
            stacklevel=2,
        )
        s.NIACORE_EXPERIENCE_ENABLED = True

    # SOMATIC_ADAPTIVE requires SOMATIC
    if s.SOMATIC_ADAPTIVE_ENABLED and not s.SOMATIC_ENABLED:
        warnings.warn(
            "SOMATIC_ADAPTIVE_ENABLED=true requires SOMATIC_ENABLED=true. "
            "Forcing SOMATIC_ENABLED=true.",
            stacklevel=2,
        )
        s.SOMATIC_ENABLED = True

    # SOMATIC_FEEDBACK requires SOMATIC
    if s.SOMATIC_FEEDBACK_ENABLED and not s.SOMATIC_ENABLED:
        warnings.warn(
            "SOMATIC_FEEDBACK_ENABLED=true requires SOMATIC_ENABLED=true. "
            "Forcing SOMATIC_ENABLED=true.",
            stacklevel=2,
        )
        s.SOMATIC_ENABLED = True


settings = Settings()
_apply_retention_profile(settings)
_validate_feature_flags(settings)

