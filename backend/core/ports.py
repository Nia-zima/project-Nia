from __future__ import annotations

from typing import Protocol, Optional, Iterable


class MemoryGateway(Protocol):
    async def recall_short(self, query: str, *, limit: int = 3) -> list[dict]:
        ...

    async def get_long_term(self, thread_id: str, *, limit: int = 8) -> dict:
        ...

    async def get_history(self, thread_id: str, *, limit: int = 60) -> list[dict]:
        ...

class CheckpointerGateway(Protocol):
    async def get_async_checkpointer_conn(self):
        ...

class MemoryCaptureGateway(Protocol):
    async def insert_capture(self, capture: dict) -> Optional[str]:
        ...

    async def update_capture_retention(self, capture_id: str, retention: float, stage: str) -> None:
        ...

    async def sweep_and_promote(self, thread_id: str, *, mode: str = "light", limit: int = 25) -> None:
        ...

    def _initial_retention(self, state_tag: Optional[str], surprise: Optional[float], keywords: list[str] | None, entities: list[str] | None) -> float:
        ...

class CaptureBuilderGateway(Protocol):
    def build_capture(self, *, thread_id: str, raw_text: str, state_tag: Optional[str], emotion_tags: Optional[list[str]] = None, refs: Optional[dict] = None) -> dict:
        ...

class VectorGateway(Protocol):
    async def register_candidate(self, text: str, meta: dict, collection: str) -> None:
        ...


class HistoryGateway(Protocol):
    async def get_history(self, thread_id: str, *, limit: int = 60) -> list[dict]:
        ...


class InnerMonologueLogger(Protocol):
    def log(self, data: dict) -> None:
        ...


class ToolRegistry(Protocol):
    def get_tools(self) -> list:
        ...


class ThoughtGateway(Protocol):
    async def reflect(self, vision_data: dict, hearing_data: dict, *, use_llm: bool = True) -> dict:
        ...


class TelemetrySink(Protocol):
    async def event(self, thread_id: str, event_type: str, payload: dict) -> None:
        ...


class TTSGateway(Protocol):
    async def generate_audio_url(self, text: str, voice_id: str, thread_id: str, stream_id: Optional[str] = None) -> Optional[str]:
        ...

    async def generate_audio(self, text: str, voice_id: str) -> Optional[bytes]:
        ...

    async def get_audio_meta(self, url: str) -> Optional[dict]:
        ...


class VisionGateway(Protocol):
    async def build_user_input(self, text: str, image_data: Optional[str]) -> str:
        ...


class AgentOrchestrator(Protocol):
    async def stream_chat(self, *, input_text: str, thread_id: str, voice_id: str, image_data: Optional[str], mode: str, stream_id: Optional[str], message_id: Optional[str]) -> Iterable[dict]:
        ...
