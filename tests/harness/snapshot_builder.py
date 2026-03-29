"""Snapshot Builder — programmatically construct DB states for testing.

Usage:
    SnapshotBuilder.slump().build()
    # or fluent:
    SnapshotBuilder().with_semantic("fact", confidence=0.9).with_telemetry("k", "v").build()

Reuses conftest.make_semantic / make_working for SemanticMemory / WorkingItem creation.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import date, timedelta

from backend.core.db import get_conn, init_schema
from backend.services.memory.models import SemanticMemory, WorkingItem
from backend.services.memory.somatic_feedback import SomaticOutcome


# ── Helpers ──────────────────────────────────────────────────


def _now() -> float:
    return time.time()


def _make_semantic(
    content: str,
    *,
    id: str | None = None,
    thread_id: str = "default_thread",
    status: str = "confirmed",
    confidence: float = 0.8,
    state_tag: str | None = None,
    defeaters: str = "[]",
    supersedes_id: str | None = None,
    seed_retention: float = 0.5,
    created_at: float | None = None,
    updated_at: float | None = None,
) -> SemanticMemory:
    now = created_at or _now()
    return SemanticMemory(
        id=id or uuid.uuid4().hex,
        thread_id=thread_id,
        content=content,
        valid_from=now,
        created_at=now,
        updated_at=updated_at or now,
        status=status,
        confidence=confidence,
        state_tag=state_tag,
        defeaters=defeaters,
        supersedes_id=supersedes_id,
        seed_retention=seed_retention,
    )


def _make_working(
    content: str,
    *,
    id: str | None = None,
    thread_id: str = "default_thread",
    item_type: str = "question",
    priority: int = 3,
    status: str = "open",
    stale_turn_count: int = 0,
    ttl_turns: int | None = None,
    expires_at: float | None = None,
) -> WorkingItem:
    now = _now()
    return WorkingItem(
        id=id or uuid.uuid4().hex,
        thread_id=thread_id,
        item_type=item_type,
        content=content,
        priority=priority,
        status=status,
        stale_turn_count=stale_turn_count,
        ttl_turns=ttl_turns,
        expires_at=expires_at,
        created_turn_id="snapshot_setup",
        created_at=now,
        updated_at=now,
    )


# ── Tables to clean ─────────────────────────────────────────

_TABLES_TO_CLEAN = [
    "memory_events",
    "semantic_memories",
    "working_items",
    "somatic_log",
    "daily_reflections",
    "telemetry_kv",
    "memory_index",
    "dreams",
    "identity_proposals",
]


def clean_all_tables() -> None:
    """Delete all rows from test-relevant tables.

    Temporarily disables FK constraints to avoid ordering issues
    when other tests have inserted FK-linked data.
    """
    conn = get_conn()
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        for t in _TABLES_TO_CLEAN:
            conn.execute(f"DELETE FROM {t}")  # noqa: S608
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
    finally:
        conn.close()


# ── Snapshot Builder ─────────────────────────────────────────


class SnapshotBuilder:
    """Programmatically build a specific DB state for testing.

    Fluent API:
        SnapshotBuilder()
            .with_semantic("fact A", confidence=0.9)
            .with_telemetry("awareness_average", "0.35")
            .build()

    Presets:
        SnapshotBuilder.slump().build()
    """

    def __init__(self) -> None:
        self._semantics: list[SemanticMemory] = []
        self._working: list[WorkingItem] = []
        self._telemetry: dict[str, str] = {}
        self._somatic_outcomes: list[SomaticOutcome] = []
        self._events: list[dict] = []
        self._reflections: list[dict] = []

    # ── Fluent builders ──────────────────────────────────────

    def with_semantic(self, content: str, **kw) -> SnapshotBuilder:
        self._semantics.append(_make_semantic(content, **kw))
        return self

    def with_working(self, content: str, **kw) -> SnapshotBuilder:
        self._working.append(_make_working(content, **kw))
        return self

    def with_telemetry(self, key: str, value: str) -> SnapshotBuilder:
        self._telemetry[key] = value
        return self

    def with_somatic_outcome(
        self,
        sense_text: str,
        outcome: str,
        *,
        intensity: float = 0.5,
        thread_id: str = "default_thread",
        correction_source: str = "",
        created_at: float | None = None,
    ) -> SnapshotBuilder:
        self._somatic_outcomes.append(SomaticOutcome(
            id=uuid.uuid4().hex,
            thread_id=thread_id,
            turn_id=f"turn_{len(self._somatic_outcomes)}",
            sense_text=sense_text,
            intensity=intensity,
            outcome=outcome,
            correction_source=correction_source,
            created_at=created_at or _now(),
        ))
        return self

    def with_event(
        self,
        user_text: str,
        ai_response: str,
        *,
        thread_id: str = "default_thread",
        turn_id: str | None = None,
        created_at: float | None = None,
    ) -> SnapshotBuilder:
        self._events.append({
            "event_id": uuid.uuid4().hex,
            "thread_id": thread_id,
            "turn_id": turn_id or f"turn_{len(self._events)}",
            "event_type": "conversation_turn",
            "payload_json": json.dumps({
                "user_text": user_text,
                "ai_response": ai_response,
            }),
            "created_at": created_at or _now(),
        })
        return self

    def with_reflection(
        self,
        content_json: str,
        *,
        phase: str = "daily_log",
        thread_id: str = "default_thread",
        reflection_date: str | None = None,
        session_index: int = 0,
        turn_count: int = 10,
    ) -> SnapshotBuilder:
        self._reflections.append({
            "id": uuid.uuid4().hex,
            "thread_id": thread_id,
            "reflection_date": reflection_date or date.today().isoformat(),
            "session_index": session_index,
            "phase": phase,
            "content_json": content_json,
            "turn_count": turn_count,
            "token_count": 0,
            "created_at": _now(),
        })
        return self

    # ── Preset: slump ────────────────────────────────────────

    @classmethod
    def slump(cls) -> SnapshotBuilder:
        """ニアの自信閾値が限界まで上がり、沈黙が多い状態。

        - somatic_log: 20件中15件 contradicted (accuracy=0.25)
        - telemetry_kv: confidence_variance=0.12, dissonance_streak=5
        - semantic_memories: 基本的な記憶あり（抽出対象）
        """
        b = cls()
        now = _now()

        # 20 somatic outcomes: 5 confirmed + 15 contradicted
        for i in range(5):
            b.with_somatic_outcome(
                "なんとなく覚えがある", "confirmed",
                intensity=0.6, created_at=now - 3600 + i,
            )
        for i in range(15):
            b.with_somatic_outcome(
                "はっきり覚えている", "contradicted",
                intensity=0.9, correction_source="user_correction",
                created_at=now - 1800 + i,
            )

        # High variance, long dissonance streak
        b.with_telemetry("confidence_variance", "0.12")
        b.with_telemetry("dissonance_streak", "5")
        b.with_telemetry("awareness_average", "0.15")
        b.with_telemetry("awareness_history",
                         json.dumps([0.1, 0.15, 0.2, 0.12, 0.18]))
        b.with_telemetry("confidence_history",
                         json.dumps([0.3, 0.8, 0.2, 0.7, 0.35]))

        # Some conversation events for sleep cycle input
        for i in range(5):
            b.with_event(
                f"テスト質問 {i}", f"テスト回答 {i}",
                created_at=now - 7200 + i * 600,
            )

        # A few semantic memories
        b.with_semantic("ジュンはプログラミングが好き", state_tag="origin")
        b.with_semantic("ニアは慎重に話す傾向がある", state_tag="nia")

        return b

    # ── Preset: contradiction_overload ────────────────────────

    @classmethod
    def contradiction_overload(cls) -> SnapshotBuilder:
        """矛盾した記憶が大量に溜まった状態。

        - semantic_memories: 10対の矛盾ペア（defeaters設定済み）
        - telemetry_kv: contradiction_recent="1"
        """
        b = cls()
        now = _now()

        pairs = [
            ("ジュンはコーヒーが好き", "ジュンは紅茶派だと言った"),
            ("ジュンは猫派", "ジュンは犬が好き"),
            ("ジュンは朝型", "ジュンは夜更かしが多い"),
            ("ジュンはRust推し", "ジュンはPythonが一番好き"),
            ("ジュンは甘党", "ジュンは甘いものが苦手"),
            ("ジュンは海が好き", "ジュンは山派"),
            ("ジュンは一人暮らし", "ジュンは同居人がいる"),
            ("ジュンは料理が趣味", "ジュンは外食ばかり"),
            ("ジュンは静かな音楽が好き", "ジュンはメタルが好き"),
            ("ジュンは読書家", "ジュンはあまり本を読まない"),
        ]

        for i, (claim_a, claim_b) in enumerate(pairs):
            id_a = f"contra_a_{i}"
            id_b = f"contra_b_{i}"
            b.with_semantic(
                claim_a, id=id_a, confidence=0.7, state_tag="origin",
                defeaters=json.dumps([claim_b]),
                created_at=now - 86400 + i * 100,
            )
            b.with_semantic(
                claim_b, id=id_b, confidence=0.6, state_tag="origin",
                defeaters=json.dumps([claim_a]),
                created_at=now - 43200 + i * 100,
            )

        b.with_telemetry("contradiction_recent", "1")

        return b

    # ── Preset: rich_history ─────────────────────────────────

    @classmethod
    def rich_history(cls) -> SnapshotBuilder:
        """100+記憶、7日分のdaily_reflection。

        R.4 cross-day distillation テスト向け。
        """
        b = cls()
        now = _now()

        tags = ["origin", "shared", "nia", "origin", "shared"]
        for i in range(100):
            tag = tags[i % len(tags)]
            b.with_semantic(
                f"記憶 #{i}: テスト事実",
                state_tag=tag,
                confidence=0.5 + (i % 5) * 0.1,
                created_at=now - 86400 * 7 + i * 600,
            )

        # 7 days of daily reflections
        for day_offset in range(7):
            ref_date = (date.today() - timedelta(days=day_offset)).isoformat()
            content = json.dumps({
                "summary": f"Day {7 - day_offset} の振り返り",
                "topics": ["テスト", "記憶"],
                "mood": "reflective",
            })
            b.with_reflection(
                content, reflection_date=ref_date,
                session_index=0, turn_count=15,
            )

        b.with_telemetry("last_sleep_completed_at", str(now - 86400))
        b.with_telemetry("awareness_average", "0.2")

        return b

    # ── Preset: high_awareness ───────────────────────────────

    @classmethod
    def high_awareness(cls) -> SnapshotBuilder:
        """持続的に高い awareness_average → N.4 トリガー想定。"""
        b = cls()
        b.with_telemetry("awareness_average", "0.35")
        b.with_telemetry("awareness_history",
                         json.dumps([0.3, 0.4, 0.35, 0.3, 0.38]))
        b.with_telemetry("confidence_history",
                         json.dumps([0.7, 0.65, 0.72, 0.68, 0.71]))
        b.with_telemetry("confidence_variance", "0.02")
        b.with_telemetry("dissonance_streak", "0")
        b.with_telemetry("topic_shift_count", "1")
        return b

    # ── Preset: fresh_start ──────────────────────────────────

    @classmethod
    def fresh_start(cls) -> SnapshotBuilder:
        """最小データ — graceful degradation テスト。"""
        return cls()  # empty builder → empty DB

    # ── Build (write to DB) ──────────────────────────────────

    def build(self) -> None:
        """Write all accumulated data to the database."""
        init_schema()
        clean_all_tables()

        conn = get_conn()
        try:
            now = _now()

            # Semantic memories
            for mem in self._semantics:
                conn.execute(
                    """INSERT OR REPLACE INTO semantic_memories
                       (id, thread_id, content, status, confidence, state_tag,
                        supersedes_id, revoked_by_id, revoke_reason,
                        valid_from, valid_to, staleness_days,
                        source_turn_ids, source_event_ids, note,
                        seed_retention, vector_sync_pending, embedding, defeaters,
                        created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        mem.id, mem.thread_id, mem.content, mem.status,
                        mem.confidence, mem.state_tag,
                        mem.supersedes_id, mem.revoked_by_id, mem.revoke_reason,
                        mem.valid_from, mem.valid_to, mem.staleness_days,
                        mem.source_turn_ids, mem.source_event_ids, mem.note,
                        mem.seed_retention, mem.vector_sync_pending,
                        mem.embedding, mem.defeaters,
                        mem.created_at, mem.updated_at,
                    ),
                )

            # Working items
            for wi in self._working:
                conn.execute(
                    """INSERT OR REPLACE INTO working_items
                       (id, thread_id, item_type, content, priority, status,
                        close_reason, linked_semantic_ids, linked_event_ids,
                        merged_into_id, ttl_turns, expires_at,
                        stale_turn_count, created_turn_id,
                        created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        wi.id, wi.thread_id, wi.item_type, wi.content,
                        wi.priority, wi.status,
                        wi.close_reason, wi.linked_semantic_ids,
                        wi.linked_event_ids, wi.merged_into_id,
                        wi.ttl_turns, wi.expires_at,
                        wi.stale_turn_count, wi.created_turn_id,
                        wi.created_at, wi.updated_at,
                    ),
                )

            # Telemetry KV
            for k, v in self._telemetry.items():
                conn.execute(
                    "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) "
                    "VALUES (?, ?, ?)",
                    (k, v, int(now)),
                )

            # Somatic outcomes
            for o in self._somatic_outcomes:
                conn.execute(
                    """INSERT INTO somatic_log
                       (id, thread_id, turn_id, query, sense_text, intensity,
                        outcome, correction_source, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        o.id, o.thread_id, o.turn_id, o.query,
                        o.sense_text, o.intensity, o.outcome,
                        o.correction_source, o.created_at,
                    ),
                )

            # Memory events
            for ev in self._events:
                conn.execute(
                    """INSERT INTO memory_events
                       (event_id, thread_id, turn_id, event_type,
                        payload_json, created_at, schema_version)
                       VALUES (?,?,?,?,?,?,1)""",
                    (
                        ev["event_id"], ev["thread_id"], ev["turn_id"],
                        ev["event_type"], ev["payload_json"], ev["created_at"],
                    ),
                )

            # Daily reflections
            for ref in self._reflections:
                conn.execute(
                    """INSERT INTO daily_reflections
                       (id, thread_id, reflection_date, session_index,
                        phase, content_json, turn_count, token_count, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        ref["id"], ref["thread_id"], ref["reflection_date"],
                        ref["session_index"], ref["phase"], ref["content_json"],
                        ref["turn_count"], ref["token_count"], ref["created_at"],
                    ),
                )

            conn.commit()
        finally:
            conn.close()
