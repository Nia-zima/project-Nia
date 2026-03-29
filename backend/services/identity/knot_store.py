"""Repository for metabolic_knots and related tables.

All functions take a sqlite3.Connection (caller owns the transaction).
JSON fields are serialized/deserialized via json module.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from backend.core.logger import logger
from backend.services.identity.schema import (
    KnotActivation,
    KnotBaseline,
    KnotRelation,
    KnotSignalSnapshot,
    KnotStatus,
    KnotType,
    MetabolicKnot,
    PerturbationEpisode,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── DDL ───────────────────────────────────────────────────────────────


def ensure_metabolic_knot_schema(conn: sqlite3.Connection) -> None:
    """Create all metabolic hardening tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS metabolic_knots (
            knot_id          TEXT PRIMARY KEY,
            knot_type        TEXT NOT NULL,
            status           TEXT NOT NULL DEFAULT 'active',

            trigger_signature TEXT NOT NULL,
            effect_signature  TEXT NOT NULL,

            activation_count        INTEGER NOT NULL DEFAULT 0,
            distinct_day_count      INTEGER NOT NULL DEFAULT 0,
            distinct_thread_count   INTEGER NOT NULL DEFAULT 0,
            distinct_regime_count   INTEGER NOT NULL DEFAULT 0,
            day_span                INTEGER NOT NULL DEFAULT 0,

            recovery_speed_avg      REAL,
            rebound_stability_avg   REAL,
            episode_confidence_avg  REAL,

            hardness_level    INTEGER NOT NULL DEFAULT 0,
            protection_score  REAL NOT NULL DEFAULT 0.0,

            reproducibility     REAL NOT NULL DEFAULT 0.0,
            damage_sensitivity  REAL NOT NULL DEFAULT 0.0,
            redundancy          REAL NOT NULL DEFAULT 0.0,
            temporal_stability  REAL NOT NULL DEFAULT 0.0,

            current_baseline_version TEXT NOT NULL,

            coupled_knots     TEXT NOT NULL DEFAULT '[]',
            coupling_type     TEXT NOT NULL DEFAULT '[]',

            rewrite_threshold           REAL NOT NULL DEFAULT 0.30,
            contradiction_hold_threshold REAL NOT NULL DEFAULT 0.55,
            softening_rate              REAL NOT NULL DEFAULT 0.02,

            source_knot_ids   TEXT NOT NULL DEFAULT '[]',
            supersedes        TEXT,
            merged_into       TEXT,

            first_seen_at     TEXT NOT NULL,
            last_activated_at TEXT NOT NULL,
            last_contradicted_at TEXT,
            created_at        TEXT NOT NULL,
            updated_at        TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS knot_signal_history (
            knot_id           TEXT NOT NULL,
            sleep_date        TEXT NOT NULL,
            reproducibility   REAL NOT NULL,
            damage_sensitivity REAL NOT NULL,
            redundancy        REAL NOT NULL,
            temporal_stability REAL NOT NULL,
            protection_score  REAL NOT NULL,
            hardness_level    INTEGER NOT NULL,
            PRIMARY KEY (knot_id, sleep_date)
        );

        CREATE TABLE IF NOT EXISTS knot_activations (
            activation_id      TEXT PRIMARY KEY,
            knot_id            TEXT NOT NULL,
            turn_id            TEXT NOT NULL,
            thread_id          TEXT NOT NULL,
            interaction_regime TEXT NOT NULL,
            baseline_version   TEXT NOT NULL,
            trigger_values     TEXT NOT NULL,
            effect_values      TEXT NOT NULL,
            activated_at       TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_ka_knot_id
        ON knot_activations(knot_id);
        CREATE INDEX IF NOT EXISTS idx_ka_turn_id
        ON knot_activations(turn_id);
        CREATE INDEX IF NOT EXISTS idx_ka_activated_at
        ON knot_activations(activated_at DESC);

        CREATE TABLE IF NOT EXISTS knot_baselines (
            baseline_version TEXT NOT NULL,
            regime           TEXT NOT NULL,
            effect_key       TEXT NOT NULL,
            value            REAL NOT NULL,
            sample_count     INTEGER NOT NULL DEFAULT 0,
            created_at       TEXT NOT NULL,
            PRIMARY KEY (baseline_version, regime, effect_key)
        );

        CREATE TABLE IF NOT EXISTS perturbation_episodes (
            episode_id            TEXT PRIMARY KEY,
            trigger_type          TEXT NOT NULL,
            trigger_turn_id       TEXT NOT NULL,
            thread_id             TEXT NOT NULL,
            destabilization_turns INTEGER NOT NULL DEFAULT 0,
            recovery_turns        INTEGER NOT NULL DEFAULT 0,
            recovered             BOOLEAN NOT NULL DEFAULT 0,
            episode_confidence    REAL NOT NULL DEFAULT 0.0,
            pre_baseline          TEXT NOT NULL,
            post_baseline         TEXT NOT NULL,
            max_deviation         REAL NOT NULL DEFAULT 0.0,
            started_at            TEXT NOT NULL,
            ended_at              TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_pe_thread
        ON perturbation_episodes(thread_id);
        CREATE INDEX IF NOT EXISTS idx_pe_started
        ON perturbation_episodes(started_at DESC);

        CREATE TABLE IF NOT EXISTS knot_relations (
            source_knot_id  TEXT NOT NULL,
            target_knot_id  TEXT NOT NULL,
            relation_type   TEXT NOT NULL,
            strength        REAL NOT NULL DEFAULT 0.0,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL,
            PRIMARY KEY (source_knot_id, target_knot_id, relation_type)
        );
        CREATE TABLE IF NOT EXISTS knot_contradiction_holds (
            hold_id                  TEXT PRIMARY KEY,
            knot_id                  TEXT NOT NULL,

            contradiction_kind       TEXT NOT NULL,
            contradiction_score      REAL NOT NULL DEFAULT 0.0,
            contradicting_turn_ids   TEXT NOT NULL DEFAULT '[]',
            evidence_count           INTEGER NOT NULL DEFAULT 0,

            hardness_level_at_hold   INTEGER NOT NULL,
            trigger_signature_snapshot TEXT NOT NULL,
            effect_signature_snapshot  TEXT NOT NULL,
            baseline_version_at_hold   TEXT NOT NULL,
            protection_score_at_hold   REAL NOT NULL,

            hold_type                TEXT NOT NULL DEFAULT 'soft',
            hold_duration_sleeps     INTEGER NOT NULL DEFAULT 0,
            min_review_sleeps        INTEGER NOT NULL DEFAULT 1,

            status                   TEXT NOT NULL DEFAULT 'pending',
            resolution_reason        TEXT,
            resolved_at              TEXT,

            adaptation_proposal_id   TEXT,
            requires_review          BOOLEAN NOT NULL DEFAULT 0,

            created_at               TEXT NOT NULL,
            updated_at               TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_kch_knot_id
        ON knot_contradiction_holds(knot_id);
        CREATE INDEX IF NOT EXISTS idx_kch_status
        ON knot_contradiction_holds(status);
    """)
    logger.info("[METABOLIC] Schema ensured: 7 tables")


# ── MetabolicKnot CRUD ────────────────────────────────────────────────


def save_knot(conn: sqlite3.Connection, knot: MetabolicKnot) -> None:
    """Insert or replace a knot."""
    conn.execute(
        """INSERT OR REPLACE INTO metabolic_knots (
            knot_id, knot_type, status,
            trigger_signature, effect_signature,
            activation_count, distinct_day_count, distinct_thread_count,
            distinct_regime_count, day_span,
            recovery_speed_avg, rebound_stability_avg, episode_confidence_avg,
            hardness_level, protection_score,
            reproducibility, damage_sensitivity, redundancy, temporal_stability,
            current_baseline_version,
            coupled_knots, coupling_type,
            rewrite_threshold, contradiction_hold_threshold, softening_rate,
            source_knot_ids, supersedes, merged_into,
            first_seen_at, last_activated_at, last_contradicted_at,
            created_at, updated_at
        ) VALUES (?,?,?, ?,?, ?,?,?,?,?, ?,?,?, ?,?, ?,?,?,?, ?, ?,?, ?,?,?, ?,?,?, ?,?,?, ?,?)""",
        (
            knot.knot_id, knot.knot_type.value, knot.status.value,
            json.dumps(knot.trigger_signature, ensure_ascii=False),
            json.dumps(knot.effect_signature, ensure_ascii=False),
            knot.activation_count, knot.distinct_day_count, knot.distinct_thread_count,
            knot.distinct_regime_count, knot.day_span,
            knot.recovery_speed_avg, knot.rebound_stability_avg, knot.episode_confidence_avg,
            knot.hardness_level, knot.protection_score,
            knot.reproducibility, knot.damage_sensitivity,
            knot.redundancy, knot.temporal_stability,
            knot.current_baseline_version,
            json.dumps(knot.coupled_knots), json.dumps(knot.coupling_type),
            knot.rewrite_threshold, knot.contradiction_hold_threshold, knot.softening_rate,
            json.dumps(knot.source_knot_ids), knot.supersedes, knot.merged_into,
            knot.first_seen_at, knot.last_activated_at, knot.last_contradicted_at,
            knot.created_at, knot.updated_at,
        ),
    )


def get_knot(conn: sqlite3.Connection, knot_id: str) -> Optional[MetabolicKnot]:
    """Fetch a single knot by ID."""
    row = conn.execute("SELECT * FROM metabolic_knots WHERE knot_id = ?", (knot_id,)).fetchone()
    if not row:
        return None
    return _row_to_knot(row, conn)


def list_active_knots(conn: sqlite3.Connection) -> list[MetabolicKnot]:
    """Return all active knots."""
    rows = conn.execute(
        "SELECT * FROM metabolic_knots WHERE status = 'active' ORDER BY hardness_level DESC, protection_score DESC"
    ).fetchall()
    return [_row_to_knot(r, conn) for r in rows]


def list_knots_by_type(conn: sqlite3.Connection, knot_type: KnotType) -> list[MetabolicKnot]:
    """Return active knots of a given type."""
    rows = conn.execute(
        "SELECT * FROM metabolic_knots WHERE status = 'active' AND knot_type = ? ORDER BY protection_score DESC",
        (knot_type.value,),
    ).fetchall()
    return [_row_to_knot(r, conn) for r in rows]


def _row_to_knot(row: sqlite3.Row, conn: sqlite3.Connection) -> MetabolicKnot:
    d = dict(row)
    d["knot_type"] = KnotType(d["knot_type"])
    d["status"] = KnotStatus(d["status"])
    d["trigger_signature"] = json.loads(d["trigger_signature"])
    d["effect_signature"] = json.loads(d["effect_signature"])
    d["coupled_knots"] = json.loads(d["coupled_knots"])
    d["coupling_type"] = json.loads(d["coupling_type"])
    d["source_knot_ids"] = json.loads(d["source_knot_ids"])
    return MetabolicKnot(**d)


# ── KnotActivation ────────────────────────────────────────────────────


def save_activation(conn: sqlite3.Connection, act: KnotActivation) -> None:
    """Insert an activation record."""
    conn.execute(
        """INSERT INTO knot_activations (
            activation_id, knot_id, turn_id, thread_id,
            interaction_regime, baseline_version,
            trigger_values, effect_values, activated_at
        ) VALUES (?,?,?,?, ?,?, ?,?,?)""",
        (
            act.activation_id, act.knot_id, act.turn_id, act.thread_id,
            act.interaction_regime, act.baseline_version,
            json.dumps(act.trigger_values, ensure_ascii=False),
            json.dumps(act.effect_values, ensure_ascii=False),
            act.activated_at,
        ),
    )


def list_activations_for_knot(
    conn: sqlite3.Connection, knot_id: str, *, limit: int = 100
) -> list[KnotActivation]:
    """Return recent activations for a knot."""
    rows = conn.execute(
        "SELECT * FROM knot_activations WHERE knot_id = ? ORDER BY activated_at DESC LIMIT ?",
        (knot_id, limit),
    ).fetchall()
    return [_row_to_activation(r) for r in rows]


def _row_to_activation(row: sqlite3.Row) -> KnotActivation:
    d = dict(row)
    d["trigger_values"] = json.loads(d["trigger_values"])
    d["effect_values"] = json.loads(d["effect_values"])
    return KnotActivation(**d)


# ── KnotBaseline ──────────────────────────────────────────────────────


def save_baseline_snapshot(conn: sqlite3.Connection, baselines: list[KnotBaseline]) -> None:
    """Insert a batch of baseline entries (append-only snapshot)."""
    conn.executemany(
        """INSERT INTO knot_baselines (baseline_version, regime, effect_key, value, sample_count, created_at)
        VALUES (?,?,?,?,?,?)""",
        [(b.baseline_version, b.regime, b.effect_key, b.value, b.sample_count, b.created_at) for b in baselines],
    )


def get_baseline(conn: sqlite3.Connection, version: str) -> dict[str, dict[str, float]]:
    """Return baseline as {regime: {effect_key: value}}."""
    rows = conn.execute(
        "SELECT regime, effect_key, value FROM knot_baselines WHERE baseline_version = ?",
        (version,),
    ).fetchall()
    result: dict[str, dict[str, float]] = {}
    for row in rows:
        regime, key, val = row["regime"], row["effect_key"], row["value"]
        result.setdefault(regime, {})[key] = val
    return result


def get_latest_baseline_version(conn: sqlite3.Connection) -> Optional[str]:
    """Return the most recent baseline_version."""
    row = conn.execute(
        "SELECT baseline_version FROM knot_baselines ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    return row["baseline_version"] if row else None


# ── PerturbationEpisode ───────────────────────────────────────────────


def save_episode(conn: sqlite3.Connection, ep: PerturbationEpisode) -> None:
    """Insert or replace a perturbation episode."""
    conn.execute(
        """INSERT OR REPLACE INTO perturbation_episodes (
            episode_id, trigger_type, trigger_turn_id, thread_id,
            destabilization_turns, recovery_turns, recovered, episode_confidence,
            pre_baseline, post_baseline, max_deviation,
            started_at, ended_at
        ) VALUES (?,?,?,?, ?,?,?,?, ?,?,?, ?,?)""",
        (
            ep.episode_id, ep.trigger_type.value, ep.trigger_turn_id, ep.thread_id,
            ep.destabilization_turns, ep.recovery_turns, int(ep.recovered), ep.episode_confidence,
            json.dumps(ep.pre_baseline, ensure_ascii=False),
            json.dumps(ep.post_baseline, ensure_ascii=False),
            ep.max_deviation,
            ep.started_at, ep.ended_at,
        ),
    )


def list_episodes(conn: sqlite3.Connection, *, limit: int = 50) -> list[PerturbationEpisode]:
    """Return recent perturbation episodes."""
    rows = conn.execute(
        "SELECT * FROM perturbation_episodes ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [_row_to_episode(r) for r in rows]


def _row_to_episode(row: sqlite3.Row) -> PerturbationEpisode:
    d = dict(row)
    d["trigger_type"] = d["trigger_type"]  # PerturbationTrigger validates
    d["recovered"] = bool(d["recovered"])
    d["pre_baseline"] = json.loads(d["pre_baseline"])
    d["post_baseline"] = json.loads(d["post_baseline"])
    return PerturbationEpisode(**d)


# ── KnotRelation ──────────────────────────────────────────────────────


def save_relation(conn: sqlite3.Connection, rel: KnotRelation) -> None:
    """Insert or replace a knot relation."""
    conn.execute(
        """INSERT OR REPLACE INTO knot_relations (
            source_knot_id, target_knot_id, relation_type,
            strength, created_at, updated_at
        ) VALUES (?,?,?, ?,?,?)""",
        (
            rel.source_knot_id, rel.target_knot_id, rel.relation_type.value,
            rel.strength, rel.created_at, rel.updated_at,
        ),
    )


def get_relations_for_knot(conn: sqlite3.Connection, knot_id: str) -> list[KnotRelation]:
    """Return all relations where knot_id is source or target."""
    rows = conn.execute(
        "SELECT * FROM knot_relations WHERE source_knot_id = ? OR target_knot_id = ?",
        (knot_id, knot_id),
    ).fetchall()
    return [KnotRelation(**dict(r)) for r in rows]


# ── KnotSignalSnapshot ────────────────────────────────────────────────


def save_signal_snapshot(conn: sqlite3.Connection, snap: KnotSignalSnapshot) -> None:
    """Insert a signal history entry."""
    conn.execute(
        """INSERT OR REPLACE INTO knot_signal_history (
            knot_id, sleep_date, reproducibility, damage_sensitivity,
            redundancy, temporal_stability, protection_score, hardness_level
        ) VALUES (?,?,?,?,?,?,?,?)""",
        (
            snap.knot_id, snap.sleep_date,
            snap.reproducibility, snap.damage_sensitivity,
            snap.redundancy, snap.temporal_stability,
            snap.protection_score, snap.hardness_level,
        ),
    )


# ── ContradictionHold ──────────────────────────────────────────────────


def save_hold(conn: sqlite3.Connection, hold: "ContradictionHold") -> None:
    """Insert or replace a contradiction hold."""
    conn.execute(
        """INSERT OR REPLACE INTO knot_contradiction_holds (
            hold_id, knot_id,
            contradiction_kind, contradiction_score, contradicting_turn_ids, evidence_count,
            hardness_level_at_hold, trigger_signature_snapshot, effect_signature_snapshot,
            baseline_version_at_hold, protection_score_at_hold,
            hold_type, hold_duration_sleeps, min_review_sleeps,
            status, resolution_reason, resolved_at,
            adaptation_proposal_id, requires_review,
            created_at, updated_at
        ) VALUES (?,?, ?,?,?,?, ?,?,?,?,?, ?,?,?, ?,?,?, ?,?, ?,?)""",
        (
            hold.hold_id, hold.knot_id,
            hold.contradiction_kind.value, hold.contradiction_score,
            json.dumps(hold.contradicting_turn_ids), hold.evidence_count,
            hold.hardness_level_at_hold,
            json.dumps(hold.trigger_signature_snapshot, ensure_ascii=False),
            json.dumps(hold.effect_signature_snapshot, ensure_ascii=False),
            hold.baseline_version_at_hold, hold.protection_score_at_hold,
            hold.hold_type, hold.hold_duration_sleeps, hold.min_review_sleeps,
            hold.status.value, hold.resolution_reason, hold.resolved_at,
            hold.adaptation_proposal_id, int(hold.requires_review),
            hold.created_at, hold.updated_at,
        ),
    )


def list_pending_holds(conn: sqlite3.Connection) -> list["ContradictionHold"]:
    """Return all pending holds."""
    rows = conn.execute(
        "SELECT * FROM knot_contradiction_holds WHERE status = 'pending' ORDER BY created_at ASC"
    ).fetchall()
    return [_row_to_hold(r) for r in rows]


def list_holds_for_knot(conn: sqlite3.Connection, knot_id: str) -> list["ContradictionHold"]:
    """Return all holds for a specific knot."""
    rows = conn.execute(
        "SELECT * FROM knot_contradiction_holds WHERE knot_id = ? ORDER BY created_at DESC",
        (knot_id,),
    ).fetchall()
    return [_row_to_hold(r) for r in rows]


def _row_to_hold(row: sqlite3.Row) -> "ContradictionHold":
    from backend.services.identity.schema import ContradictionHold, ContradictionKind, HoldStatus
    d = dict(row)
    d["contradiction_kind"] = ContradictionKind(d["contradiction_kind"])
    d["status"] = HoldStatus(d["status"])
    d["contradicting_turn_ids"] = json.loads(d["contradicting_turn_ids"])
    d["trigger_signature_snapshot"] = json.loads(d["trigger_signature_snapshot"])
    d["effect_signature_snapshot"] = json.loads(d["effect_signature_snapshot"])
    d["requires_review"] = bool(d["requires_review"])
    return ContradictionHold(**d)


# ── Knot Summary (human-readable, not a claim) ───────────────────────


_TRIGGER_LABELS: dict[str, str] = {
    "uncertainty": "不確実性",
    "contradiction_pressure": "矛盾圧",
    "user_repair_recent": "直近訂正",
    "interaction_regime": "対話形式",
    "focus": "焦点",
    "user_correction": "ユーザー訂正",
}

_EFFECT_LABELS: dict[str, str] = {
    "hold_bias": "保留傾向",
    "direct_assertion": "直答",
    "retrieval_seek": "検索探索",
    "premature_closure": "早期閉鎖",
    "exploration": "探索",
    "hedge_ratio": "hedgeの割合",
    "assertion_ratio": "assertionの割合",
    "pause_markers": "ポーズ",
    "organize_rate": "整理率",
    "direct_answer_rate": "直答率",
    "self_ref": "自己参照",
    "fragile_self_rate": "脆い自己開示",
    "ask_rate": "質問率",
    "response_length": "応答長",
    "directness": "直接性",
    "somatic_intensity": "体感強度",
    "depth_distribution": "depth分布",
    "recovery_speed": "回復速度",
    "rebound_stability": "反発安定性",
}


def summarize_knot(knot: MetabolicKnot) -> str:
    """Human-readable 1-line summary. Not a claim — just a meter reading."""
    triggers = []
    for k, v in knot.trigger_signature.items():
        label = _TRIGGER_LABELS.get(k, k)
        triggers.append(f"{label}={v}")
    trigger_text = " + ".join(triggers)

    effects = sorted(knot.effect_signature.items(), key=lambda x: abs(x[1]), reverse=True)[:2]
    effect_parts = []
    for k, v in effects:
        label = _EFFECT_LABELS.get(k, k)
        direction = "↑" if v > 0 else "↓"
        effect_parts.append(f"{label}{direction}")
    effect_text = ", ".join(effect_parts)

    return f"[{knot.knot_type.value}] {trigger_text} → {effect_text}  (L{knot.hardness_level}, P={knot.protection_score:.2f})"
