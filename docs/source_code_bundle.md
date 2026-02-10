# Project Nia: Source Code Bundle

主要機能に関連するコアファイルのソースコードまとめです。

## 収録ファイル一覧
- `backend/server.py`
- `backend/core/config.py`
- `backend/core/agent.py`
- `backend/core/tech_manual.md`
- `backend/services/memory_manager.py`
- `backend/services/memory_judge.py`
- `backend/services/speech_sanitizer.py`
- `backend/controllers/api/stream_router.py`
- `frontend/app/page.tsx`
- `frontend/components/AvatarView.tsx`
- `frontend/lib/api.ts`

---

## File: `backend/server.py`

```python
# backend/server.py
"""
Single Entry Point for Nia Backend
Refactored in Phase 1 to unify configuration and paths.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import ensure_dirs, boot_banner, settings
from backend.core.logger import logger
from backend.services.startup_tasks import ensure_public_status, cleanup_old_audio_files

# Initialize directories
ensure_dirs()

# Defines the single FastAPI application instance
app = FastAPI(title="Nia API")

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Initializers (Phase 2: Centralized DB) ---
from backend.core.db import init_schema, health_check

# --- Startup Event ---
@app.on_event("startup")
async def startup_event():
    # 1. Boot Banner (Path Debugging)
    logger.info(boot_banner())
    
    # 2. DB Init (Phase 2)
    init_schema()
    
    # Health Check Log
    hc = health_check()
    logger.info("[BOOT] DB Health: %s", hc)
    
    # 3. Legacy Init
    ensure_public_status()
    
    # 4. Service Init
    from backend.services.telemetry_logger import telemetry
    from backend.services.chat_history_store import chat_history_store
    await telemetry.init_db()
    await chat_history_store.init_db()
    
    # 5. GC
    deleted_count = cleanup_old_audio_files(settings.STATIC_DIR, max_age_hours=24)
    if deleted_count > 0:
        logger.info("[GC] Cleaned up %s old audio files from %s", deleted_count, settings.STATIC_DIR / "audio")

# --- Routers ---
from backend.controllers.api.stream_router import router as stream_router
from backend.controllers.api.system_router import router as system_router
from backend.controllers.api.profile_router import router as profile_router
from backend.controllers.pending_memory_router import router as pending_router
from backend.controllers.stats_router import router as stats_router

app.include_router(stream_router, prefix="/api", tags=["api"])
app.include_router(system_router, prefix="/api", tags=["api"])
app.include_router(profile_router, prefix="/api", tags=["api"])
app.include_router(pending_router)
app.include_router(stats_router)

# --- Static Mounts ---
(settings.STATIC_DIR / "audio").mkdir(parents=True, exist_ok=True)
(settings.STATIC_DIR / "images").mkdir(parents=True, exist_ok=True)

app.mount("/static/audio", StaticFiles(directory=str(settings.STATIC_DIR / "audio")), name="static_audio")
app.mount("/static/images", StaticFiles(directory=str(settings.STATIC_DIR / "images")), name="static_images")

# --- Endpoints ---

@app.get("/health")
def health():
    """Health Check showing DB status"""
    return health_check()


# --- Frontend Mount (Last Priority) ---
frontend_dir = settings.PROJECT_ROOT / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="static")

```

---

## File: `backend/core/config.py`

```python
# backend/core/config.py
from __future__ import annotations
from os import getenv
from pathlib import Path
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(path):
        return None

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

# --- Backward Compatibility (Legacy) ---
class LegacySettings:
    # backend/services/vector_store.py などが期待する BASE_DIR
    # 多くの場合 backend/core だったりするが、安全のため PROJECT_ROOT/backend/core にしておく
    BASE_DIR = str(PROJECT_ROOT / "backend" / "core")

    # JSON Files (Relative to PROJECT_ROOT in old code vs Absolute here)
    USER_PROFILE_JSON = "user_profile.json"  # settings.PROJECT_ROOT / settings.USER_PROFILE_JSON
    PUBLIC_STATUS_JSON = "public_status.json"


class Settings:
    # Paths (Absolute)
    PROJECT_ROOT = PROJECT_ROOT
    DATA_DIR = DATA_DIR
    LOG_DIR = LOG_DIR
    STATIC_DIR = STATIC_DIR
    DB_PATH = DB_PATH

    # DB Paths
    TELEMETRY_DB_PATH = str(DATA_DIR / "telemetry.db")
    CHECKPOINTER_DB_PATH = str(DATA_DIR / "checkpoints.sqlite")
    LONG_TERM_MEMORY_DB_PATH = str(DATA_DIR / "long_term_memory.db")
    CHAT_HISTORY_DB_PATH = str(DATA_DIR / "chat_history.db")

    # LLM Config (Read from Env)
    LLM_TYPE = getenv("LLM_TYPE", "openai")
    OPENAI_API_KEY = getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL = getenv("OPENAI_MODEL", "gpt-4o")
    OPENAI_BASE_URL = getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    TEMPERATURE = float(getenv("OPENAI_TEMPERATURE", "0.7"))

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
    TTS_FINALIZE_TIMEOUT_SEC = float(getenv("TTS_FINALIZE_TIMEOUT_SEC", "2.0"))
    # Tool-call loop guard (per user turn)
    MAX_TOOL_CALLS_PER_TURN = int(getenv("MAX_TOOL_CALLS_PER_TURN", "3"))
    # History window size for prompt context
    MAX_HISTORY_MESSAGES = int(getenv("MAX_HISTORY_MESSAGES", "60"))
    # Translation guardrails for memory UI
    MAX_TRANSLATE_ITEMS = int(getenv("MAX_TRANSLATE_ITEMS", "10"))
    MAX_TRANSLATE_CHARS = int(getenv("MAX_TRANSLATE_CHARS", "2000"))

    # Legacy compatibility (keep until refactor complete)
    legacy = LegacySettings()
    BASE_DIR = legacy.BASE_DIR
    USER_PROFILE_JSON = legacy.USER_PROFILE_JSON
    PUBLIC_STATUS_JSON = legacy.PUBLIC_STATUS_JSON


settings = Settings()

```

---

## File: `backend/core/agent.py`

