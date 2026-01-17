from pydantic import BaseModel, Field
from typing import Literal, Optional, Any, Dict
import time
import uuid

class AgentEvent(BaseModel):
    """
    Core と Router 間の通信プロトコルを定義するイベントモデル。
    data: ...\n\n のSSE形式ではなく、純粋な辞書としてやり取りする。
    """
    type: Literal["text", "audio", "error", "done", "debug", "meta", "dream"]
    content: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    url: Optional[str] = None      # audio用（URL配信方式）
    seq: int = 0
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    ts: float = Field(default_factory=lambda: time.time())
