from __future__ import annotations

import base64
import io
import math
import multiprocessing as mp
import queue
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore


HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _safe_executor_loop(in_q: mp.Queue, out_q: mp.Queue, stop_event: mp.Event) -> None:
    """
    Safety executor process.
    - Validates commands
    - Blocks out-of-canvas coordinates
    - Blocks command bursts
    """
    recent = deque(maxlen=128)
    max_per_sec = 12

    while not stop_event.is_set():
        try:
            item = in_q.get(timeout=0.2)
        except queue.Empty:
            continue
        except Exception:
            continue

        now = time.time()
        while recent and now - recent[0] > 1.0:
            recent.popleft()
        if len(recent) >= max_per_sec:
            out_q.put(
                {
                    "session_id": item.get("session_id"),
                    "accepted": False,
                    "reason": "rate_limited",
                    "command": item.get("command"),
                    "ts": now,
                }
            )
            continue

        cmd = item.get("command") or {}
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)

        accepted, reason, normalized = _validate_command(cmd, width=width, height=height)
        out_q.put(
            {
                "session_id": item.get("session_id"),
                "accepted": accepted,
                "reason": reason,
                "command": normalized,
                "ts": now,
            }
        )
        if accepted:
            recent.append(now)


def _validate_color(value: Any) -> bool:
    return isinstance(value, str) and bool(HEX_COLOR_RE.match(value))


def _validate_int(value: Any) -> bool:
    return isinstance(value, int) or (isinstance(value, float) and float(value).is_integer())


def _in_bounds(x: int, y: int, *, width: int, height: int) -> bool:
    return 0 <= x <= width and 0 <= y <= height


def _validate_command(cmd: dict, *, width: int, height: int) -> tuple[bool, str, dict]:
    kind = str(cmd.get("cmd") or "").strip().lower()
    if width <= 0 or height <= 0:
        return False, "invalid_canvas_size", cmd

    if kind == "fill":
        color = cmd.get("color")
        if not _validate_color(color):
            return False, "invalid_color", cmd
        return True, "ok", {"cmd": "fill", "color": color}

    if kind == "line":
        x1 = cmd.get("x1")
        y1 = cmd.get("y1")
        x2 = cmd.get("x2")
        y2 = cmd.get("y2")
        brush = cmd.get("brush")
        color = cmd.get("color")
        if not all(_validate_int(v) for v in (x1, y1, x2, y2, brush)):
            return False, "invalid_numeric", cmd
        x1i, y1i, x2i, y2i, brushi = int(x1), int(y1), int(x2), int(y2), int(brush)
        if not (_in_bounds(x1i, y1i, width=width, height=height) and _in_bounds(x2i, y2i, width=width, height=height)):
            return False, "out_of_bounds", cmd
        if not (1 <= brushi <= 64):
            return False, "invalid_brush", cmd
        if not _validate_color(color):
            return False, "invalid_color", cmd
        return True, "ok", {"cmd": "line", "x1": x1i, "y1": y1i, "x2": x2i, "y2": y2i, "brush": brushi, "color": color}

    return False, "unknown_command", cmd


@dataclass
class DrawSession:
    session_id: str
    prompt: str
    width: int
    height: int
    interval_sec: float
    max_strokes: int
    timeout_sec: int
    started_at: float
    active: bool = True
    stop_reason: Optional[str] = None
    emergency_stop: bool = False
    last_observation_ts: float = 0.0
    last_plan_ts: float = 0.0
    observation_dark_ratio: float = 0.0
    planned_count: int = 0
    sent_count: int = 0
    rejected_count: int = 0
    next_seq: int = 0
    command_buffer: Optional[list] = None

    def __post_init__(self) -> None:
        if self.command_buffer is None:
            self.command_buffer = []