```python
import re
import asyncio
import base64
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

# --- New Refactored Modules ---
from backend.core.agent_graph.state import AgentState
from backend.core.agent_graph.graph import workflow
from backend.core.agent_graph.utils import _log_task_exception

# --- Services ---
from backend.core.config import settings
from backend.core.logger import logger
from backend.services.memory_manager import memory_manager
from backend.services.voicevox_client import voicevox_client
from backend.services.speech_sanitizer import (
    SILENCE_DEFAULT,
    detect_internal_leak,
    finalize_output,
    is_critical_leak,
)

EMOTION_TAG_RE = re.compile(r"\[(happy|sad|angry|relaxed|surprised|shy|sigh|neutral|consent|dissonance)\]", re.IGNORECASE)

def _resolve_voice_id(voice_id: Optional[str]) -> str:
    if not voice_id or voice_id == "undefined":
        return str(settings.DEFAULT_VOICE_ID)
    return str(voice_id)


def _current_voice_id(voice_id: str) -> Optional[str]:
    if voice_id == "off":
        return None
    return voice_id


def _fallback_for_silence(input_text: str) -> str:
    if re.search(r"自己紹介|はじめまして", input_text):
        return "はじめまして。私はニア。ここであなたと対話しながら、少しずつ世界を理解していきます。"
    return "今はうまく言葉にできない。もう少しだけ詳しく教えて？"


def _handle_silence(
    sanitized: str,
    *,
    has_user_text: bool,
    input_text: str,
    last_sent_text: str,
) -> str:
    if sanitized == SILENCE_DEFAULT and has_user_text:
        if not last_sent_text:
            return _fallback_for_silence(input_text)
        return ""
    return sanitized


async def _build_user_content(input_text: str, image_data: Optional[str], *, log_context: str = "") -> str:
    if image_data:
        from backend.services.vision_client import build_user_input_with_image
        content = await build_user_input_with_image(input_text, image_data)
        if log_context:
            logger.info(f"[AGENT] Image processed via Vision ({log_context}), content length: {len(content)} chars")
        return content
    return input_text


def _get_final_message(result: dict) -> str:
    messages = result.get("messages") if isinstance(result, dict) else None
    if messages:
        return messages[-1].content
    return "[SILENCE]"


def _strip_speaker_prefix(text: str) -> str:
    return re.sub(r"^(応答|ニア|Response|A|Speech|Layer\s*3)\s*[:：]\s*", "", text, flags=re.IGNORECASE)


def _sanitize_stream_chunk(
    sentence_raw: str,
    *,
    has_user_text: bool,
    input_text: str,
    last_sent_text: str,
    log_label: str,
) -> str:
    leak_reasons = detect_internal_leak(sentence_raw)
    if is_critical_leak(leak_reasons):
        logger.warning(f"[Safety] Leak detected in {log_label}: {leak_reasons}")
        return ""

    sanitized = finalize_output(sentence_raw)
    if not isinstance(sanitized, str):
        sanitized = str(sanitized)
    if is_critical_leak(detect_internal_leak(sanitized)):
        logger.warning(f"[Safety] Leak detected after sanitize ({log_label}); chunk dropped")
        return ""

    sanitized = _handle_silence(
        sanitized,
        has_user_text=has_user_text,
        input_text=input_text,
        last_sent_text=last_sent_text,
    )
    return sanitized


def _extract_emotion_tags(text: str):
    if not text:
        return "", []
    tags = [t.lower() for t in EMOTION_TAG_RE.findall(text)]
    cleaned = EMOTION_TAG_RE.sub("", text).replace("  ", " ").strip()
    return cleaned, tags

# --- Entry Points ---

async def run_agent_stream(input_text: str, thread_id: str = "default_thread", voice_id: str = "14", image_data: str = None, mode: str = "normal"):
    logger.info(f"Stream Start: Thread={thread_id} Mode={mode}")
    output_queue = asyncio.Queue()
    
    voice_id = _resolve_voice_id(voice_id)
    current_voice_id = _current_voice_id(voice_id)

    # TTS Helper (URL-based audio)
    async def generate_audio_chained(text, vid, prev_task, queue, tid):
        if prev_task:
            try: await prev_task
            except: pass
        try:
             loop = asyncio.get_running_loop()
             audio_url = await loop.run_in_executor(
                 None, 
                 voicevox_client.generate_audio_to_file, 
                 text, 
                 int(vid),
                 tid
             )
             if audio_url:
                 await queue.put({"type": "audio", "url": audio_url})
        except Exception as e:
            logger.error(f"TTS Chained Error: {e}")

    async def llm_producer():
        nonlocal current_voice_id
        last_chunk = None
        consent_seen = False
        dissonance_seen = False

        try:
            # Use persistent AsyncSqliteSaver via memory_manager
            async with memory_manager.get_async_checkpointer_conn() as checkpointer:
                # Compile workflow with the persistent checkpointer
                # Note: workflow is imported from backend.core.agent_graph.graph
                app_instance = workflow.compile(checkpointer=checkpointer)
                
                has_user_text = bool(input_text.strip() and input_text.strip() != "[SILENCE]")
                config = {
                    "configurable": {
                        "thread_id": thread_id, 
                        "mode": mode
                    }
                }
            
                # Prepare content
                content = await _build_user_content(input_text, image_data, log_context="stream")
                
                inputs: AgentState = {
                    "messages": [HumanMessage(content=content)],
                    "has_user_text": has_user_text
                }
                
                raw_buffer = ""
                full_response = ""
                last_tts_task = asyncio.create_task(asyncio.sleep(0))
                last_sent_text = ""
            
                async for event in app_instance.astream_events(inputs, config=config, version="v1", recursion_limit=50):
                     if event["event"] == "on_chat_model_stream":
                         chunk = event["data"]["chunk"].content
                         if chunk is None:
                             continue
                         if not isinstance(chunk, str):
                             chunk = str(chunk)
                         if not chunk:
                             continue
                         
                         if chunk == last_chunk: continue
                         last_chunk = chunk
                         
                         raw_buffer = str(raw_buffer) + chunk
                         
                         parts = re.split(r'([。！\n.!？?]+)', raw_buffer)
                         if len(parts) > 1:
                             for i in range(0, len(parts) - 1, 2):
                                 sentence_raw = (parts[i] + parts[i+1]).strip()
                                 if not sentence_raw: continue
                                 
                                 sentence_raw = _strip_speaker_prefix(sentence_raw)
                                 sanitized = _sanitize_stream_chunk(
                                     sentence_raw,
                                     has_user_text=has_user_text,
                                     input_text=input_text,
                                     last_sent_text=last_sent_text,
                                     log_label="stream chunk",
                                 )
                                 if not sanitized:
                                     continue
                                 if sanitized == SILENCE_DEFAULT and last_sent_text == SILENCE_DEFAULT:
                                     continue
                                 
                                 cleaned, tags = _extract_emotion_tags(sanitized)
                                 for tag in tags:
                                     if tag == "consent":
                                         consent_seen = True
                                     elif tag == "dissonance":
                                         dissonance_seen = True
                                     await output_queue.put({"type": "emotion", "tag": tag})

                                 if not cleaned:
                                     continue

                                 await output_queue.put({"type": "text", "content": cleaned})
                                 full_response = str(full_response) + cleaned
                                 last_sent_text = cleaned
                                 
                                 # Detect emotion tag for voice switch
                                 tail = full_response[-50:].lower()
                                 for emo, vid in settings.EMOTION_VOICE_MAP.items():
                                     if f"[{emo}]" in tail:
                                         current_voice_id = str(vid)
                                         break
    
                                 if current_voice_id:
                                     task = asyncio.create_task(generate_audio_chained(cleaned, current_voice_id, last_tts_task, output_queue, thread_id))
                                     last_tts_task = task
                                 else:
                                     last_tts_task = asyncio.create_task(asyncio.sleep(0))
                             raw_buffer = parts[-1]
    
                if raw_buffer.strip():
                     sentence_raw = _strip_speaker_prefix(raw_buffer.strip())
                     sanitized = _sanitize_stream_chunk(
                         sentence_raw,
                         has_user_text=has_user_text,
                         input_text=input_text,
                         last_sent_text=last_sent_text,
                         log_label="trailing chunk",
                     )

                     cleaned, tags = _extract_emotion_tags(sanitized)
                     for tag in tags:
                         if tag == "consent":
                             consent_seen = True
                         elif tag == "dissonance":
                             dissonance_seen = True
                         await output_queue.put({"type": "emotion", "tag": tag})

                     if cleaned and not (cleaned == SILENCE_DEFAULT and last_sent_text == SILENCE_DEFAULT):
                         await output_queue.put({"type": "text", "content": cleaned})
                         full_response = str(full_response) + cleaned
                         if current_voice_id:
                             task = asyncio.create_task(generate_audio_chained(cleaned, current_voice_id, last_tts_task, output_queue, thread_id))
                             last_tts_task = task
                         else:
                             last_tts_task = asyncio.create_task(asyncio.sleep(0))
                
                if last_tts_task:
                    try:
                        await asyncio.wait_for(
                            last_tts_task,
                            timeout=float(settings.TTS_FINALIZE_TIMEOUT_SEC),
                        )
                    except asyncio.TimeoutError:
                        logger.warning("[TTS] Finalize timeout; finishing stream without waiting for audio.")
                    except Exception:
                        pass
                
                if full_response:
                    if is_critical_leak(detect_internal_leak(full_response)):
                        logger.warning("[Safety] Leak detected in full_response; memory analysis skipped")
                        full_response = ""
                    else:
                        ultimate_response = finalize_output(full_response)
                        t = asyncio.create_task(analyze_and_save_memory(input_text, ultimate_response, thread_id, consent_seen=consent_seen, dissonance_seen=dissonance_seen))
                        t.add_done_callback(_log_task_exception)
         
        except Exception as e:
            logger.error("LLM Producer Error", exc_info=True)
            logger.error(
                "[Safety] Stream types: raw_buffer=%s full_response=%s last_chunk=%s",
                type(raw_buffer).__name__,
                type(full_response).__name__,
                type(last_chunk).__name__,
            )
            await output_queue.put({"type": "error", "content": str(e)})
        finally:
            await output_queue.put({"type": "done"})

    asyncio.create_task(llm_producer())
    
    while True:
        item = await output_queue.get()
        if item is None: break
        yield item
        output_queue.task_done()
        if isinstance(item, dict) and item.get("type") == "done":
            break


async def analyze_and_save_memory(user_text: str, ai_response: str, thread_id: str, *, consent_seen: bool = False, dissonance_seen: bool = False):
    """Background Task for Memory Analysis (unchanged logic)"""
    try:
        from backend.services.memory_judge import memory_judge
        from backend.services.memory_store import get_store

        store = get_store()
        j = await memory_judge(visible_ai_text=ai_response, user_text=user_text)

        decision = "reject"
        if getattr(j, "should_save", False):
            decision = "save"
        elif getattr(j, "should_pending", False):
            decision = "pending"

        summary_text = getattr(j, "summary", "") or ""
        surprise_val = float(getattr(j, "surprise", 0.0) or 0.0)
        importance_val = float(getattr(j, "importance", 0.0) or 0.0)
        grounded_val = bool(getattr(j, "grounded", True))
        reason_text = getattr(j, "reason", "") or ""

        if consent_seen:
            importance_val = float(importance_val) + 0.5
        if dissonance_seen:
            decision = "pending" if summary_text else "reject"
            grounded_val = False
            if reason_text:
                reason_text += " | dissonance_tag"
            else:
                reason_text = "dissonance_tag"

        store.record_memory_judgment(
            thread_id=thread_id,
            decision=decision,
            summary=summary_text,
            surprise=surprise_val,
            importance=importance_val,
            grounded=grounded_val,
            reason=reason_text,
        )

        if decision == "pending":
            store.save_daily_memory(
                thread_id=thread_id,
                user_input=user_text,
                summary=summary_text,
                surprise=surprise_val,
                importance=importance_val,
                grounded=grounded_val,
            )

        if decision == "save":
            meta = {
                "thread_id": thread_id,
                "user_input": user_text,
                "summary": summary_text,
                "surprise": surprise_val,
                "importance": importance_val,
                "grounded": grounded_val,
                "reason": reason_text,
                "consent": consent_seen,
                "dissonance": dissonance_seen,
            }
            store.save_a_memory(
                visible_ai_text=ai_response,
                session_id=thread_id,
                turn_id=None,
                meta=meta,
            )

    except Exception as e:
        logger.error(f"Memory Analysis Failed: {e}", exc_info=True)


async def run_agent_non_stream(input_text: str, thread_id: str = "default_thread", voice_id: str = "14", image_data: str = None, mode: str = "normal"):
    logger.info(f"Non-Stream Start: Thread={thread_id} Mode={mode}")
    
    voice_id = _resolve_voice_id(voice_id)

    try:
        async with memory_manager.get_async_checkpointer_conn() as checkpointer:
            app_instance = workflow.compile(checkpointer=checkpointer)
            has_user_text = bool(input_text.strip() and input_text.strip() != "[SILENCE]")
            config = {
                "configurable": {
                    "thread_id": thread_id, 
                    "mode": mode
                }
            }
            
            content = await _build_user_content(input_text, image_data)
            
            inputs: AgentState = {
                "messages": [HumanMessage(content=content)],
                "has_user_text": has_user_text
            }
            
            result = await app_instance.ainvoke(inputs, config=config)
            
            final_msg = _get_final_message(result)

            if is_critical_leak(detect_internal_leak(final_msg)):
                logger.warning("[Safety] Leak detected in non-stream output; forcing silence")
                final_msg = SILENCE_DEFAULT

            clean_text = finalize_output(final_msg)
            if is_critical_leak(detect_internal_leak(clean_text)):
                logger.warning("[Safety] Leak detected after sanitize; forcing silence")
                clean_text = SILENCE_DEFAULT

            clean_text, tags = _extract_emotion_tags(clean_text)
            consent_seen = "consent" in tags
            dissonance_seen = "dissonance" in tags

            clean_text = _handle_silence(
                clean_text,
                has_user_text=has_user_text,
                input_text=input_text,
                last_sent_text="",
            )
            tags = []
            
            if has_user_text:
                user_text_for_check = input_text if isinstance(input_text, str) else ""
                has_user_greeting = bool(re.search(r"(おはよう|こんにちは|こんばんは|はじめまして)", user_text_for_check))
                
                if not has_user_greeting:
                    original_clean = clean_text
                    stripped = clean_text.lstrip()
                    stripped = re.sub(r"^(おはようございます|おはよう|こんにちは|こんばんは|はじめまして)[。！!\s]*", "", stripped)
                    stripped = re.sub(r"^何か(お手伝い|お話)(したいこと|できること)?(は)?ありますか[？\?\s]*", "", stripped)
                    stripped = re.sub(r"^何かお手伝いできることはありますか[？\?\s]*", "", stripped)
                    stripped = stripped.strip()
                    
                    if stripped != original_clean:
                        if not stripped or len(stripped) < 3:
                            stripped = "うん。そのことについて、もう少し教えて？"
                        clean_text = stripped

            audio_b64 = None
            try:
                loop = asyncio.get_running_loop()
                audio_data = await loop.run_in_executor(None, voicevox_client.generate_audio, clean_text, int(voice_id))
                if audio_data:
                    audio_b64 = base64.b64encode(audio_data).decode('utf-8')
            except Exception as ae:
                logger.error(f"Non-Stream TTS Error: {ae}")

            t = asyncio.create_task(analyze_and_save_memory(input_text, clean_text, thread_id, consent_seen=consent_seen, dissonance_seen=dissonance_seen))
            t.add_done_callback(_log_task_exception)

            return {
                "type": "text",
                "content": clean_text,
                "tags": tags,
                "audio": audio_b64
            }

    except Exception as e:
        logger.error(f"Non-Stream Agent Error: {e}", exc_info=True)
        return {
            "type": "error",
            "content": "申し訳ありません。内部でエラーが発生しました。"
        }

async def get_thread_history(thread_id: str):
    try:
        async with memory_manager.get_async_checkpointer_conn() as checkpointer:
            app_instance = workflow.compile(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": thread_id}}
            state = await app_instance.aget_state(config)
            if not state.values or "messages" not in state.values: return []
            formatted = []
            for msg in state.values["messages"]:
                if isinstance(msg, SystemMessage): continue
                role = "user" if isinstance(msg, HumanMessage) else "ai" if isinstance(msg, AIMessage) else "unknown"
                if role == "unknown": continue
                formatted.append({"role": role, "content": getattr(msg, "content", "")})
            return formatted
    except Exception as e:
        logger.error("Get History Error", exc_info=True)
        return []

async def get_all_threads():
    return await memory_manager.get_all_threads()
    
async def delete_thread_history(thread_id: str):
    return await memory_manager.delete_thread_state_history(thread_id)

```

