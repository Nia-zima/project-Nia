"""Tests for backend/services/stt_service.py."""
from __future__ import annotations

import struct
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from backend.services.stt_service import STTService


# ── _ffmpeg_input_format ─────────────────────────────────────────

class TestFfmpegInputFormat:
    def setup_method(self):
        with patch.dict("os.environ", {}, clear=False):
            self.stt = STTService()

    def test_webm(self):
        assert self.stt._ffmpeg_input_format("audio/webm") == "webm"

    def test_ogg(self):
        assert self.stt._ffmpeg_input_format("audio/ogg") == "ogg"

    def test_ogg_opus(self):
        assert self.stt._ffmpeg_input_format("audio/ogg; codecs=opus") == "ogg"

    def test_webm_opus(self):
        assert self.stt._ffmpeg_input_format("audio/webm; codecs=opus") == "webm"

    def test_empty(self):
        assert self.stt._ffmpeg_input_format("") == "webm"

    def test_none(self):
        assert self.stt._ffmpeg_input_format(None) == "webm"

    def test_unknown(self):
        assert self.stt._ffmpeg_input_format("audio/mp3") == "webm"


# ── _wav_rms ─────────────────────────────────────────────────────

class TestWavRms:
    def test_empty_wav(self):
        """WAV with only header returns 0."""
        assert STTService._wav_rms(b"\x00" * 44) == 0.0

    def test_short_wav(self):
        """WAV shorter than header returns 0."""
        assert STTService._wav_rms(b"\x00" * 20) == 0.0

    def test_silent_wav(self):
        """All-zero PCM returns 0."""
        header = b"\x00" * 44
        pcm = b"\x00\x00" * 100  # 100 silent samples
        assert STTService._wav_rms(header + pcm) == 0.0

    def test_nonzero_rms(self):
        """Non-silent PCM returns positive RMS."""
        header = b"\x00" * 44
        # Create samples with value 1000 (little-endian s16)
        sample_val = 1000
        pcm = struct.pack("<h", sample_val) * 50
        rms = STTService._wav_rms(header + pcm)
        assert rms == pytest.approx(1000.0, abs=0.1)


# ── _is_hallucination ───────────────────────────────────────────

class TestIsHallucination:
    def test_hallucination_detected(self):
        assert STTService._is_hallucination("ご視聴ありがとうございました") is True
        assert STTService._is_hallucination("チャンネル登録") is True
        assert STTService._is_hallucination("  ありがとうございました  ") is True

    def test_normal_text(self):
        assert STTService._is_hallucination("今日はいい天気ですね") is False
        assert STTService._is_hallucination("ゲームの話をしよう") is False

    def test_empty(self):
        assert STTService._is_hallucination("") is False

    def test_hallucination_with_punctuation(self):
        assert STTService._is_hallucination("ご視聴ありがとうございました。") is True


# ── _pcm_to_wav ──────────────────────────────────────────────────

class TestPcmToWav:
    def test_header_structure(self):
        pcm = b"\x00\x01" * 100  # 200 bytes of PCM
        wav = STTService._pcm_to_wav(pcm)
        # RIFF header
        assert wav[:4] == b"RIFF"
        # WAVE format
        assert wav[8:12] == b"WAVE"
        # fmt chunk
        assert wav[12:16] == b"fmt "
        # data chunk
        assert wav[36:40] == b"data"
        # data size
        data_size = struct.unpack_from("<I", wav, 40)[0]
        assert data_size == len(pcm)
        # Total size
        riff_size = struct.unpack_from("<I", wav, 4)[0]
        assert riff_size == 36 + len(pcm)
        # PCM data preserved
        assert wav[44:] == pcm

    def test_empty_pcm(self):
        wav = STTService._pcm_to_wav(b"")
        assert wav[:4] == b"RIFF"
        assert len(wav) == 44  # header only


# ── transcribe_container_bytes ───────────────────────────────────

class TestTranscribeContainerBytes:
    @pytest.mark.asyncio
    async def test_empty_bytes(self):
        stt = STTService()
        result = await stt.transcribe_container_bytes(b"", "audio/webm")
        assert result["ok"] is True
        assert result["text"] == ""

    @pytest.mark.asyncio
    async def test_provider_disabled(self):
        stt = STTService()
        stt.provider = "none"
        result = await stt.transcribe_container_bytes(b"\xff" * 100, "audio/webm")
        assert result["ok"] is False
        assert "disabled" in result["reason"]

    @pytest.mark.asyncio
    async def test_model_unavailable(self):
        stt = STTService()
        stt.provider = "faster_whisper"
        stt._model = None
        with patch.object(stt, "_ensure_model", new_callable=AsyncMock, return_value=None):
            result = await stt.transcribe_container_bytes(b"\xff" * 100, "audio/webm")
            assert result["ok"] is False
            assert "unavailable" in result["reason"]

    @pytest.mark.asyncio
    async def test_decode_failure(self):
        stt = STTService()
        stt.provider = "faster_whisper"
        mock_model = MagicMock()
        stt._model = mock_model
        with patch.object(stt, "_ensure_model", new_callable=AsyncMock, return_value=mock_model), \
             patch.object(stt, "_decode_to_wav_bytes", return_value=None):
            result = await stt.transcribe_container_bytes(b"\xff" * 100, "audio/webm")
            assert result["ok"] is False
            assert "decode" in result["reason"]

    @pytest.mark.asyncio
    async def test_success(self):
        stt = STTService()
        stt.provider = "faster_whisper"
        mock_model = MagicMock()
        stt._model = mock_model
        with patch.object(stt, "_ensure_model", new_callable=AsyncMock, return_value=mock_model), \
             patch.object(stt, "_decode_to_wav_bytes", return_value=b"\x00" * 100), \
             patch.object(stt, "_transcribe_wav_sync", return_value="テスト音声"):
            result = await stt.transcribe_container_bytes(b"\xff" * 100, "audio/webm")
            assert result["ok"] is True
            assert result["text"] == "テスト音声"


# ── transcribe_pcm_bytes ─────────────────────────────────────────

class TestTranscribePcmBytes:
    @pytest.mark.asyncio
    async def test_empty_bytes(self):
        stt = STTService()
        result = await stt.transcribe_pcm_bytes(b"")
        assert result["ok"] is True
        assert result["text"] == ""

    @pytest.mark.asyncio
    async def test_provider_disabled(self):
        stt = STTService()
        stt.provider = "none"
        result = await stt.transcribe_pcm_bytes(b"\x00" * 100)
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_success(self):
        stt = STTService()
        stt.provider = "faster_whisper"
        mock_model = MagicMock()
        stt._model = mock_model
        with patch.object(stt, "_ensure_model", new_callable=AsyncMock, return_value=mock_model), \
             patch.object(stt, "_transcribe_wav_sync", return_value="PCMテスト"):
            result = await stt.transcribe_pcm_bytes(b"\x00\x01" * 100)
            assert result["ok"] is True
            assert result["text"] == "PCMテスト"