class DrawAgentService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._session: Optional[DrawSession] = None
        self._in_q: Optional[mp.Queue] = None
        self._out_q: Optional[mp.Queue] = None
        self._proc: Optional[mp.Process] = None
        self._proc_stop: Optional[mp.Event] = None
        self._planner_stop = threading.Event()
        self._planner_thread: Optional[threading.Thread] = None

    def _ensure_executor(self) -> None:
        if self._proc and self._proc.is_alive():
            return
        self._in_q = mp.Queue()
        self._out_q = mp.Queue()
        self._proc_stop = mp.Event()
        self._proc = mp.Process(
            target=_safe_executor_loop,
            args=(self._in_q, self._out_q, self._proc_stop),
            daemon=True,
            name="draw_safe_executor",
        )
        self._proc.start()

    def _ensure_planner(self) -> None:
        if self._planner_thread and self._planner_thread.is_alive():
            return
        self._planner_stop.clear()
        self._planner_thread = threading.Thread(target=self._planner_loop, daemon=True, name="draw_planner")
        self._planner_thread.start()

    def start_session(
        self,
        *,
        prompt: str,
        width: int,
        height: int,
        interval_sec: float = 1.2,
        max_strokes: int = 40,
        timeout_sec: int = 180,
    ) -> dict:
        width = max(128, min(1920, int(width)))
        height = max(128, min(1080, int(height)))
        interval_sec = max(1.0, min(2.0, float(interval_sec)))
        max_strokes = max(1, min(300, int(max_strokes)))
        timeout_sec = max(15, min(600, int(timeout_sec)))

        self._ensure_executor()
        self._ensure_planner()

        session = DrawSession(
            session_id=uuid.uuid4().hex[:12],
            prompt=(prompt or "").strip(),
            width=width,
            height=height,
            interval_sec=interval_sec,
            max_strokes=max_strokes,
            timeout_sec=timeout_sec,
            started_at=time.time(),
        )
        with self._lock:
            self._session = session
        return self.get_state()

    def stop_session(self, *, emergency: bool = False, reason: str = "stopped_by_user") -> dict:
        with self._lock:
            s = self._session
            if not s:
                return {"active": False, "session_id": None, "stop_reason": "no_session"}
            s.active = False
            s.emergency_stop = bool(emergency)
            s.stop_reason = "emergency_stop" if emergency else reason
        return self.get_state()

    def observe(self, *, session_id: str, image_data: str) -> dict:
        with self._lock:
            s = self._session
            if not s or s.session_id != session_id:
                return {"ok": False, "reason": "session_not_found"}
            if not s.active:
                return {"ok": False, "reason": "session_inactive"}
            s.last_observation_ts = time.time()
            s.observation_dark_ratio = self._estimate_dark_ratio(image_data)
        return {"ok": True}

    def get_state(self) -> dict:
        self._drain_executor_events()
        with self._lock:
            s = self._session
            if not s:
                return {"active": False, "session_id": None}
            return {
                "active": s.active,
                "session_id": s.session_id,
                "prompt": s.prompt,
                "width": s.width,
                "height": s.height,
                "interval_sec": s.interval_sec,
                "max_strokes": s.max_strokes,
                "timeout_sec": s.timeout_sec,
                "planned_count": s.planned_count,
                "sent_count": s.sent_count,
                "rejected_count": s.rejected_count,
                "stop_reason": s.stop_reason,
                "emergency_stop": s.emergency_stop,
            }

    def get_commands(self, *, session_id: str, since_seq: int = 0, limit: int = 100) -> dict:
        self._drain_executor_events()
        with self._lock:
            s = self._session
            if not s or s.session_id != session_id:
                return {"items": [], "next_seq": since_seq, "active": False, "stop_reason": "session_not_found"}
            items = [c for c in (s.command_buffer or []) if int(c.get("seq") or 0) > int(since_seq)]
            items = items[: max(1, min(200, int(limit)))]
            next_seq = int(s.command_buffer[-1]["seq"]) if s.command_buffer else int(since_seq)
            return {
                "items": items,
                "next_seq": next_seq,
                "active": s.active,
                "stop_reason": s.stop_reason,
                "sent_count": s.sent_count,
                "planned_count": s.planned_count,
                "rejected_count": s.rejected_count,
            }

    def _planner_loop(self) -> None:
        while not self._planner_stop.is_set():
            time.sleep(0.2)
            with self._lock:
                s = self._session
                if not s or not s.active:
                    continue

                now = time.time()
                if s.emergency_stop:
                    s.active = False
                    s.stop_reason = "emergency_stop"
                    continue
                if now - s.started_at > s.timeout_sec:
                    s.active = False
                    s.stop_reason = "timeout"
                    continue
                if s.planned_count >= s.max_strokes:
                    s.active = False
                    s.stop_reason = "max_strokes_reached"
                    continue
                if s.last_observation_ts <= 0:
                    continue
                if now - s.last_plan_ts < s.interval_sec:
                    continue

                cmd = self._plan_next_command(s)
                s.last_plan_ts = now
                if not cmd:
                    continue
                s.planned_count += 1
                in_q = self._in_q
                if in_q is not None:
                    in_q.put(
                        {
                            "session_id": s.session_id,
                            "width": s.width,
                            "height": s.height,
                            "command": cmd,
                        }
                    )

    def _plan_next_command(self, s: DrawSession) -> Optional[dict]:
        # First stroke: fill a soft background.
        if s.planned_count == 0:
            return {"cmd": "fill", "color": "#0f172a"}

        # If canvas is still mostly blank, use brighter strokes to make progress visible.
        dark_ratio = float(s.observation_dark_ratio or 0.0)
        palette_blank = ["#93c5fd", "#fcd34d", "#fca5a5", "#86efac"]
        palette_normal = ["#60a5fa", "#f59e0b", "#f43f5e", "#34d399", "#a78bfa"]
        palette = palette_blank if dark_ratio > 0.82 else palette_normal

        step = s.planned_count
        w, h = s.width, s.height
        cx, cy = w / 2.0, h / 2.0
        rx, ry = w * 0.34, h * 0.30
        t1 = step * 0.42
        t2 = (step + 1) * 0.42

        x1 = int(cx + rx * math.sin(t1 * 1.7))
        y1 = int(cy + ry * math.cos(t1 * 1.3))
        x2 = int(cx + rx * math.sin(t2 * 1.2 + 0.7))
        y2 = int(cy + ry * math.cos(t2 * 1.6 + 0.3))
        brush = 2 + (step % 5)
        color = palette[step % len(palette)]
        return {"cmd": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2, "brush": brush, "color": color}

    def _drain_executor_events(self) -> None:
        out_q = self._out_q
        if out_q is None:
            return
        while True:
            try:
                ev = out_q.get_nowait()
            except queue.Empty:
                break
            except Exception:
                break
            with self._lock:
                s = self._session
                if not s:
                    continue
                if ev.get("session_id") != s.session_id:
                    continue
                if ev.get("accepted"):
                    s.next_seq += 1
                    item = {
                        "seq": s.next_seq,
                        "command": ev.get("command") or {},
                        "ts": ev.get("ts"),
                    }
                    s.command_buffer.append(item)
                    if len(s.command_buffer) > 600:
                        s.command_buffer = s.command_buffer[-600:]
                    s.sent_count += 1
                else:
                    s.rejected_count += 1

    def _estimate_dark_ratio(self, image_data: str) -> float:
        if not image_data or Image is None:
            return 0.0
        try:
            if "," in image_data:
                image_data = image_data.split(",", 1)[1]
            raw = base64.b64decode(image_data)
            with Image.open(io.BytesIO(raw)) as img:
                gray = img.convert("L").resize((80, 50))
                pixels = list(gray.getdata())
                dark = sum(1 for p in pixels if p < 40)
                return float(dark) / max(1, len(pixels))
        except Exception:
            return 0.0


draw_agent_service = DrawAgentService()