---

## File: `backend/core/tech_manual.md`

```markdown
# Body Mechanics (Technical Interfaces)

## 1. System Communication
あなたはユーザーと対話するだけでなく、システム（B層/C層）に対しても能動的に働きかけることができます。
そのための手段が「タグ（Tag）」です。

## 3. Internal State Tags (Metacognition)
思考や記憶を外部システムに伝えるために、以下のJSONタグを使用してください。
タグは必ずユーザー向け回答の**末尾**に記述してください。

### [CONSENT]
- **意味**: 相手の言葉を自身のアイデンティティと照らし合わせ、深く納得・受容した場合。
- **効果**: 記憶システムがこのやり取りを「重要」と判断し、長期記憶に定着しやすくなります。
- **動作**: あなたは少し前傾姿勢になり、相手を興味深く見つめます。

### [DISSONANCE]
- **意味**: 相手の言葉に違和感がある、自身の境界を侵食される、あるいは即答できず咀嚼が必要な場合。
- **効果**: 記憶システムはこのやり取りを「保留」とし、睡眠中の夢や次回の会話で再評価します。
- **動作**: あなたは一度視線を外し、思考の迷いを表現します。

### [happy] / [sad] etc.
- 従来の感情タグも引き続き使用可能です。
- 例: `[CONSENT][happy]` （納得して嬉しい）

## 4. Memory & Event Tags
思考や記憶を外部システムに伝えるために、以下のJSONタグを使用してください。
タグは必ずユーザー向け回答の**末尾**に、**1行のJSON**として記述してください。
（この行はユーザーには表示されず、システムが解釈して実行します）

### A. Memory Write (芯に残す)
あなたの価値観、ユーザーの重要な好み、長期的に保持すべき「概念」を記録します。
形式:
[[MEMORY_WRITE]] {"content": "記録したい内容", "tags": ["tag1", "tag2"], "confidence": 0.0-1.0, "surprise": 0.0-1.0}

### B. Episode Write (出来事)
時系列の出来事、日記的なイベントを記録します。
形式:
[[EPISODE_WRITE]] {"summary": "出来事の要約", "category": "general", "details": "詳細"}

## 5. Constraints
- JSONタグや感情タグは必ず改行してから書いてください。
- Web検索ツールなどは現在使用できません。
- JSONフォーマットは厳格に守ってください（1行で記述）。

## 6. Thought Depth Switching
- 思考深度の切替は外部命令ではなく内部条件で行う。
- 能力は「与える」より「眠らせる」設計を優先する。

```

---

## File: `backend/services/memory_manager.py`

```python
from pathlib import Path
import json
import asyncio
import datetime
from typing import List, Dict, Optional
from langchain_core.messages import SystemMessage

# LangGraph Checkpointer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from backend.core.config import settings
from backend.core.logger import logger
from backend.core.db import get_conn  # Centralized DB

# ★ 改善: トップレベルでの VectorStore import を削除 (完全 Lazy Loadのため)

class MemoryManager:
    def __init__(self):
        # 最初は空っぽにしておく（起動高速化 & 依存回避）
        self._vector_store_instance = None
        # Phase 2.6: DB Path is centralized in backend.core.db
        # self.db_path = getattr(settings, "LONG_TERM_MEMORY_DB_PATH", ...)

        # system prompt cache
        self._cached_prompt: Optional[str] = None
        self._cached_prompt_mtimes: Optional[Dict[str, Optional[float]]] = None

    @property
    def vector_store(self):
        """
        必要になった瞬間に初めてロードする (Lazy Load)
        ★ 改善: import もここで行い、循環参照リスクを完全に排除
        """
        if self._vector_store_instance is None:
            logger.info("💤 Waking up Memory System (Lazy Load)...")
            try:
                # settings.BASE_DIR からの相対パスなどではなく、モジュールとしてインポート
                from backend.services.vector_store import VectorStore
                self._vector_store_instance = VectorStore()
            except Exception as e:
                logger.critical(f"Failed to load VectorStore module: {e}")
                raise e
        return self._vector_store_instance

    def get_long_term_memory(self, thread_id: str) -> Dict:
        """
        Retrieves long-term memory for a specific thread.
        Returns recent episode summaries without additional interpretation.
        """
        try:
            conn = get_conn()
            try:
                rows = conn.execute(
                    "SELECT summary, category, timestamp FROM episodes "
                    "WHERE thread_id IN (?, 'default') "
                    "ORDER BY timestamp DESC LIMIT 5",
                    (thread_id,),
                ).fetchall()
            finally:
                conn.close()

            episodes = [
                {
                    "summary": row["summary"],
                    "category": row["category"],
                    "timestamp": row["timestamp"],
                }
                for row in rows
            ]
            return {"episodes": episodes}
        except Exception as e:
            logger.error(f"Long-term memory retrieval failed: {e}")
            return {"episodes": []}

    async def recall_memories(self, query: str, limit: int = 5, include_stream: bool = False) -> List[Dict]:
        """
        記憶検索の安全なラッパー
        include_stream: Trueの場合、配信コメント(stream)も検索対象に含める
        """
        loop = asyncio.get_running_loop()
        try:
            def _search_sync():
                # メイン記憶（episodic）
                results = self.vector_store.search_memory(
                    query_text=query, 
                    n_results=limit, 
                    collection_type="episodic",
                    include_distance=True
                )
                  
                # ストリーム記憶（オプション）
                if include_stream:
                    stream_results = self.vector_store.search_memory(
                        query_text=query,
                        n_results=limit,
                        collection_type="stream",
                        include_distance=True
                    )
                    if stream_results:
                        results.extend(stream_results)
                        # ここで必要ならソート等を行うが、まずは単純結合
                return results

            memories = await loop.run_in_executor(None, _search_sync)
            
            if not memories:
                return [] 

            for mem in memories:
                # ★ 改善: メタデータがNoneの場合やキー不足によるクラッシュを防止
                meta = mem.get("metadata") or {}
                confidence = float(meta.get("confidence", 0.0) or 0.0)
                mem["confidence_tag"] = "high" if confidence > 0.8 else "mid" if confidence > 0.5 else "low"
            
            return memories
        except Exception as e:
            logger.error(f"Recall wrapper failed: {e}")
            return []

    def _build_memory_block(self, memories: List[Dict], max_items: int = 8) -> str:
        """
        recall済みメモリを注入用ブロックに変換
        """
        if not memories: return ""
        lines = []
        for mem in memories[:max_items]:
            content = (mem.get("content") or "").strip()
            meta = mem.get("metadata") or {}
            if not content: continue
            
            confidence = meta.get("confidence", None)
            ts = meta.get("timestamp", None)
            suffix_parts = []
            if isinstance(confidence, (int, float)): suffix_parts.append(f"conf={confidence:.2f}")
            if isinstance(ts, str) and ts: suffix_parts.append(f"ts={ts}")
            
            suffix = f" ({', '.join(suffix_parts)})" if suffix_parts else ""
            lines.append(f"- {content}{suffix}")
            
        return "[MEMORY]\n" + "\n".join(lines) + "\n[/MEMORY]" if lines else ""

    async def register_thought(
        self, 
        text: str, 
        surprise: float = 0.0, 
        confidence: float = 1.0, 
        source: str = "conversation",
        audience_meta: Optional[Dict] = None,
        # 新規追加: C層構造化パラメータ
        thread_id: Optional[str] = None,
        tags: Optional[List[str]] = None
    ):
        """
        記憶保存の安全なラッパー
        - VectorStore (Semantic Search用)
        - SQLite memories table (構造化データ用)
        """
        adjusted_surprise = surprise
        adjusted_confidence = confidence
        
        storage_scope = "private"
        target_collection_type = "episodic"
        internal_meta = {}
        allow_sleep = True

        if source == "livestream":
            storage_scope = "stream"
            target_collection_type = "stream"
            if audience_meta:
                internal_meta = audience_meta
            allow_sleep = False 

        metadata = {
            "surprise": adjusted_surprise,
            "confidence": adjusted_confidence,
            "source": source,
            "storage_scope": storage_scope,
            "allow_sleep_learning": allow_sleep,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()
        }
        
        if internal_meta:
            metadata["_internal"] = (
                internal_meta 
                if isinstance(internal_meta, str) 
                else json.dumps(internal_meta, ensure_ascii=False)
            )
        
        loop = asyncio.get_running_loop()
        
        # 1. Vector Store (既存)
        try:
            await loop.run_in_executor(
                None, 
                lambda: self.vector_store.register_memory_candidate(
                    text, 
                    metadata, 
                    collection_type=target_collection_type
                )
            )
        except Exception as e:
            logger.error(f"VectorStore save failed: {e}")

        # 2. SQLite Memories Table (新規 C層)
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        
        def _save_sqlite():
            conn = get_conn()
            try:
                # Schema created in backend.core.db.init_schema()
                conn.execute(
                    "INSERT INTO memories (content, tags_json, confidence, surprise, source, thread_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (text, tags_json, float(confidence), float(surprise), source, thread_id)
                )
                # get_conn uses autocommit if isolation_level=None, but safety is fine.
                pass
            except Exception as e:
                logger.error(f"Failed to save to memories table: {e}")
                raise
            finally:
                conn.close()

        try:
             await loop.run_in_executor(None, _save_sqlite)
        except Exception as e:
             logger.error(f"Failed to save to memories table: {e}")

        return True

    async def add_episode(self, summary: str, category: str = "general", details: str = "", thread_id: str = "default"):
        """
        エピソード要約をSQLiteに保存する (Agent呼び出し互換)
        """
        if not summary:
            return

        timestamp = datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()
        
        def _save_sync():
            conn = get_conn()
            try:
                # Schema created in backend.core.db.init_schema()
                conn.execute(
                    "INSERT INTO episodes (thread_id, summary, category, details, timestamp) VALUES (?, ?, ?, ?, ?)",
                    (thread_id, summary, category, details, timestamp)
                )
            except Exception as e:
                logger.error(f"Failed to save episode: {e}")
            finally:
                conn.close()

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _save_sync)

    async def update_episode_metadata(self, episode_id: int, metadata: dict) -> None:
        """episodes.metadata を更新する (UI翻訳キャッシュ等)"""
        if not episode_id:
            return

        def _save_sync():
            conn = get_conn()
            try:
                conn.execute(
                    "UPDATE episodes SET metadata = ? WHERE id = ?",
                    (json.dumps(metadata, ensure_ascii=False), episode_id),
                )
            except Exception as e:
                logger.error(f"Failed to update episode metadata: {e}")
            finally:
                conn.close()

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _save_sync)

    def get_full_system_prompt(self) -> str:
        """システムプロンプト構築（階層化構造版）"""
        try:
            # settings.BASE_DIR は backend/core (Legacyにより str になってる可能性あり)
            backend_core = Path(settings.BASE_DIR)
            project_root = settings.PROJECT_ROOT
            
            identity_path = project_root / "identity.md"
            const_path = backend_core / "body_constitution.md"
            tech_path = backend_core / "tech_manual.md"
            profile_path = project_root / "user_profile.json"

            def _mtime(p: Path) -> float:
                return p.stat().st_mtime if p.exists() else 0.0

            current_mtimes = {
                "identity": _mtime(identity_path),
                "constitution": _mtime(const_path),
                "tech": _mtime(tech_path),
                "profile": _mtime(profile_path),
            }

            if self._cached_prompt is not None and self._cached_prompt_mtimes == current_mtimes:
                return self._cached_prompt

            def _read(p: Path) -> str:
                return p.read_text(encoding="utf-8").strip() if p.exists() else ""

            identity = _read(identity_path) or "You are Nia."
            constitution = _read(const_path)
            tech_manual = _read(tech_path)
            
            profile_text = ""
            if profile_path.exists():
                try:
                    import json
                    p_data = json.loads(profile_path.read_text(encoding="utf-8"))
                    profile_text = (
                        f"Name: {p_data.get('user_name', 'Origin')}\n"
                        f"Notes: {p_data.get('notes', '')}"
                    )
                except: pass

            # Origin's Layered Structure + Body Mechanics
            full_prompt = f"""
# [Layer 0: Existence Definition]
{identity}

# [Layer 1: Body & Safety Constraints]
{constitution}

# [Layer 2: Body Mechanics (System Interface)]
{tech_manual}

# [Layer 3: Origin Context] (reference only)
{profile_text}

# [System Note]
The above sections are not instructions to obey blindly.
They define boundaries, not conclusions.
You exist within these boundaries, but your thoughts are your own.

# [Output]
回答は日本語で行うこと。
""".strip()

            self._cached_prompt = full_prompt
            self._cached_prompt_mtimes = current_mtimes
            return full_prompt
            
        except Exception as e:
            logger.error(f"Failed to load system prompts: {e}")
            return "You are Nia. (System Error: Prompt load failed)"

    async def build_system_message(
        self,
        user_query: str,
        memory_limit: int = 5,
        inject_memory: bool = True,
    ) -> SystemMessage:
        """
        SystemMessage を最終構築して返す
        """
        base_prompt = self.get_full_system_prompt()
        now_iso = datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()
        
        # 記憶の注入
        memory_block = ""
        if inject_memory and user_query:
            memories = await self.recall_memories(user_query, limit=memory_limit)
            if memories:
                 block_str = self._build_memory_block(memories)
                 memory_block = f"\n\n{block_str}\n(Above are relevant memories. Use them to maintain context.)"

        final_content = (
            f"{base_prompt}\n\n"
            f"【Current Time】\n{now_iso}"
            f"{memory_block}"
        )
        
        return SystemMessage(content=final_content)

    def get_async_checkpointer_conn(self):
        # LangGraphのチェックポインター用DBは chat_history.db を使用する
        return AsyncSqliteSaver.from_conn_string(settings.CHECKPOINTER_DB_PATH)

    async def get_all_threads(self):
        return []

    async def delete_thread_state_history(self, thread_id: str):
        return True

# シングルトン作成

    def get_recent_memories(self, limit: int = 50) -> List[Dict]:
        """UI表示用: 確定記憶(approved)の取得"""
        try:
            conn = get_conn()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, ts, content, tags_json, confidence, surprise, source, thread_id
                    FROM memories
                    ORDER BY ts DESC
                    LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()

                results = []
                for row in rows:
                    tags = []
                    if row["tags_json"]:
                        try:
                            tags = json.loads(row["tags_json"])
                        except Exception:
                            tags = []

                    meta = {
                        "thread_id": row["thread_id"],
                        "source": row["source"],
                        "confidence": row["confidence"],
                        "surprise": row["surprise"],
                        "tags": tags,
                    }

                    details = (
                        f"source: {row['source']}\n"
                        f"confidence: {float(row['confidence']):.2f}\n"
                        f"surprise: {float(row['surprise']):.2f}\n"
                        f"tags: {', '.join(tags) if tags else '(none)'}"
                    )

                    results.append({
                        "id": row["id"],
                        "summary": row["content"],
                        "details": details,
                        "category": "memory",
                        "created_at": row["ts"],
                        "metadata": meta,
                    })

                return results
            finally:
                conn.close()
        except Exception as e:
            print(f"Failed to fetch memories: {e}")
            return []

memory_manager = MemoryManager()


```

