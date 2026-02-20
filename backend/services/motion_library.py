"""VRM motion preset store (SQLite). Follows SkillLibrary pattern."""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Optional

from backend.core.db import get_conn

logger = logging.getLogger(__name__)

# Default presets matching AvatarView.tsx GESTURE_PRESETS
_DEFAULT_PRESETS = [
    {
        "name": "nod",
        "description": "うなずき",
        "keyframes_json": json.dumps({
            "keyframes": [
                {"bone": "head", "axis": "x", "target": -0.18, "duration": 200},
                {"bone": "head", "axis": "x", "target": 0.0, "duration": 200},
            ],
            "totalDuration": 400,
            "returnDuration": 200,
        }),
        "tags": json.dumps(["agreement", "acknowledgment"]),
        "context_hint": "同意するとき、相槌を打つとき",
        "source": "builtin",
    },
    {
        "name": "wave",
        "description": "手を振る",
        "keyframes_json": json.dumps({
            "keyframes": [
                {"bone": "rightUpperArm", "axis": "z", "target": 0.3, "duration": 300},
                {"bone": "rightLowerArm", "axis": "z", "target": -0.8, "duration": 200, "delay": 100},
                {"bone": "rightLowerArm", "axis": "z", "target": -1.2, "duration": 200, "delay": 300},
                {"bone": "rightLowerArm", "axis": "z", "target": -0.8, "duration": 200, "delay": 500},
            ],
            "totalDuration": 800,
            "returnDuration": 400,
        }),
        "tags": json.dumps(["greeting", "farewell"]),
        "context_hint": "挨拶のとき、お別れのとき",
        "source": "builtin",
    },
    {
        "name": "shrug",
        "description": "肩をすくめる",
        "keyframes_json": json.dumps({
            "keyframes": [
                {"bone": "leftUpperArm", "axis": "z", "target": -1.0, "duration": 350},
                {"bone": "rightUpperArm", "axis": "z", "target": 1.0, "duration": 350},
                {"bone": "head", "axis": "x", "target": -0.08, "duration": 300},
                {"bone": "head", "axis": "z", "target": 0.1, "duration": 300},
            ],
            "totalDuration": 600,
            "returnDuration": 400,
        }),
        "tags": json.dumps(["uncertainty", "confusion"]),
        "context_hint": "わからないとき、困惑したとき",
        "source": "builtin",
    },
    {
        "name": "tilt_head",
        "description": "首をかしげる",
        "keyframes_json": json.dumps({
            "keyframes": [
                {"bone": "head", "axis": "z", "target": 0.18, "duration": 400},
                {"bone": "head", "axis": "x", "target": -0.05, "duration": 300},
            ],
            "totalDuration": 500,
            "returnDuration": 400,
        }),
        "tags": json.dumps(["curiosity", "questioning"]),
        "context_hint": "疑問に思ったとき、興味があるとき",
        "source": "builtin",
    },
    {
        "name": "bow",
        "description": "お辞儀",
        "keyframes_json": json.dumps({
            "keyframes": [
                {"bone": "spine", "axis": "x", "target": -0.2, "duration": 500},
                {"bone": "head", "axis": "x", "target": -0.15, "duration": 400, "delay": 100},
            ],
            "totalDuration": 700,
            "returnDuration": 500,
        }),
        "tags": json.dumps(["greeting", "respect", "apology"]),
        "context_hint": "丁寧な挨拶、感謝、謝罪のとき",
        "source": "builtin",
    },
    {
        "name": "point",
        "description": "指さし",
        "keyframes_json": json.dumps({
            "keyframes": [
                {"bone": "rightUpperArm", "axis": "z", "target": 0.2, "duration": 300},
                {"bone": "rightLowerArm", "axis": "z", "target": -0.3, "duration": 250, "delay": 100},
            ],
            "totalDuration": 500,
            "returnDuration": 350,
        }),
        "tags": json.dumps(["attention", "indication"]),
        "context_hint": "話題を示すとき、方向を示すとき",
        "source": "builtin",
    },
    {
        "name": "fist_pump",
        "description": "ガッツポーズ",
        "keyframes_json": json.dumps({
            "keyframes": [
                {"bone": "rightUpperArm", "axis": "z", "target": 0.5, "duration": 250},
                {"bone": "rightLowerArm", "axis": "z", "target": -1.5, "duration": 200, "delay": 100},
                {"bone": "rightUpperArm", "axis": "z", "target": 0.3, "duration": 200, "delay": 300},
                {"bone": "rightUpperArm", "axis": "z", "target": 0.5, "duration": 200, "delay": 500},
            ],
            "totalDuration": 700,
            "returnDuration": 350,
        }),
        "tags": json.dumps(["success", "celebration", "motivation"]),
        "context_hint": "喜びや達成感を表すとき",
        "source": "builtin",
    },
    {
        "name": "clap",
        "description": "拍手",
        "keyframes_json": json.dumps({
            "keyframes": [
                {"bone": "leftUpperArm", "axis": "z", "target": -0.8, "duration": 200},
                {"bone": "rightUpperArm", "axis": "z", "target": 0.8, "duration": 200},
                {"bone": "leftUpperArm", "axis": "z", "target": -1.0, "duration": 150, "delay": 200},
                {"bone": "rightUpperArm", "axis": "z", "target": 1.0, "duration": 150, "delay": 200},
                {"bone": "leftUpperArm", "axis": "z", "target": -0.8, "duration": 150, "delay": 350},
                {"bone": "rightUpperArm", "axis": "z", "target": 0.8, "duration": 150, "delay": 350},
            ],
            "totalDuration": 600,
            "returnDuration": 350,
        }),
        "tags": json.dumps(["applause", "praise", "encouragement"]),
        "context_hint": "称賛や応援を示すとき",
        "source": "builtin",
    },
]


