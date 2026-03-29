import asyncio
from collections import defaultdict, deque
from typing import Any, AsyncGenerator, Deque, Dict, Set


class TTSEventBus:
    def __init__(self, backlog_size: int = 50) -> None:
        self._backlog_size = max(1, int(backlog_size))
        self._backlog: Dict[str, Deque[dict]] = defaultdict(lambda: deque(maxlen=self._backlog_size))
        self._subscribers: Dict[str, Set[asyncio.Queue]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def publish(self, thread_id: str, event: Dict[str, Any]) -> None:
        if not thread_id:
            return
        async with self._lock:
            self._backlog[thread_id].append(event)
            subscribers = list(self._subscribers.get(thread_id, set()))
        for q in subscribers:
            q.put_nowait(event)

    async def subscribe(self, thread_id: str) -> AsyncGenerator[dict, None]:
        if not thread_id:
            return
        q: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._subscribers[thread_id].add(q)
            # 再接続時にバックログから直近のイベントを送信
            backlog = list(self._backlog.get(thread_id, []))

        try:
            # バックログから直近のイベントを配信（再接続時の欠損対策）
            for ev in backlog[-5:]:  # 直近5件のみ
                yield ev
            while True:
                ev = await q.get()
                yield ev
        finally:
            async with self._lock:
                subs = self._subscribers.get(thread_id)
                if subs and q in subs:
                    subs.remove(q)
                if subs is not None and not subs:
                    self._subscribers.pop(thread_id, None)


tts_event_bus = TTSEventBus(backlog_size=50)