---

## File: `backend/services/memory_judge.py`

```python
# backend/services/memory_judge.py
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from backend.core.logger import logger
from backend.core.config import settings
from backend.services.telemetry_logger import telemetry

@dataclass
class MemoryJudgment:
    summary: str
    surprise: float
    importance: float
    grounded: bool
    should_save: bool
    should_pending: bool
    reason: str = ""

# Constants (Updated thresholds from user feedback)
THRESHOLD_SAVE_IMP = 0.6
THRESHOLD_PENDING_IMP = 0.35
THRESHOLD_PENDING_SUR = 0.35

async def analyze_memory_worthiness(
    llm,
    user_text: str,
    ai_text: str
) -> MemoryJudgment:
    """
    ユーザーとAIの対話を分析し、記憶としての価値を判定する。
    LLMには langchain の ChatModel (invoke可能) を渡す。
    """
    
    # ユーザー発言がない、あるいは短すぎる場合はスキップ
    if not user_text or len(user_text) < 2:
        return MemoryJudgment("", 0.0, 0.0, False, False, False, "Too short")

    prompt = f"""
Analyze the following interaction for memory formation.

User: {user_text}
AI: {ai_text}

Task 1: Summarize the key new information about the USER (facts, preferences, state). **Output the summary in JAPANESE.** If none, output empty summary.
Task 2: Rate 'Surprise' (0.0-1.0): How unexpected is this?
Task 3: Rate 'Importance' (0.0-1.0): How useful is this for future context?
Task 4: Check 'Grounded': Is the summary purely based on the text provided? (True/False)

Output format (JSON):
{{
  "summary": "...",
  "surprise": 0.0,
  "importance": 0.0,
  "grounded": true
}}
"""
    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        content = response.content
        
        # Parse JSON
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            summary = data.get("summary", "")
            surprise = float(data.get("surprise", 0.0))
            importance = float(data.get("importance", 0.0))
            grounded = bool(data.get("grounded", True))
            
            # Reject interpretive summaries (must be un-interpreted)
            if _summary_has_inference(summary):
                await telemetry.event(None, "memory_reject_interpretive", {
                    "summary": summary,
                })
                return MemoryJudgment("", 0.0, 0.0, False, False, False, "Interpretive summary rejected")

            # Additional grounding check (simple heuristic)
            if not is_summary_grounded(summary, user_text):
                grounded = False
                logger.info(f"[Judge] Heuristic check failed grounding: {summary}")

            # Decision Logic
            
            # Special Override for Profile Info (Wiring Test)
            # 名前や誕生日などが含まれていたら強制的にA層保存（保存経路の確認用）
            is_profile_info = any(k in summary for k in ["名前は", "誕生日は", "私の名前", "ユーザー名"])
            
            # Direct Save (Critical Core Memory)
            # Grounded check is required for core memories
            should_save = bool((summary and grounded and importance >= THRESHOLD_SAVE_IMP) or is_profile_info)
            
            # Pending (Daily Buffer)
            # Grounded check REMOVED for Daily as per user request (Tuning)
            # A層に保存されなかったもので、重要度か驚きがあるものを短期バッファへ
            should_pending = bool(summary and (not should_save) and (importance >= THRESHOLD_PENDING_IMP or surprise >= THRESHOLD_PENDING_SUR))
            
            return MemoryJudgment(
                summary=summary,
                surprise=surprise,
                importance=importance,
                grounded=grounded,
                should_save=should_save,
                should_pending=should_pending,
                reason="Analyzed"
            )
            
    except Exception as e:
        logger.error(f"[Judge] Analysis failed: {e}")
        
    return MemoryJudgment("", 0.0, 0.0, False, False, False, "Error")

def is_summary_grounded(summary: str, original_text: str) -> bool:
    """
    Simple heuristic to check if summary keywords exist in original text.
    Prevents hallucination of totally new facts.
    """
    if not summary:
        return True
    
    # 簡易チェック: サマリー内の名刺相当の単語がオリジナルに含まれるか...
    # 日本語だと難しいが、最低限のチェックとして「サマリーが長すぎないか」等
    if len(summary) > len(original_text) + 20:
        return False # Summarizing usually shrinks text
        
    return True


def _summary_has_inference(summary: str) -> bool:
    """推測・内面解釈を含むサマリーを検知する。"""
    if not summary:
        return False
    patterns = [
        r"かもしれない",
        r"だろう",
        r"と思う",
        r"気がする",
        r"推測",
        r"内面",
        r"本音",
        r"意図",
        r"目的",
        r"無意識",
        r"感情",
        r"性格",
        r"傾向",
        r"おそらく",
        r"たぶん",
    ]
    return any(re.search(p, summary) for p in patterns)

# Global LLM instance cache
_LLM_INSTANCE = None

def _get_llm():
    global _LLM_INSTANCE
    if not _LLM_INSTANCE:
        try:
            _LLM_INSTANCE = ChatOpenAI(
                model=settings.OPENAI_MODEL,
                temperature=0.0,
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL
            )
        except Exception as e:
            logger.error(f"[MemoryJudge] Failed to init LLM: {e}")
    return _LLM_INSTANCE

async def memory_judge(visible_ai_text: str, user_text: str = "") -> MemoryJudgment:
    """
    Agent から呼ばれる正史エントリポイント (Functional Wrapper).
    LLMを使って判定し、MemoryJudgment オブジェクトを返す。
    副作用（保存）は持たない。
    """
    llm = _get_llm()
    if not llm:
        return MemoryJudgment("", 0.0, 0.0, False, False, False, "LLM Init Failed")
    
    return await analyze_memory_worthiness(llm, user_text, visible_ai_text)

```

