import logging
import os
import sys
import time
from collections import defaultdict, deque
from logging.handlers import RotatingFileHandler
from pathlib import Path
from backend.core.config import LOG_DIR

# Log Directory setup
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = Path(LOG_DIR) / "app.log"

_HANDLER_MARKER = "_ai_buddy_handler"


class RateLimitFilter(logging.Filter):
    """
    同一キー（prefixなど）に対して、一定時間に一定回数だけ通す簡易レート制限。
    """

    def __init__(self, *, window_sec: float = 1.0, max_events: int = 5, key_fn=None):
        super().__init__()
        self.window_sec = float(window_sec)
        self.max_events = int(max_events)
        self.key_fn = key_fn or (lambda rec: getattr(rec, "msg", "")[:40])
        self._events = defaultdict(deque)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            key = self.key_fn(record)
            now = time.time()
            q = self._events[key]
            while q and (now - q[0]) > self.window_sec:
                q.popleft()
            if len(q) >= self.max_events:
                return False
            q.append(now)
            return True
        except Exception:
            return True


class _QuietPollFilter(logging.Filter):
    """高頻度ポーリングのアクセスログを抑制"""
    _QUIET_PATHS = ("/api/diagnostics", "/api/status", "/health")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(p in msg for p in self._QUIET_PATHS)


def attach_debug_suppress_filter(target: logging.Filterer) -> None:
    """
    高頻度デバッグログだけ間引くフィルタを logger/handler に付与。
    """

    if getattr(target, "_ai_buddy_rate_limit", False):
        return

    def key_fn(rec: logging.LogRecord) -> str:
        msg = str(rec.getMessage())
        if msg.startswith("[DEBUG_SSE_TEXT]"):
            return "DEBUG_SSE_TEXT"
        if msg.startswith("[DEBUG_RAW_STREAM]"):
            return "DEBUG_RAW_STREAM"
        if msg.startswith("[DEBUG_RAW_STREAM_FINAL]"):
            return "DEBUG_RAW_STREAM_FINAL"
        if msg.startswith("[DEBUG_RAW_NON_STREAM]"):
            return "DEBUG_RAW_NON_STREAM"
        if msg.startswith("[DEBUG_SSE_EVENT]"):
            return "DEBUG_SSE_EVENT"
        if msg.startswith("[VEC]"):
            return "VEC"
        return msg[:40]

    f = RateLimitFilter(window_sec=1.0, max_events=5, key_fn=key_fn)
    target.addFilter(f)
    setattr(target, "_ai_buddy_rate_limit", True)


def setup_logging(
    *,
    level: str = "INFO",
    log_file: Path | str | None = None,
    console: bool = True,
    file_encoding: str = "utf-8",
    file_errors: str = "backslashreplace",
) -> None:
    root = logging.getLogger()
    if any(getattr(h, _HANDLER_MARKER, False) for h in root.handlers):
        for h in root.handlers:
            attach_debug_suppress_filter(h)
        return

    level_name = os.getenv("LOG_LEVEL", level or "INFO")
    lvl = getattr(logging, str(level_name).upper(), logging.INFO)

    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

    handlers: list[logging.Handler] = []

    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(lvl)
        setattr(console_handler, _HANDLER_MARKER, True)
        handlers.append(console_handler)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=int(os.getenv("LOG_MAX_BYTES", str(5 * 1024 * 1024))),
            backupCount=int(os.getenv("LOG_BACKUP_COUNT", "3")),
            encoding=file_encoding,
            errors=file_errors,
            delay=True,
        )
        file_handler.setLevel(lvl)
        setattr(file_handler, _HANDLER_MARKER, True)
        handlers.append(file_handler)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    for h in handlers:
        h.setFormatter(formatter)

    root.setLevel(lvl)
    for h in handlers:
        root.addHandler(h)
        attach_debug_suppress_filter(h)

    # サードパーティロガーのノイズ抑制
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("chromadb.telemetry").setLevel(logging.WARNING)

    # 高頻度ポーリングエンドポイントのアクセスログ抑制
    _uvicorn_access = logging.getLogger("uvicorn.access")
    if not getattr(_uvicorn_access, "_quiet_poll_filter", False):
        _uvicorn_access.addFilter(_QuietPollFilter())
        setattr(_uvicorn_access, "_quiet_poll_filter", True)


class CustomLogger:
    def __init__(self, name: str = "AI_Buddy"):
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
            if hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass

        self.logger = logging.getLogger(name)
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        self.logger.setLevel(getattr(logging, log_level, logging.INFO))
        self.logger.propagate = False # Prevent double logging (root logger + custom handler)
        
        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        # Clear existing handlers to prevent duplicates
        if self.logger.hasHandlers():
            self.logger.handlers.clear()

        # 1. Console Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        setattr(console_handler, _HANDLER_MARKER, True)
        self.logger.addHandler(console_handler)

        # 2. File Handler (Rotating)
        max_bytes = int(os.getenv("LOG_MAX_BYTES", str(5 * 1024 * 1024)))
        backup_count = int(os.getenv("LOG_BACKUP_COUNT", "3"))
        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
            errors="backslashreplace",
        )
        file_handler.setFormatter(formatter)
        setattr(file_handler, _HANDLER_MARKER, True)
        self.logger.addHandler(file_handler)

        for h in self.logger.handlers:
            attach_debug_suppress_filter(h)

    def get_logger(self):
        return self.logger

# Global Instance
logger = CustomLogger().get_logger()
