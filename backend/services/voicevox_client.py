
import requests
from typing import List, Dict, Optional

from backend.core.config import settings
from backend.core.logger import logger

class VoicevoxClient:
    def __init__(self, base_url: str = "http://127.0.0.1:50021"):
        self.base_url = base_url

    def generate_audio(self, text: str, speaker_id: int) -> Optional[bytes]:
        if not text: return None
        logger.info(f"[VOICEVOX] generate_audio speaker={speaker_id} text_len={len(text)} text='{text[:50]}...'")
        try:
            # 1. Audio Query
            query_res = requests.post(
                f"{self.base_url}/audio_query", 
                params={"text": text, "speaker": speaker_id},
                timeout=2
            )
            query_res.raise_for_status()
            query_data = query_res.json()

            # 2. Synthesis
            synth_res = requests.post(
                f"{self.base_url}/synthesis",
                params={"speaker": speaker_id},
                json=query_data,
                timeout=5
            )
            synth_res.raise_for_status()
            return synth_res.content
            
        except requests.ConnectionError:
            logger.warning(f"Voicevox Connection Failed at {self.base_url}")
            return None
        except Exception as e:
            logger.error(f"Voicevox Gen Error: {e}", exc_info=True)
            return None

    def generate_audio_to_file(self, text: str, speaker_id: int, thread_id: str = "default") -> Optional[str]:
        """
        Generate audio and save to static/audio/{thread_id}/{uuid}.wav.
        Returns the URL path (e.g., /static/audio/default/abc123.wav) or None on failure.
        """
        import uuid as uuid_mod

        audio_bytes = self.generate_audio(text, speaker_id)
        if not audio_bytes:
            return None
        
        # Determine save path
        base_dir = settings.STATIC_DIR / "audio" / thread_id
        base_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"{uuid_mod.uuid4().hex}.wav"
        filepath = base_dir / filename
        
        try:
            with open(filepath, "wb") as f:
                f.write(audio_bytes)
            
            # Return URL path (relative to server root)
            url = f"/static/audio/{thread_id}/{filename}"
            logger.info(f"[AUDIO_SAVED] {filepath} url={url}")
            return url
        except Exception as e:
            logger.error(f"Failed to save audio file: {e}")
            return None

    def get_speakers(self) -> List[Dict]:
        try:
            res = requests.get(f"{self.base_url}/speakers", timeout=5)
            res.raise_for_status()
            speakers_data = res.json()
            
            simple_list = []
            for speaker in speakers_data:
                name = speaker['name']
                for style in speaker.get('styles', []):
                    simple_list.append({
                        "id": style['id'],
                        "name": f"{name} ({style['name']})"
                    })
            return simple_list
        except Exception as e:
            logger.warning(f"Voicevox Speaker List Error: {e}. Using fallback.")
            return self._fallback_speakers()

    def _fallback_speakers(self):
        return [
            {"name": "四国めたん (ノーマル)", "id": 2},
            {"name": "ずんだもん (ノーマル)", "id": 3},
            {"name": "春日部つむぎ (ノーマル)", "id": 8},
            {"name": "冥鳴ひまり (ノーマル)", "id": 14},
        ]

voicevox_client = VoicevoxClient()