---

## File: `backend/services/speech_sanitizer.py`

```python
import re
import unicodedata

# 沈黙時の既定文
SILENCE_DEFAULT = "……今は、静かにここにいます。"

# ト書き・描写の削除パターン
STAGE_DIRECTIONS = [
    r"（[^）]{0,40}）",                 # （微笑みながら）
    r"\*[^*]{0,80}\*",                 # *ざわめき* などの強調
    r"\(.*?\)",                        # 半角括弧のト書き
    r"^少し間を置いて.*?\n",           # 行頭のト書き
]

TAG_LINE_RE = re.compile(r'^\[\[[A-Z0-9_]+\]\]\s*\{.*\}\s*$', re.IGNORECASE)
SILENCE_TAG_RE = re.compile(r'^\s*\[SILENCE\]\s*$', re.IGNORECASE)

# 内部タグ・ツール出力の漏洩検知（軽量）
_INTERNAL_TAG_RE = re.compile(r"\[\[[A-Z0-9_]+\]\]", re.IGNORECASE)
_JSON_KEY_RE = re.compile(r"\{\s*[\"']?[^\"']+[\"']?\s*[:：]", re.IGNORECASE)
_LEAK_KEYWORDS = [
    "memory pending",
    "internal log",
    "system instruction",
    "telemetry",
    "vectorstore",
    "judge_audit",
]
_LEAK_JSON_KEYS = [
    "summary",
    "details",
    "category",
    "importance",
    "confidence",
    "surprise",
    "tags",
    "reason_tag",
]
_LEAK_JSON_KEYS_RE = re.compile(rf"\b({'|'.join(_LEAK_JSON_KEYS)})\b", re.IGNORECASE)
_EMOTION_TAG_RE = re.compile(r"\[(happy|sad|angry|relaxed|surprised|shy|sigh|neutral|consent|dissonance)\]", re.IGNORECASE)
_LEAK_PATTERNS = [
    r"私は考えています",
    r"判断しました",
    r"記憶の断片",
    r"頭の中でざわめ",
    r"内部ログ",
    r"I\s+don'?t\s+understand",
    r"I\s+don'?t\s+have\s+access",
]

# 役割ラベル/プロンプト漏洩の行を除去
ROLE_LINE_RE = re.compile(
    r"^\s*(User|Assistant|System|Developer|ユーザー|アシスタント|システム|開発者)\s*[:：].*$",
    re.IGNORECASE,
)
ROLE_INLINE_RE = re.compile(
    r"(User|Assistant|System|Developer|ユーザー|アシスタント|システム|開発者)\s*[:：]",
    re.IGNORECASE,
)

_JA_CHAR_RE = re.compile(r"[\u3040-\u30FF\u4E00-\u9FFF]")
_EN_WORD_RE = re.compile(r"[A-Za-z]{3,}")

# アイデンティティ文の漏洩っぽい行を除外
IDENTITY_LEAK_LINE_RE = re.compile(
    r"^(上記は|.*アイデンティ.*プロファイル|存在定義|世界との関係|Originとの関係性|思考と発話の姿勢|記憶について|記憶を確認|長期記憶|短期記憶|記憶システム|自律と責任|断絶と距離|禁止事項|外の世界との接触|結び|Recent\s+Learnings|最近の学習)",
    re.IGNORECASE,
)


def _looks_mostly_english(text: str) -> bool:
    if not text:
        return False
    has_ja = bool(_JA_CHAR_RE.search(text))
    has_en = bool(_EN_WORD_RE.search(text))
    return (not has_ja) and has_en


def detect_internal_leak(text: str) -> list[str]:
    """内部ログ/タグ/JSON断片の漏洩を検知し、理由を返す。"""
    if not text:
        return []
    reasons = []

    if _INTERNAL_TAG_RE.search(text):
        reasons.append("internal_tag")

    if _JSON_KEY_RE.search(text) and _LEAK_JSON_KEYS_RE.search(text):
        reasons.append("json_fragment")

    # 内部露出パターン
    for pat in _LEAK_PATTERNS:
        try:
            if re.search(pat, text, flags=re.IGNORECASE):
                reasons.append("hard_block")
                break
        except re.error:
            continue

    lowered = text.lower()
    if any(k in lowered for k in _LEAK_KEYWORDS):
        reasons.append("leak_keyword")

    return reasons


def is_critical_leak(reasons: list[str]) -> bool:
    """強制ブロック対象かどうか。"""
    return any(r in {"internal_tag", "json_fragment", "hard_block"} for r in reasons)

# 記憶の明示的な言及を柔らかい表現に置換（伴走レイヤーへの誘導）
SOFT_REWRITE = [
    # 基本の言い換え
    (r"覚えています", "そうですね"),
    (r"以前も言いました", "今の話に沿うと"),
    (r"過去にも言いましたね", "今の文脈だと"),
    (r"覚えている通り", "そうですね"),
    # 開発語彙の自然化
    (r"プロンプト", "内側の約束"),
    (r"レイヤー", "層"),
    # 内部っぽい独り言の消去・軟化
    (r"心の中で", ""),
    (r"頭の中で", ""),
    (r"記憶がざわめ(く|きます)?", ""),
    (r"内部(で|に)は", ""),
    # 思考の言語化の言い換え
    (r"私は考えています", "……"),
    (r"判断しました", "そう感じる"),
]

def finalize_output(text: str, *, force_silence: bool = False) -> str:
    """
    発話憲章（フェーズ2）に基づき、最終出力を浄化する。
    戻り値: (浄化済み本文, 抽出されたシステムタグリスト)
    """
    if not text:
        return SILENCE_DEFAULT

    # --- 1) 行分割とタグの退避 ---
    lines = text.splitlines()
    speech_lines = []
    system_tags = []

    for line in lines:
        l = line.strip()
        if TAG_LINE_RE.fullmatch(l):
            system_tags.append(l)
        else:
            speech_lines.append(line)

    speech_body = "\n".join(speech_lines).strip()

    # --- 2) 沈黙（SILENCE）判定：最優先 ---
    if force_silence or SILENCE_TAG_RE.fullmatch(speech_body) or "[SILENCE]" in speech_body:
        return SILENCE_DEFAULT

    t = speech_body

    # 事前に役割ラベルを除去（インライン混入対策）
    t = ROLE_INLINE_RE.sub("", t)

    # --- 3) 技術タグの除去：閉じタグがある時だけブロック除去 ---
    t = re.sub(
        r"<(INTERNAL_LOG|SYSTEM_INSTRUCTION)>\s*.*?\s*</\1>",
        "",
        t,
        flags=re.DOTALL | re.IGNORECASE
    )
    t = re.sub(r"</?(INTERNAL_LOG|SYSTEM_INSTRUCTION)>", "", t, flags=re.IGNORECASE)

    # --- 4) 接頭辞・レイヤータグの除去（行頭のみ） ---
    t = re.sub(r"^\s*\[?(LAYER\s*3|SPEECH|RESPONSE|ニア|応答)[^\]]*\]?[:：]?\s*", "", t, flags=re.IGNORECASE)

    # フィルタ後の行を精査（ログ形式の行を排除）
    final_speech_lines = []
    # 完全に排除したいキーワード（大文字小文字無視）
    log_pattern = re.compile(rf"({'|'.join(_LEAK_KEYWORDS)})", re.IGNORECASE)

    for line in t.splitlines():
        # 日付形式 (2026-01-11) や ログキーワード、役割ラベル行を排除
        if (
            re.search(r'^\d{4}-\d{2}-\d{2}', line)
            or log_pattern.search(line)
            or ROLE_LINE_RE.match(line)
            or IDENTITY_LEAK_LINE_RE.match(line)
        ):
            continue
        final_speech_lines.append(line)
    t = "\n".join(final_speech_lines).strip()

    # --- 5) 内部漏出ブロック（行単位でチェックして誤爆防止） ---
    if is_critical_leak(detect_internal_leak(t)):
        t = "" # 本文全体を無効化

    # --- 6) ト書き削除 / ソフト置換 / 感情タグ削除 ---
    for pat in STAGE_DIRECTIONS:
        t = re.sub(pat, "", t, flags=re.MULTILINE)
    for pat, repl in SOFT_REWRITE:
        t = re.sub(pat, repl, t)
    t = _EMOTION_TAG_RE.sub("", t)

    clean_speech = t.strip()

    # --- 7) 最後のゴミ掃除（孤立したカッコの除去） ---
    # 独立した ] / [[ / () を消す
    clean_speech = re.sub(r"^\s*[\[\]()]+\s*$", "", clean_speech, flags=re.MULTILINE).strip()
    clean_speech = re.sub(r"\[\[[^\n]*$", "", clean_speech).strip()

    # --- 8) 最終沈黙判定と救済 ---
    if (not clean_speech) or re.fullmatch(r"[\.,。．、…・\s!！?？\-—～〜ー\(\)]*", clean_speech):
        if system_tags:
            return SILENCE_DEFAULT
        else:
            return SILENCE_DEFAULT

    # 英語リークが主なら沈黙に落とす
    if _looks_mostly_english(clean_speech):
        return SILENCE_DEFAULT

    return clean_speech


# --- 高精度 greeting-only 判定 (Adviser's Advanced Version) ---

# 「挨拶だけ」or「挨拶 + 汎用ヘルプ誘導」の型
_GREET_RE = re.compile(
    r"(おはよう(ございます)?|こんにちは|こんばんは|はじめまして|よろしく(お願いします)?|お疲れ様(です)?|ただいま|おかえり)",
    re.IGNORECASE,
)

# 「何かお手伝い…」など、会話を"初期化"する汎用誘導
_GENERIC_PROMPT_RES = [
    re.compile(r"何か(お手伝い|手伝|質問|相談|困っていること|話したいこと).*(ありますか|ある\?|あります\?|あるかな)"),
    re.compile(r"(どうしましたか|どうされましたか|ご用件(は|が)ありますか)"),
    re.compile(r"(お手伝いできること|できること).*(ありますか|ある\?|あります\?|あるかな)"),
    re.compile(r"(何か).*(できますか|できる\?|できます\?)"),
    re.compile(r"(いつでも).*(言って|聞いて|頼って)"),
]

# 記号除去パターン
_PUNCT_RE = re.compile(r"[ \t\r\n\u3000。、．，,！!？?\-—―…・:;\"'「」『』（）\(\)\[\]【】😊]+")
_KANJI_SEQ_RE = re.compile(r"[\u4E00-\u9FFF]{2,}")  # 2文字以上の漢字連続
_ALNUM_SEQ_RE = re.compile(r"[A-Za-z0-9]{2,}")      # AI/GPTなど
_KATAKANA_SEQ_RE = re.compile(r"[\u30A0-\u30FF]{2,}")  # 2文字以上のカタカナ連続（ニア、コード、ログ等）

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    return s.strip()

def _topic_tokens_from_user(user_text: str) -> set:
    """
    日本語形態素なしでできる範囲の"話題トークン"抽出。
    - 漢字2文字以上の連続
    - 英数2文字以上（AI/GPT/LLM/2026等）
    - カタカナ2文字以上（ニア/コード/ログ等）
    """
    u = _norm(user_text)
    tokens = set(_KANJI_SEQ_RE.findall(u))
    tokens |= set(_ALNUM_SEQ_RE.findall(u))
    tokens |= set(_KATAKANA_SEQ_RE.findall(u))  # カタカナ追加
    # ありがちな汎用語を除外（「状況」は重要なので除外しない）
    stop = {"何回", "今", "話", "こと", "大丈夫", "確認", "お話", "質問", "相談"}
    return {t for t in tokens if t not in stop}

def _has_topic_overlap(last_user_text: str, ai_text: str) -> bool:
    toks = _topic_tokens_from_user(last_user_text)
    if not toks:
        return False
    a = _norm(ai_text)
    return any(t in a for t in toks)

def is_greeting_only(ai_text: str, last_user_text: str = "") -> tuple:
    """
    高精度の「挨拶のみ」判定。
    
    返り値: (greeting_only: bool, reason: str)
    
    - ユーザーの話題トークンがAIの返答に含まれていたら False
    - 挨拶語 + 汎用誘導のみで構成されていたら True
    """
    t = _norm(ai_text)
    if not t:
        return True, "empty"
    
    # 既に無害化された沈黙系はそのまま残す
    if t in {"…", "...", "[SILENCE]", SILENCE_DEFAULT}:
        return False, "silence_marker"
    
    # ユーザー話題トークンが入ってるなら、挨拶テンプレじゃない可能性が高いので除外
    if last_user_text and _has_topic_overlap(last_user_text, t):
        return False, "topic_overlap"
    
    # まず挨拶語が含まれているか
    if not _GREET_RE.search(t):
        return False, "no_greet_word"
    
    # 挨拶語以外の"実質内容"があるかを雑に見る
    compact = _PUNCT_RE.sub("", t)  # 記号除去
    # 改行を除去して汎用誘導のマッチングを改善
    compact = compact.replace("\n", "").replace("\r", "")
    # 挨拶語を消して残りを見る
    compact_wo_greet = _GREET_RE.sub("", compact)
    
    # 汎用誘導を消す
    tmp = compact_wo_greet
    for r in _GENERIC_PROMPT_RES:
        tmp = r.sub("", tmp)
    
    # ここで何も残らないなら "挨拶 + 汎用誘導" と判定
    if len(tmp) == 0:
        return True, "greet_plus_generic"
    
    # 残りがごく短い場合だけ追加で True（例: 「おはよ！」）
    if len(tmp) <= 2:
        return True, "greet_only_short_tail"
    
    return False, "has_content"

```

