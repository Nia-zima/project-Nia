"""
Smoke test for Qwen3-TTS (VoiceDesign).

Usage:
  python -m scripts.qwen3_tts_smoke
"""
from __future__ import annotations

import soundfile as sf

from backend.services.tts.qwen3_tts_engine import qwen3_tts_engine


def main() -> None:
    print("[INFO] Model Download/Loading...")
    qwen3_tts_engine.load_model(model_size="1.7B", model_type="VoiceDesign")
    text = "こんにちは、ニアです。"
    print(f"[INFO] Generating Audio for: {text!r}")
    result = qwen3_tts_engine.voice_design(
        text=text,
        language="ja",
        voice_description="中性的で落ち着いた声。感情を誇張せず、自然なトーン。",
    )
    wav, sr = sf.read(result.wav_path)
    print(f"[INFO] Waveform generated. Shape: {wav.shape}")
    sf.write("out.wav", wav, sr)
    print("[SUCCESS] out.wav saved.")


if __name__ == "__main__":
    main()