class MotionLibrary:
    """CRUD for motion_presets table."""

    def save(
        self,
        name: str,
        description: str,
        keyframes_json: str,
        tags: list[str] | None = None,
        context_hint: str = "",
        source: str = "manual",
    ) -> dict:
        """Save or update a motion preset."""
        now = time.time()
        conn = get_conn()
        try:
            existing = conn.execute(
                "SELECT id FROM motion_presets WHERE name = ?", (name,)
            ).fetchone()

            if existing:
                conn.execute(
                    """UPDATE motion_presets
                       SET description=?, keyframes_json=?, tags=?, context_hint=?, source=?, updated_at=?
                       WHERE name=?""",
                    (description, keyframes_json, json.dumps(tags or []), context_hint, source, now, name),
                )
                preset_id = existing["id"]
            else:
                preset_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO motion_presets
                       (id, name, description, keyframes_json, tags, context_hint, source, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (preset_id, name, description, keyframes_json, json.dumps(tags or []), context_hint, source, now, now),
                )

            logger.info("[MotionLibrary] Saved preset: %s", name)
            return {"id": preset_id, "name": name}
        finally:
            conn.close()

    def get(self, name: str) -> Optional[dict]:
        """Get a preset by name."""
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM motion_presets WHERE name = ?", (name,)
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            d["tags"] = json.loads(d["tags"]) if d["tags"] else []
            return d
        finally:
            conn.close()

    def list_all(self) -> list[dict]:
        """List all presets."""
        conn = get_conn()
        try:
            rows = conn.execute(
                """SELECT id, name, description, tags, context_hint, use_count,
                          success_count, failure_count, source, created_at, updated_at
                   FROM motion_presets ORDER BY name"""
            ).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d["tags"] = json.loads(d["tags"]) if d["tags"] else []
                d["total_uses"] = d["use_count"]
                result.append(d)
            return result
        finally:
            conn.close()

    def record_use(self, name: str, success: bool = True) -> None:
        """Increment use counter and optionally success/failure."""
        conn = get_conn()
        try:
            col = "success_count" if success else "failure_count"
            conn.execute(
                f"UPDATE motion_presets SET use_count = use_count + 1, {col} = {col} + 1, updated_at = ? WHERE name = ?",
                (time.time(), name),
            )
        finally:
            conn.close()

    def delete(self, name: str) -> bool:
        """Delete a preset by name."""
        conn = get_conn()
        try:
            cur = conn.execute("DELETE FROM motion_presets WHERE name = ?", (name,))
            return cur.rowcount > 0
        finally:
            conn.close()

    def get_for_context(self, emotion: str = "", text_hint: str = "") -> list[dict]:
        """Get presets matching a context (tag-based)."""
        all_presets = self.list_all()
        if not emotion and not text_hint:
            return all_presets

        scored = []
        for p in all_presets:
            score = 0
            tags = p.get("tags", [])
            hint = p.get("context_hint", "")
            if emotion and emotion.lower() in " ".join(tags).lower():
                score += 2
            if text_hint and hint and text_hint in hint:
                score += 1
            scored.append((score, p))

        scored.sort(key=lambda x: -x[0])
        return [p for _, p in scored]

    def ensure_defaults(self) -> int:
        """Insert default presets if they don't exist. Returns count inserted."""
        count = 0
        for preset in _DEFAULT_PRESETS:
            existing = self.get(preset["name"])
            if not existing:
                self.save(
                    name=preset["name"],
                    description=preset["description"],
                    keyframes_json=preset["keyframes_json"],
                    tags=json.loads(preset["tags"]),
                    context_hint=preset["context_hint"],
                    source=preset["source"],
                )
                count += 1
        if count:
            logger.info("[MotionLibrary] Inserted %d default presets", count)
        return count


motion_library = MotionLibrary()