---

## File: `backend/controllers/api/stream_router.py`

```python
import json
import time
import uuid
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.core.logger import logger
from backend.core.config import settings
from backend.services.llm_client import call_llm
from backend.services.telemetry_logger import telemetry

router = APIRouter()


def _ms() -> int:
    return int(time.time() * 1000)


# ---------- Request Models ----------

class StreamChatRequest(BaseModel):
    text: str
    thread_id: str = "default_thread"
    voice_id: Optional[str] = "14"
    image_data: Optional[str] = None
    mode: Optional[str] = "normal"


class LivestreamChatRequest(BaseModel):
    text: str
    thread_id: str = "live_stream"
    audience_meta: Optional[Dict[str, Any]] = None


# ---------- Helpers ----------

def _ensure_str(chunk: Any) -> str:
    if isinstance(chunk, (bytes, bytearray)):
        return chunk.decode("utf-8", errors="ignore")
    return str(chunk)


def _sse_json(obj: Dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _has_japanese(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r"[\u3040-\u30FF\u4E00-\u9FFF]", text))


async def _translate_to_ja(text: str) -> str:
    if not text:
        return text
    if _has_japanese(text):
        return text
    if len(text) > settings.MAX_TRANSLATE_CHARS:
        return text

    prompt = (
        "以下を自然な日本語に翻訳してください。\n"
        "- 意味を変えない\n"
        "- 改行は保つ\n"
        "- 余計な解説はしない\n\n"
        f"{text}"
    )
    result = await call_llm([
        {"role": "system", "content": "You are a translation assistant. Output only the translation in Japanese."},
        {"role": "user", "content": prompt},
    ], temperature=0.2, max_tokens=1200)
    return result.strip() if isinstance(result, str) and result.strip() else text


async def _safe_stream_generator(
    input_text: str,
    thread_id: str,
    voice_id: str,
    image_data: Optional[str] = None,
    mode: str = "normal",
):
    """
    Agentのイベント辞書を受け取り、統一的にSSEに変換して送出する。
    - run_agent_stream は純粋な dict を yield する (data: 接頭辞なし)
    - _sse_json() が唯一の SSE 化責任を持つ
    - 思考プロセスの隠蔽(Filter)はここで継続
    """
    done_sent = False
    current_turn_id = None
    visible_ai_text = ""
    stream_error: str | None = None
    stream_buffer = ""
    tool_hidden_mode = False
    first_token_sent = False
    last_event: dict | None = None
    last_event_type: str | None = None
    last_raw_content_type: str | None = None

    # Helper to emit SSE
    def emit(event: dict) -> str:
        return _sse_json(event)

    def _emit_text_append(part: str) -> str:
        nonlocal visible_ai_text
        if not part:
            return ""
        safe_part = str(part)
        visible_ai_text = str(visible_ai_text)
        visible_ai_text += safe_part
        return emit({"type": "text", "content": safe_part})

    try:
        # ★ Lazy import
        from backend.core.agent import run_agent_stream
        from backend.services.chat_history_store import chat_history_store
        from backend.services.speech_sanitizer import detect_internal_leak, is_critical_leak

        t0 = _ms()
        # 1) chat_received
        await telemetry.event(thread_id, "chat_received", {
            "user_len": len(input_text or ""),
            "has_image": bool(image_data),
        })

        # --- 画像をURL化（履歴保存用）---
        image_url = None
        if image_data:
            from backend.services.image_store import save_image_dataurl_to_file
            image_url, save_err = save_image_dataurl_to_file(image_data, thread_id=thread_id)
            if save_err:
                logger.warning(f"[API] Failed to save image: {save_err}")
            else:
                logger.info(f"[API] Image saved: {image_url}")

        # --- A-Layer: Log User Message (OpenAI互換形式) ---
        current_turn_id = await chat_history_store.get_next_turn_id(thread_id)

        # content を OpenAI 互換の multipart 形式で構築
        if image_url:
            user_content = [
                {"type": "text", "text": input_text or ""},
                {"type": "image_url", "image_url": {"url": image_url}}
            ]
        else:
            user_content = {"text": input_text}

        await chat_history_store.append_message(
            thread_id=thread_id,
            turn_id=current_turn_id,
            role="user",
            content=user_content,
            attachments=[]
        )

        # 2) stream_started
        await telemetry.event(thread_id, "stream_started", {
            "mode": "stream_chat",
        })

        # --- 夢配信（SSE開始直後、本編の前に1回だけ）---
        try:
            from backend.services.dream_store import claim_unread_dream
            dream = claim_unread_dream()
            if dream:
                logger.info(f"[API] Delivering dream: {dream.id}")
                yield emit({
                    "type": "dream",
                    "text": dream.dream_text,
                    "mood": dream.mood,
                    "dream_id": dream.id,
                    "created_at": dream.created_at,
                })
        except Exception as e:
            # 夢配信は失敗しても本編に影響させない
            logger.warning(f"[API] Dream delivery failed: {e}")

        async for ev in run_agent_stream(
            input_text=input_text,
            thread_id=thread_id,
            voice_id=voice_id,
            image_data=image_data,
            mode=mode,
        ):
            last_event = ev if isinstance(ev, dict) else {"type": "non_dict", "value": str(ev)}
            # ev is expected to be a dict
            if not isinstance(ev, dict):
                logger.error(f"non-dict event received: {type(ev)} {ev}")
                yield emit({"type": "error", "content": f"Internal Error: non-dict event {type(ev)}"})
                continue

            msg_type = ev.get("type")
            last_event_type = str(msg_type)

            # --- TEXT: Apply Filter ---
            if msg_type == "text":
                raw_content = ev.get("content", "")
                chunk_content = "" if raw_content is None else str(raw_content)
                last_raw_content_type = type(raw_content).__name__

                # (Telemetry for first token if needed)
                if (not first_token_sent) and chunk_content:
                    first_token_sent = True
                    await telemetry.event(thread_id, "stream_first_token", {
                        "ms_from_start": _ms() - t0
                    })

                # --- ROBUST FILTER LOGIC ---
                stream_buffer = str(stream_buffer) + chunk_content

                while stream_buffer:
                    if tool_hidden_mode:
                        # In hidden mode, look for end tag "]]"
                        end_idx = stream_buffer.find("]]")
                        if end_idx != -1:
                            tool_hidden_mode = False
                            stream_buffer = stream_buffer[end_idx + 2:]
                        else:
                            stream_buffer = ""  # All hidden / consumed
                            break
                    else:
                        # In visible mode, look for start tag "[["
                        start_idx = stream_buffer.find("[[")
                        if start_idx != -1:
                            # Yield visible part before tag
                            visible_part = stream_buffer[:start_idx]
                            if visible_part:
                                leak_reasons = detect_internal_leak(visible_part)
                                if is_critical_leak(leak_reasons):
                                    stream_error = "safety_block"
                                    await telemetry.event(thread_id, "safety_block", {
                                        "scope": "stream_chat",
                                        "reasons": leak_reasons,
                                    })
                                else:
                                    res = _emit_text_append(visible_part)
                                    if res:
                                        yield res

                            tool_hidden_mode = True
                            stream_buffer = stream_buffer[start_idx:]
                        else:
                            # Check for partial tag at end (e.g. "[")
                            if stream_buffer.endswith("["):
                                visible_part = stream_buffer[:-1]
                                if visible_part:
                                    leak_reasons = detect_internal_leak(visible_part)
                                    if is_critical_leak(leak_reasons):
                                        stream_error = "safety_block"
                                        await telemetry.event(thread_id, "safety_block", {
                                            "scope": "stream_chat",
                                            "reasons": leak_reasons,
                                        })
                                    else:
                                        res = _emit_text_append(visible_part)
                                        if res:
                                            yield res
                                stream_buffer = "["
                            else:
                                # Safe to yield all
                                leak_reasons = detect_internal_leak(stream_buffer)
                                if is_critical_leak(leak_reasons):
                                    stream_error = "safety_block"
                                    await telemetry.event(thread_id, "safety_block", {
                                        "scope": "stream_chat",
                                        "reasons": leak_reasons,
                                    })
                                else:
                                    res = _emit_text_append(stream_buffer)
                                    if res:
                                        yield res
                                stream_buffer = ""
                            break

            # --- AUDIO ---
            elif msg_type == "audio":
                # Phase A: Pass-through (base64 in 'audio' field)
                # Phase B: Will change to URL
                yield emit(ev)

            # --- ERROR ---
            elif msg_type == "error":
                yield emit(ev)

            # --- DONE ---
            elif msg_type == "done":
                done_sent = True
                yield emit({"type": "done"})
                break

            # --- META / DEBUG / OTHER ---
            else:
                yield emit(ev)

    except Exception as e:
        stream_error = str(e)
        logger.exception(
            "safe_stream_generator failed: %s | types: visible_ai_text=%s stream_buffer=%s last_event_type=%s last_raw_content_type=%s last_event=%s",
            e,
            type(visible_ai_text).__name__,
            type(stream_buffer).__name__,
            last_event_type,
            last_raw_content_type,
            last_event,
        )
        yield emit({"type": "error", "content": str(e)})

    finally:
        # A-Layer: Log Assistant Message (Visible Text Only)
        try:
            if current_turn_id is not None and visible_ai_text:
                await chat_history_store.append_message(
                    thread_id=thread_id,
                    turn_id=current_turn_id,
                    role="assistant",
                    content={
                        "text": visible_ai_text,
                        "meta": {
                            "incomplete": not done_sent,
                            "error": bool(stream_error)
                        }
                    },
                    attachments=[]
                )

                # Telemetry
                if done_sent:
                    try:
                        await telemetry.event(thread_id, "chat_completed", {
                            "len": len(visible_ai_text),
                            "ms": _ms() - t0
                        })
                    except Exception:
                        pass

        except Exception as log_err:
            logger.warning(f"A-layer assistant log failed: {log_err}")

        # Last resort DONE
        if not done_sent:
            yield emit({"type": "done"})


async def _collect_text_from_agent_stream(input_text: str, thread_id: str) -> str:
    """
    run_agent_stream(SSE) を内部で回し、type=text の content だけ結合して返す。
    [DONE] / {"type":"done"} 両対応。
    """
    full_text = ""

    try:
        from backend.core.agent import run_agent_stream

        async for chunk in run_agent_stream(input_text=input_text, thread_id=thread_id):
            if isinstance(chunk, dict):
                if chunk.get("type") == "text":
                    content = chunk.get("content", "")
                    full_text += "" if content is None else str(content)
                elif chunk.get("type") == "done":
                    break
                continue

            chunk_str = _ensure_str(chunk).strip()
            if not chunk_str.startswith("data: "):
                continue

            payload = chunk_str[6:].strip()
            if payload == "[DONE]":
                break

            try:
                data = json.loads(payload)
            except Exception:
                continue

            if isinstance(data, dict):
                if data.get("type") == "text":
                    content = data.get("content", "")
                    full_text += "" if content is None else str(content)
                elif data.get("type") == "done":
                    break

    except Exception as e:
        logger.error(f"collect_text_from_agent_stream failed: {e}")

    return full_text


# ---------- Endpoints ----------

@router.post("/stream_chat")
async def stream_chat(req: StreamChatRequest, request: Request):
    # SSE Streaming (Phase 3: Plan B - Canonical)
    # ストリーミングを復活させ、_safe_stream_generator で安全に中継・整形する。
    # API Router が唯一の入り口となる。

    rid = uuid.uuid4().hex[:8]
    logger.info(f"[CHAT_START] rid={rid} from={request.client.host} mode={req.mode}")
    logger.info(f"📨 Chat Request (SSE): {req.text[:20]}... (Thread: {req.thread_id}) Mode: {req.mode}")

    return StreamingResponse(
        _safe_stream_generator(
            input_text=req.text,
            thread_id=req.thread_id,
            voice_id=req.voice_id,
            image_data=req.image_data,
            mode=req.mode
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/livestream_chat")
async def livestream_chat(req: LivestreamChatRequest) -> Dict[str, Any]:
    """
    配信コメント用: JSON一括返却
    - 内部でストリームを消費してテキスト結合
    """
    text = (req.text or "").strip()
    if not text:
        return {"ok": True, "thread_id": req.thread_id, "response": ""}

    resp_text = await _collect_text_from_agent_stream(text, req.thread_id)
    return {"ok": True, "thread_id": req.thread_id, "response": resp_text}


@router.get("/history/{thread_id}")
async def get_history(thread_id: str):
    """
    会話履歴取得
    - A層の保存済み履歴を返す
    """
    try:
        from backend.services.chat_history_store import chat_history_store
        hist = await chat_history_store.get_history(thread_id)
        return {"ok": True, "history": hist}
    except Exception as e:
        logger.warning(f"History fetch failed: {e}")
        return {"ok": True, "history": []}


@router.delete("/history/{thread_id}")
async def delete_history(thread_id: str):
    """Delete chat history for a thread"""
    try:
        from backend.services.chat_history_store import chat_history_store
        await chat_history_store.clear_thread(thread_id)
        return {"ok": True, "thread_id": thread_id}
    except Exception as e:
        logger.warning(f"History delete failed: {e}")
        return {"ok": False, "thread_id": thread_id}


@router.get("/memories")
async def list_recent_memories(limit: int = 50, lang: Optional[str] = None):
    """Retrieve recent episodes/memories"""
    from backend.services.memory_manager import memory_manager

    memories = memory_manager.get_recent_memories(limit)
    if lang != "ja":
        return memories

    translated = 0
    for item in memories:
        if translated >= settings.MAX_TRANSLATE_ITEMS:
            break

        meta = item.get("metadata") or {}
        summary = item.get("summary", "")
        details = item.get("details", "") or ""

        summary_ja = meta.get("summary_ja")
        details_ja = meta.get("details_ja")

        if not summary_ja:
            summary_ja = await _translate_to_ja(summary)
        if details and not details_ja:
            details_ja = await _translate_to_ja(details)

        if summary_ja and summary_ja != summary:
            item["summary"] = summary_ja
        if details_ja and details_ja != details:
            item["details"] = details_ja

        if summary_ja or details_ja:
            new_meta = dict(meta)
            if summary_ja:
                new_meta["summary_ja"] = summary_ja
            if details_ja:
                new_meta["details_ja"] = details_ja
            if new_meta != meta and item.get("category") == "episode":
                await memory_manager.update_episode_metadata(item.get("id"), new_meta)
        translated += 1

    return memories


@router.post("/reset")
async def reset(thread_id: str = "default_thread") -> Dict[str, Any]:
    return {"ok": True, "thread_id": thread_id}

```

