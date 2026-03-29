from dataclasses import dataclass
from typing import Dict
from backend.core.config import settings

@dataclass(frozen=True)
class RetentionConfig:
    profile: str
    th_promote: float
    th_background: float
    grace_days: float
    half_life_days: Dict[str, float]  # CONSENT/PONDERING/DISSONANCE/DEFAULT

PROFILES = {
    "prod": RetentionConfig(
        profile="prod",
        th_promote=0.70,
        th_background=0.10,
        grace_days=1.0,
        half_life_days={"CONSENT": 30.0, "PONDERING": 7.0, "DISSONANCE": 3.0, "DEFAULT": 5.0},
    ),
    # 開発用：遷移を早く見たい時だけ
    "fast": RetentionConfig(
        profile="fast",
        th_promote=0.70,
        th_background=0.10,
        grace_days=0.0,
        half_life_days={"CONSENT": 3.0, "PONDERING": 1.0, "DISSONANCE": 0.5, "DEFAULT": 1.0},
    ),
}

def get_retention_config():
    prof = getattr(settings, "RETENTION_PROFILE", "prod")
    return PROFILES.get(prof, PROFILES["prod"])
