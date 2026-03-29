from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock


@dataclass
class AvatarState:
    """In-memory, lightweight state for public mood/flags."""
    current_emotion: str = "neutral"
    current_mode: str = "normal"
    _lock: Lock = field(default_factory=Lock, repr=False)

    def set_emotion(self, emotion: str) -> None:
        if not emotion:
            return
        with self._lock:
            self.current_emotion = emotion

    def set_mode(self, mode: str) -> None:
        if not mode:
            return
        with self._lock:
            self.current_mode = mode


avatar_state = AvatarState()