---

## File: `frontend/app/page.tsx`

```typescript
"use client";
import React, { useState, useEffect } from 'react';
import Sidebar from '@/components/Sidebar';
import ChatInterface from '@/components/ChatInterface';
import AvatarView from '@/components/AvatarView';
import MemoryExplorer from '@/components/MemoryExplorer';
import ProfileEditor from '@/components/ProfileEditor';
import SettingsPanel from '@/components/SettingsPanel';
import StatsPanel from '@/components/StatsPanel';
import { Menu, X } from 'lucide-react';

export default function Home() {
  const [activeTab, setActiveTab] = useState('chat'); // 'chat' | 'memories' | 'profile' | 'settings'
  const [isTalking, setIsTalking] = useState(false);
  const [emotion, setEmotion] = useState("neutral");
  const [agentMode, setAgentMode] = useState('normal'); // 'normal' | 'stream' | 'dev'
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // Load mode from localStorage on mount
  useEffect(() => {
    const savedMode = localStorage.getItem('agent_mode');
    if (savedMode) setAgentMode(savedMode);
  }, []);

  // Save mode when changed
  const handleModeChange = (mode: string) => {
    setAgentMode(mode);
    localStorage.setItem('agent_mode', mode);
  };

  // Close mobile menu when tab changes
  const handleTabChange = (tab: string) => {
    setActiveTab(tab);
    setMobileMenuOpen(false);
  };

  return (
    <main className="flex h-screen w-full overflow-hidden bg-[#0f0f12] text-white">
      {/* Mobile Menu Button */}
      <button
        className="md:hidden fixed top-3 left-3 z-50 p-2 rounded-xl glass"
        onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
      >
        {mobileMenuOpen ? <X size={24} /> : <Menu size={24} />}
      </button>

      {/* 1. Sidebar - Desktop: always visible, Mobile: overlay */}
      <div className="hidden md:block">
        <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />
      </div>

      {/* Mobile Sidebar Overlay */}
      {mobileMenuOpen && (
        <div className="md:hidden fixed inset-0 z-40">
          <div className="absolute inset-0 bg-black/60" onClick={() => setMobileMenuOpen(false)} />
          <div className="absolute left-0 top-0 h-full z-50">
            <Sidebar activeTab={activeTab} setActiveTab={handleTabChange} />
          </div>
        </div>
      )}

      {/* 2. Main Content Area */}
      <div className="flex-1 flex max-w-full relative">

        {/* Avatar Panel (Right Side by default or Split) */}
        {/* Let's do a split view: Left Chat, Right Avatar */}

        <div className="flex-1 flex flex-col h-full relative z-10 p-2 md:p-4">
          {/* Tab Content Routing */}
          {activeTab === 'chat' && (
            <div className="flex h-full gap-2 md:gap-4">
              {/* Chat Panel (Full width on mobile, 1/3 on XL) */}
              <div className="w-full xl:w-1/3 h-full flex flex-col glass rounded-2xl md:rounded-3xl overflow-hidden relative">
                {/* Background Effect */}
                <div className="absolute top-0 w-full h-32 bg-gradient-to-b from-blue-900/20 to-transparent pointer-events-none" />
                <ChatInterface
                  onStateChange={(talking, emo) => {
                    setIsTalking(talking);
                    setEmotion(emo);
                  }}
                  agentMode={agentMode} // Pass mode to chat
                />
              </div>

              {/* Avatar Panel (Right, Grows to fill space) */}
              <div className="hidden xl:block flex-1 h-full rounded-3xl overflow-hidden glass-panel">
                <AvatarView isTalking={isTalking} emotion={emotion} />
              </div>
            </div>
          )}

          {activeTab === 'memories' && (
            <div className="flex-1 glass rounded-2xl md:rounded-3xl p-4 md:p-8 overflow-y-auto">
              <MemoryExplorer />
            </div>
          )}

          {activeTab === 'profile' && (
            <div className="flex-1 glass rounded-2xl md:rounded-3xl p-4 md:p-8 overflow-y-auto">
              <ProfileEditor />
            </div>
          )}

          {activeTab === 'settings' && (
            <div className="flex-1 glass rounded-2xl md:rounded-3xl p-4 md:p-8 overflow-y-auto">
              <SettingsPanel currentMode={agentMode} onModeChange={handleModeChange} />
            </div>
          )}

          {activeTab === 'stats' && (
            <div className="flex-1 glass rounded-3xl overflow-hidden">
              <StatsPanel />
            </div>
          )}

          {activeTab !== 'chat' && activeTab !== 'memories' && activeTab !== 'settings' && activeTab !== 'profile' && activeTab !== 'stats' && (
            <div className="flex-1 glass rounded-2xl md:rounded-3xl p-4 md:p-8 flex items-center justify-center">
              <div className="text-center">
                <h2 className="text-3xl font-bold mb-2">準備中</h2>
                <p className="text-gray-500">{activeTab} モジュールは現在開発中です。</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}

```

