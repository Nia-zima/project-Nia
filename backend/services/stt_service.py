from __future__ import annotations

import asyncio
import subprocess
import tempfile
import os
from os import getenv
from typing import Any
from pathlib import Path

from backend.core.logger import logger


def _env_str(key: str, default: str) -> str:
    v = getenv(key)
    return v if v is not None and str(v).strip() != "" else default


def _env_int(key: str, default: int) -> int:
    v = getenv(key)
    try:
        return int(v) if v is not None and str(v).strip() != "" else default
    except Exception:
        return default


def _env_bool(key: str, default: bool) -> bool:
    v = getenv(key)
    if v is None or str(v).strip() == "":
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


class STTService:
    """
    Step 3 scope:
    - Accept container bytes from MediaRecorder chunks (webm/ogg).
    - Decode to wav(16k/mono) via ffmpeg.
    - Run optional faster-whisper transcription.
    """

    def __init__(self) -> None:
        self.provider = _env_str("STT_PROVIDER", "none").strip().lower()
        self.model_name = _env_str("STT_MODEL", "small")
        self.model_path = _env_str("STT_MODEL_PATH", "").strip()
        self.local_files_only = _env_bool("STT_LOCAL_FILES_ONLY", True)
        self.language = _env_str("STT_LANGUAGE", "ja")
        self.compute_type = _env_str("STT_COMPUTE_TYPE", "int8")
        self.device = _env_str("STT_DEVICE", "cpu")
        self.ffmpeg_bin = _env_str("FFMPEG_BIN", "ffmpeg")
        self.allow_omp_duplicate = _env_bool("STT_ALLOW_OMP_DUPLICATE", True)
        self.omp_num_threads = _env_int("STT_OMP_NUM_THREADS", 1)
        self.max_buffer_bytes = _env_int("STT_MAX_BUFFER_BYTES", 4 * 1024 * 1024)
        self.partial_interval_chunks = _env_int("STT_PARTIAL_INTERVAL_CHUNKS", 8)
        self.partial_min_buffer_bytes = _env_int("STT_PARTIAL_MIN_BUFFER_BYTES", 120 * 1024)
        self.partial_max_buffer_bytes = _env_int("STT_PARTIAL_MAX_BUFFER_BYTES", 800 * 1024)
        self._model = None
        self._lock = asyncio.Lock()

    async def _ensure_model(self):
        if self.provider != "faster_whisper":
            return None
        if self._model is not None:
            return self._model
        async with self._lock:
            if self._model is not None:
                return self._model
            # Windowsでlibomp/libiomp衝突が起きるケースの回避。
            # 競合を根本解決できる構成が理想だが、PoC段階では起動不能を避ける。
            if self.allow_omp_duplicate:
                os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
            if self.omp_num_threads > 0:
                os.environ.setdefault("OMP_NUM_THREADS", str(self.omp_num_threads))
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            try:
                from faster_whisper import WhisperModel
            except Exception:
                logger.warning("[STT] faster_whisper is not installed; STT_PROVIDER=faster_whisper is unavailable")
                return None
            try:
                model_source = self.model_path or self.model_name
                self._model = WhisperModel(
                    model_source,
                    device=self.device,
                    compute_type=self.compute_type,
                    local_files_only=self.local_files_only,
                )
                logger.info(
                    "[STT] faster-whisper model loaded source=%s device=%s local_only=%s",
                    model_source,
                    self.device,
                    str(self.local_files_only),
                )
            except Exception:
                logger.exception(
                    "[STT] failed to load faster-whisper source=%s",
                    self.model_path or self.model_name,
                )
                self._model = None
            return self._model

    def _ffmpeg_input_format(self, mime_type: str) -> str:
        m = (mime_type or "").lower()
        if "ogg" in m:
            return "ogg"
        if "webm" in m:
            return "webm"
        return "webm"

    def _decode_to_wav_bytes(self, audio_bytes: bytes, mime_type: str) -> bytes | None:
        if not audio_bytes:
            return None
        input_format = self._ffmpeg_input_format(mime_type)
        cmd = [
            self.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            input_format,
            "-i",
            "pipe:0",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-f",
            "wav",
            "pipe:1",
        ]
        cmd_auto = [
            self.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-f",
            "wav",
            "pipe:1",
        ]

        def _run_ffmpeg(c: list[str]):
            return subprocess.run(
                c,
                input=audio_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=10,
            )
        try:
            proc = _run_ffmpeg(cmd)
        except FileNotFoundError:
            logger.warning("[STT] ffmpeg not found; cannot decode %s input", input_format)
            return None
        except subprocess.TimeoutExpired:
            logger.warning("[STT] ffmpeg timed out decoding %s input", input_format)
            return None
        except Exception:
            logger.exception("[STT] ffmpeg decode exception")
            return None

        if proc.returncode != 0:
            # MIME推定が外れたケースを救済するため、入力フォーマット自動判定で再試行
            try:
                proc_auto = _run_ffmpeg(cmd_auto)
            except Exception:
                proc_auto = None
            if proc_auto is not None and proc_auto.returncode == 0 and proc_auto.stdout:
                return proc_auto.stdout

            err = proc.stderr.decode("utf-8", errors="ignore")[:200]
            logger.debug("[STT] ffmpeg decode failed code=%s err=%s", proc.returncode, err)
            return None
        return proc.stdout if proc.stdout else None

    @staticmethod
    def _wav_rms(wav_bytes: bytes) -> float:
        """Calculate RMS of 16-bit PCM WAV (skip 44-byte header)."""
        import struct
        if len(wav_bytes) <= 44:
            return 0.0
        pcm = wav_bytes[44:]
        n_samples = len(pcm) // 2
        if n_samples == 0:
            return 0.0
        sum_sq = 0.0
        for i in range(0, n_samples * 2, 2):
            sample = struct.unpack_from("<h", pcm, i)[0]
            sum_sq += sample * sample
        return (sum_sq / n_samples) ** 0.5

    # Whisper Japanese hallucination patterns — these appear when audio is
    # silent / low-energy and the model "invents" common training-data phrases.
    _HALLUCINATION_RE = None

    @classmethod
    def _is_hallucination(cls, text: str) -> bool:
        import re
        if cls._HALLUCINATION_RE is None:
            patterns = [
                r"ご視聴ありがとうございました",
                r"ありがとうございました",
                r"お疲れ様でした",
                r"チャンネル登録",
                r"高評価",
                r"よろしくお願いします",
                r"字幕は自動生成",
                r"ご覧いただき",
                r"最後までご覧",
                r"それではまた",
                r"おやすみなさい",
                r"次の動画でお会いしましょう",
                r"バイバイ",
            ]
            cls._HALLUCINATION_RE = re.compile(
                r"^[\s。、！？!?\.\s]*(" + "|".join(patterns) + r")[\s。、！？!?\.\s]*$"
            )
        return bool(cls._HALLUCINATION_RE.match(text.strip()))

    def _transcribe_wav_sync(self, wav_bytes: bytes) -> str:
        if not wav_bytes:
            return ""
        model = self._model
        if model is None:
            return ""

        # Diagnostic: check WAV size and energy
        rms = self._wav_rms(wav_bytes)
        wav_duration_est = max(0, len(wav_bytes) - 44) / (16000 * 2)
        logger.info(
            "[STT] wav_bytes=%d duration_est=%.2fs rms=%.1f",
            len(wav_bytes), wav_duration_est, rms,
        )
        if rms < 1.0:
            logger.warning("[STT] WAV appears silent (rms=%.1f) — audio pipeline issue?", rms)

        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_bytes)
                tmp_path = f.name

            def _run_transcribe(vad: bool) -> str:
                vad_params = dict(
                    threshold=0.20,
                    min_silence_duration_ms=350,
                    speech_pad_ms=200,
                ) if vad else None
                segments, _info = model.transcribe(
                    tmp_path,
                    language=self.language,
                    beam_size=1,
                    vad_filter=vad,
                    vad_parameters=vad_params,
                    condition_on_previous_text=False,
                    without_timestamps=True,
                    # No initial_prompt — it primes hallucinations
                )
                texts: list[str] = []
                seg_total = 0
                for seg in segments:
                    seg_total += 1
                    t = str(getattr(seg, "text", "") or "").strip()
                    if not t:
                        continue
                    no_speech = getattr(seg, "no_speech_prob", 0.0) or 0.0
                    avg_logprob = getattr(seg, "avg_logprob", 0.0) or 0.0
                    logger.debug(
                        "[STT] seg: no_speech=%.3f avg_logprob=%.3f text=%s",
                        no_speech, avg_logprob, t[:60],
                    )
                    # Conservative drop only for clearly invalid segments.
                    if no_speech > 0.98:
                        logger.info("[STT] drop segment (no_speech=%.2f): %s", no_speech, t[:60])
                        continue
                    if avg_logprob < -2.5:
                        logger.info("[STT] drop segment (avg_logprob=%.2f): %s", avg_logprob, t[:60])
                        continue
                    texts.append(t)
                result = " ".join(texts).strip()
                logger.info(
                    "[STT] transcribe vad=%s seg_total=%d kept=%d text=%s",
                    vad,
                    seg_total,
                    len(texts),
                    result[:80] if result else "(empty)",
                )
                return result

            # まずVADありで実行し、空ならVADなしで再試行（短発話救済）
            text = _run_transcribe(True)
            if not text:
                text = _run_transcribe(False)

            # Final hallucination filter
            if text and self._is_hallucination(text):
                logger.info("[STT] filtered hallucination: %s", text)
                return ""
            return text
        except Exception:
            logger.exception("[STT] faster-whisper transcribe failed")
            return ""
        finally:
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

    async def transcribe_container_bytes(self, audio_bytes: bytes, mime_type: str) -> dict[str, Any]:
        if not audio_bytes:
            return {"ok": True, "text": "", "provider": self.provider}
        if self.provider != "faster_whisper":
            return {"ok": False, "text": "", "provider": self.provider, "reason": "stt provider disabled"}

        model = await self._ensure_model()
        if model is None:
            return {"ok": False, "text": "", "provider": self.provider, "reason": "stt model unavailable"}

        logger.debug("[STT] decode start input_bytes=%d mime=%s", len(audio_bytes), mime_type)
        wav_bytes = await asyncio.to_thread(self._decode_to_wav_bytes, audio_bytes, mime_type)
        if not wav_bytes:
            return {"ok": False, "text": "", "provider": self.provider, "reason": "audio decode failed"}

        text = await asyncio.to_thread(self._transcribe_wav_sync, wav_bytes)
        return {"ok": True, "text": text, "provider": self.provider}


stt_service = STTService()