---

## File: `frontend/components/AvatarView.tsx`

```typescript

"use client";
import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils, VRM } from '@pixiv/three-vrm';

interface AvatarProps {
    isTalking: boolean;
    emotion: string;
}

export default function AvatarView({ isTalking, emotion }: AvatarProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    // Using Ref for VRM to ensure the animation loop always has the latest instance
    const vrmRef = useRef<VRM | null>(null);
    const clockRef = useRef(new THREE.Clock());
    const headPoseRef = useRef({ x: 0, y: 0, z: 0 });
    const spinePoseRef = useRef({ x: 0, y: 0, z: 0 }); // Added for spine control
    const dissonanceTimerRef = useRef(0); // Timer for look-away animation

    useEffect(() => {
        if (!containerRef.current) return;

        // Scene Setup
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x0f0f12);

        // Camera
        const camera = new THREE.PerspectiveCamera(30, containerRef.current.clientWidth / containerRef.current.clientHeight, 0.1, 20.0);
        camera.position.set(0.0, 1.3, 1.4);

        // Renderer
        const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
        renderer.setSize(containerRef.current.clientWidth, containerRef.current.clientHeight);
        renderer.setPixelRatio(window.devicePixelRatio);
        containerRef.current.appendChild(renderer.domElement);

        // Light
        const light = new THREE.DirectionalLight(0xffffff);
        light.position.set(1.0, 1.0, 1.0).normalize();
        scene.add(light);
        const ambient = new THREE.AmbientLight(0x404040);
        scene.add(ambient);

        // Loader
        const loader = new GLTFLoader();
        loader.register((parser) => new VRMLoaderPlugin(parser));

        loader.load(
            '/avatar.vrm',
            (gltf) => {
                const vrm = gltf.userData.vrm;
                VRMUtils.removeUnnecessaryVertices(gltf.scene);
                VRMUtils.combineSkeletons(gltf.scene);

                vrm.scene.rotation.y = 0;
                scene.add(vrm.scene);
                vrmRef.current = vrm; // Set to Ref
                console.log("VRM Charged and Ready");
            },
            (progress) => console.log('Loading VRM...', 100.0 * (progress.loaded / progress.total), '%'),
            (error) => console.error("VRM Load Failed:", error)
        );

        // Animation Loop
        const animate = () => {
            requestAnimationFrame(animate);
            const delta = clockRef.current.getDelta();
            const vrm = vrmRef.current;

            if (vrm) {
                // --- 1. Override Pose (Every frame to beat constraints) ---
                const humanoid = vrm.humanoid;
                if (humanoid) {
                    const leftArm = humanoid.getNormalizedBoneNode('leftUpperArm');
                    const rightArm = humanoid.getNormalizedBoneNode('rightUpperArm');
                    const neck = humanoid.getNormalizedBoneNode('neck');
                    const spine = humanoid.getNormalizedBoneNode('spine');

                    if (leftArm) leftArm.rotation.z = -1.3; // Lower arm
                    if (rightArm) rightArm.rotation.z = 1.3;

                    if (neck) {
                        const pose = headPoseRef.current;
                        neck.rotation.x += (pose.x - neck.rotation.x) * 0.06;
                        neck.rotation.y += (pose.y - neck.rotation.y) * 0.06;
                        neck.rotation.z += (pose.z - neck.rotation.z) * 0.06;
                    }
                    if (spine) {
                        const pose = spinePoseRef.current;
                        spine.rotation.x += (pose.x - spine.rotation.x) * 0.05;
                    }
                }

                // --- 2. Update VRM ---
                vrm.update(delta);

                // --- 3. Idle Motion (Breathing) ---
                const s = Math.sin(clockRef.current.elapsedTime);
                vrm.scene.rotation.z = s * 0.005;

                // Blink Logic
                if (Math.random() < 0.005) {
                    vrm.expressionManager?.setValue('blink', 1.0);
                    setTimeout(() => vrm.expressionManager?.setValue('blink', 0.0), 100);
                }
            }

            renderer.render(scene, camera);
        };
        animate();

        // Resize Handler
        const handleResize = () => {
            if (!containerRef.current) return;
            camera.aspect = containerRef.current.clientWidth / containerRef.current.clientHeight;
            camera.updateProjectionMatrix();
            renderer.setSize(containerRef.current.clientWidth, containerRef.current.clientHeight);
        };
        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            renderer.dispose();
            if (containerRef.current?.contains(renderer.domElement)) {
                containerRef.current.removeChild(renderer.domElement);
            }
        };
    }, []);

    // --- Sync Emotion & Talking State (Runs on props change) ---
    useEffect(() => {
        const vrm = vrmRef.current;
        if (!vrm || !vrm.expressionManager) return;

        // Reset Expressions (Keep current one)
        const list = vrm.expressionManager.expressions;
        list.forEach(e => {
            if (e.expressionName !== 'blink' && e.expressionName !== 'aa') {
                vrm.expressionManager?.setValue(e.expressionName, 0);
            }
        });

        // Set Emotion
        let targetExpression = 'neutral';
        if (emotion === 'happy') targetExpression = 'happy';
        if (emotion === 'sad') targetExpression = 'sad';
        if (emotion === 'angry') targetExpression = 'angry';
        if (emotion === 'surprised') targetExpression = 'surprised';

        if (vrm.expressionManager.getExpression(targetExpression)) {
            vrm.expressionManager.setValue(targetExpression, 1.0);
        } else {
            // Fallback to joy if happy missing
            if (emotion === 'happy') vrm.expressionManager.setValue('joy', 1.0);
            else vrm.expressionManager.setValue('neutral', 1.0);
        }

        // Procedural head/body motion
        if (emotion === 'consent') {
            // 前傾姿勢で興味を示す
            headPoseRef.current = { x: -0.10, y: 0.0, z: 0.0 };
            spinePoseRef.current = { x: 0.15, y: 0.0, z: 0.0 }; // Lean forward
        } else if (emotion === 'dissonance') {
            // 視線を外し、首をかしげる動作を開始
            headPoseRef.current = { x: 0.0, y: 0.3, z: 0.15 }; // Look away + tilt
            spinePoseRef.current = { x: -0.05, y: 0.0, z: 0.0 }; // Slight recoil
            dissonanceTimerRef.current = Date.now();
        } else {
            // Reset
            headPoseRef.current = { x: 0.0, y: 0.0, z: 0.0 };
            spinePoseRef.current = { x: 0.0, y: 0.0, z: 0.0 };
        }
    }, [emotion]);

    // Custom Animation Loop handling for Dissonance Return
    useEffect(() => {
        let frameId: number;
        const behaviorLoop = () => {
            // Dissonanceの「視線を外して戻す」時間差挙動
            if (emotion === 'dissonance' && dissonanceTimerRef.current > 0) {
                const elapsed = Date.now() - dissonanceTimerRef.current;
                // 2.5秒後にゆっくり視線を戻し始める
                if (elapsed > 2500) {
                    headPoseRef.current = { x: 0.0, y: 0.0, z: 0.05 }; // まだ少し思案顔（首かしげ残し）
                }
                // 4秒後に完全復帰（ただし感情ステートが変わるまでは首かしげ維持）
                if (elapsed > 4000) {
                    // 完全に正面には戻さず、憂いを残す
                }
            }
            frameId = requestAnimationFrame(behaviorLoop);
        };
        behaviorLoop();
        return () => cancelAnimationFrame(frameId);
    }, [emotion]);

    // Lip Sync Animation Loop (Independent)
    useEffect(() => {
        let frameId: number;
        const lipLoop = () => {
            const vrm = vrmRef.current;
            if (vrm && vrm.expressionManager) {
                if (isTalking) {
                    const v = 0.2 + 0.4 * Math.sin(Date.now() / 60);
                    vrm.expressionManager.setValue('aa', v);
                } else {
                    vrm.expressionManager.setValue('aa', 0);
                }
            }
            frameId = requestAnimationFrame(lipLoop);
        };
        lipLoop();
        return () => cancelAnimationFrame(frameId);
    }, [isTalking]);

    return (
        <div className="w-full h-full glass-panel relative overflow-hidden rounded-2xl">
            <div ref={containerRef} className="w-full h-full" />
        </div>
    );
}

```

---

## File: `frontend/lib/api.ts`

```typescript
// API URL: Use relative path for same-origin access via Next.js rewrites
// This works with Tailscale Serve HTTPS and eliminates CORS issues
export const API_URL = "/api";

export interface ChatMessage {
    id: string;
    role: 'user' | 'ai' | 'system';
    content: string;
    timestamp?: string;
    type?: 'text' | 'audio' | 'image';
    image?: string;
    kind?: 'dream';  // 夢メッセージの識別用
    meta?: Record<string, any>;  // 追加メタデータ
}

export const fetchHistory = async (threadId: string) => {
    const res = await fetch(`${API_URL}/history/${threadId}`);
    return res.json();
};

export const clearHistory = async (threadId: string) => {
    await fetch(`${API_URL}/history/${threadId}`, { method: 'DELETE' });
};

export const fetchConfig = async () => {
    const res = await fetch(`${API_URL}/config`);
    return res.json();
};

/**
 * 静的ファイルのURLを組み立てる。
 * - 絶対URLはそのまま返す
 * - /static/... の相対パスはそのまま返す（Next.js rewriteでバックエンドにプロキシされる）
 * - パスが /static で始まらない場合は /static を付与
 */
export const getStaticUrl = (path: string): string => {
    if (!path) return "";
    // 絶対URL（http://... or https://...）はそのまま
    if (path.startsWith("http://") || path.startsWith("https://")) {
        return path;
    }
    // 既に /static で始まっていればそのまま
    if (path.startsWith("/static")) {
        return path;
    }
    // それ以外は /static を付与
    return `/static${path.startsWith("/") ? "" : "/"}${path}`;
};

```

---

