# Usage:
#   python dataset_builder.py --db data/nia.sqlite3 --out data.jsonl --since 0 --limit 0 \
#     --out_gold gold.jsonl --max_user_text_chars 800 --max_candidate_chars 800
#
# This script generates Gate training JSONL from commit_log + pending_actions.

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple


TERMINAL_EVENTS = (
    "MEMORY_ADD_APPLIED",
    "MEMORY_ADD_REJECTED",
    "MEMORY_ADD_CANCELLED_ALREADY_EXISTS",
)


@dataclass
class Stats:
    total: int = 0
    positives: int = 0
    negatives: int = 0
    missing_user_text: int = 0
    bad_payload: int = 0
    bad_commit_meta: int = 0
    dwell_pos_sum: float = 0.0
    dwell_pos_count: int = 0
    dwell_neg_sum: float = 0.0
    dwell_neg_count: int = 0
    gold_count: int = 0
    hard_violation_sum: int = 0
    hard_violation_rows: int = 0
    hard_violation_max: int = 0


def _open_db(path: str) -> sqlite3.Connection:
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _weight(label: int, dwell_sec: Optional[float]) -> float:
    if label != 1:
        return 1.0
    if dwell_sec is None:
        return 1.0
    bonus = _clamp((300.0 - dwell_sec) / 300.0, 0.0, 1.0) * 0.5
    return 1.0 + bonus


def _extract_text_from_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict):
                if p.get("type") in {"text", "input_text"}:
                    parts.append(str(p.get("text") or ""))
                elif p.get("type") == "image_url":
                    parts.append("[image]")
            elif isinstance(p, str):
                parts.append(p)
        return "\n".join([p for p in parts if p]).strip()
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return content.get("text")
        if "content" in content:
            return _extract_text_from_content(content.get("content"))
    return str(content)


def _parse_content_json(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        # raw may already be plain text or JSON
        s = raw.strip()
        if not s:
            return ""
        try:
            obj = json.loads(s)
        except Exception:
            return s
        return _extract_text_from_content(obj)
    return _extract_text_from_content(raw)


def _get_user_text(conn: sqlite3.Connection, thread_id: str, message_id: str, enqueued_at: float) -> str:
    # A) messages.id = message_id AND role='user'
    row = conn.execute(
        "SELECT content_json FROM messages WHERE id = ? AND role = 'user' LIMIT 1",
        (message_id,),
    ).fetchone()
    if row:
        return _parse_content_json(row["content_json"])

    # B) messages.turn_id = message_id AND role='user'
    row = conn.execute(
        "SELECT content_json FROM messages WHERE turn_id = ? AND role = 'user' LIMIT 1",
        (message_id,),
    ).fetchone()
    if row:
        return _parse_content_json(row["content_json"])

    # C) same thread_id, nearest user message before enqueue
    row = conn.execute(
        """
        SELECT content_json
        FROM messages
        WHERE thread_id = ? AND role = 'user' AND created_at <= ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (thread_id, int(enqueued_at)),
    ).fetchone()
    if row:
        return _parse_content_json(row["content_json"])
    return ""


def _parse_payload(payload_json: str) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[Any], Optional[str]]:
    try:
        obj = json.loads(payload_json or "{}")
    except Exception:
        return None, None, None, None
    raw_text = obj.get("raw_text") or obj.get("candidate_raw_text")
    tags = obj.get("tags") or obj.get("candidate_tags")
    schema_version = obj.get("schema_version")
    return obj, raw_text, tags, schema_version


def _extract_hard_violations(lint_meta: Optional[Dict[str, Any]]) -> Tuple[int, list]:
    if not isinstance(lint_meta, dict):
        return 0, []
    violations = lint_meta.get("violations")
    if not isinstance(violations, list):
        return 0, []
    hard = []
    for v in violations:
        if not isinstance(v, dict):
            continue
        if v.get("severity") == "hard":
            code = v.get("code")
            if isinstance(code, str):
                hard.append(code)
    return len(hard), hard


def _rows(
    conn: sqlite3.Connection,
    since: float,
    limit: int,
) -> Iterable[sqlite3.Row]:
    base = """
    WITH terminal AS (
        SELECT
            json_extract(e.payload_json, '$.pending_action_id') AS pending_action_id,
            json_extract(e.payload_json, '$.event') AS terminal_event,
            e.payload_json AS commit_meta,
            e.ts AS terminal_ts,
            CAST(strftime('%s', e.ts) AS REAL) AS terminal_at,
            e.thread_id AS thread_id,
            ROW_NUMBER() OVER (
                PARTITION BY json_extract(e.payload_json, '$.pending_action_id')
                ORDER BY CAST(strftime('%s', e.ts) AS REAL) DESC
            ) AS rn
        FROM events e
        WHERE e.event_type = 'commit_log'
          AND json_extract(e.payload_json, '$.event') IN (?, ?, ?)
    ),
    lint AS (
        SELECT
            json_extract(e.payload_json, '$.message_id') AS message_id,
            e.thread_id AS thread_id,
            e.payload_json AS lint_meta,
            CAST(strftime('%s', e.ts) AS REAL) AS lint_at,
            ROW_NUMBER() OVER (
                PARTITION BY json_extract(e.payload_json, '$.message_id'), e.thread_id
                ORDER BY CAST(strftime('%s', e.ts) AS REAL) DESC
            ) AS rn
        FROM events e
        WHERE e.event_type = 'commit_log'
          AND json_extract(e.payload_json, '$.event') = 'OUTPUT_LINT'
    )
    SELECT
        t.pending_action_id,
        t.terminal_event,
        t.commit_meta,
        t.terminal_at,
        p.thread_id,
        p.message_id,
        p.payload_json,
        p.created_at AS enqueued_at,
        l.lint_meta
    FROM terminal t
    JOIN pending_actions p ON p.id = t.pending_action_id
    LEFT JOIN lint l ON l.message_id = p.message_id AND l.thread_id = p.thread_id AND l.rn = 1
    WHERE t.rn = 1
    """
    params = list(TERMINAL_EVENTS)
    if since and since > 0:
        base += " AND t.terminal_at >= ?"
        params.append(float(since))
    base += " ORDER BY t.terminal_at ASC"
    if limit and limit > 0:
        base += " LIMIT ?"
        params.append(int(limit))
    return conn.execute(base, params)


def build_dataset(
    *,
    db_path: str,
    out_path: str,
    since: float,
    limit: int,
    out_gold: Optional[str],
    max_user_text_chars: int,
    max_candidate_chars: int,
) -> None:
    stats = Stats()
    conn = _open_db(db_path)
    try:
        with open(out_path, "w", encoding="utf-8") as fout:
            gold_out = open(out_gold, "w", encoding="utf-8") if out_gold else None
            try:
                for row in _rows(conn, since, limit):
                    stats.total += 1
                    try:
                        terminal_event = row["terminal_event"]
                        if terminal_event == "MEMORY_ADD_CANCELLED_ALREADY_EXISTS":
                            continue

                        label = 1 if terminal_event == "MEMORY_ADD_APPLIED" else 0
                        if label == 1:
                            stats.positives += 1
                        else:
                            stats.negatives += 1

                        payload, cand_raw, cand_tags, schema_version = _parse_payload(row["payload_json"])
                        if payload is None:
                            stats.bad_payload += 1
                            continue

                        commit_meta = None
                        commit_line = None
                        try:
                            commit_meta = json.loads(row["commit_meta"]) if row["commit_meta"] else None
                            if isinstance(commit_meta, dict):
                                commit_line = commit_meta.get("line")
                        except Exception:
                            stats.bad_commit_meta += 1
                            commit_meta = None

                        enqueued_at = float(row["enqueued_at"] or 0)
                        terminal_at = float(row["terminal_at"] or 0)
                        dwell_sec = terminal_at - enqueued_at if enqueued_at and terminal_at else None

                        lint_meta = None
                        try:
                            lint_raw = row["lint_meta"] if "lint_meta" in row.keys() else None
                            lint_meta = json.loads(lint_raw) if lint_raw else None
                        except Exception:
                            lint_meta = None
                        hard_violation_count, hard_violation_codes = _extract_hard_violations(lint_meta)
                        stats.hard_violation_sum += hard_violation_count
                        stats.hard_violation_max = max(stats.hard_violation_max, hard_violation_count)
                        if hard_violation_count > 0:
                            stats.hard_violation_rows += 1

                        user_text = _get_user_text(conn, row["thread_id"], row["message_id"], enqueued_at)
                        if not user_text:
                            stats.missing_user_text += 1
                        user_text = (user_text or "")[:max_user_text_chars]

                        cand_raw_text = (cand_raw or "")[:max_candidate_chars]

                        weight = _weight(label, dwell_sec)
                        if label == 1 and dwell_sec is not None:
                            stats.dwell_pos_sum += dwell_sec
                            stats.dwell_pos_count += 1
                        if label == 0 and dwell_sec is not None:
                            stats.dwell_neg_sum += dwell_sec
                            stats.dwell_neg_count += 1

                        record = {
                            "label": label,
                            "weight": weight,
                            "pending_action_id": row["pending_action_id"],
                            "thread_id": row["thread_id"],
                            "message_id": row["message_id"],
                            "terminal_event": terminal_event,
                            "enqueued_at": enqueued_at,
                            "terminal_at": terminal_at,
                            "dwell_sec": dwell_sec,
                            "user_text": user_text,
                            "candidate_raw_text": cand_raw_text,
                            "candidate_tags": cand_tags,
                            "schema_version": schema_version,
                            "commit_line": commit_line,
                            "commit_meta": commit_meta,
                            "hard_violation_count": hard_violation_count,
                            "hard_violation_codes": hard_violation_codes,
                        }

                        fout.write(json.dumps(record, ensure_ascii=False) + "\n")

                        if gold_out and label == 1 and weight >= 1.4:
                            gold_out.write(json.dumps(record, ensure_ascii=False) + "\n")
                            stats.gold_count += 1
                    except Exception:
                        stats.bad_payload += 1
                        continue
            finally:
                if gold_out:
                    gold_out.close()
    finally:
        conn.close()

    avg_dwell_pos = stats.dwell_pos_sum / stats.dwell_pos_count if stats.dwell_pos_count else 0.0
    avg_dwell_neg = stats.dwell_neg_sum / stats.dwell_neg_count if stats.dwell_neg_count else 0.0
    avg_hard_violations = stats.hard_violation_sum / stats.total if stats.total else 0.0

    print(
        json.dumps(
            {
                "total": stats.total,
                "positives": stats.positives,
                "negatives": stats.negatives,
                "missing_user_text": stats.missing_user_text,
                "bad_payload": stats.bad_payload,
                "bad_commit_meta": stats.bad_commit_meta,
                "avg_dwell_pos": avg_dwell_pos,
                "avg_dwell_neg": avg_dwell_neg,
                "gold_count": stats.gold_count,
                "avg_hard_violations": avg_hard_violations,
                "hard_violation_rows": stats.hard_violation_rows,
                "hard_violation_max": stats.hard_violation_max,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Gate training JSONL from commit_log + pending_actions.")
    parser.add_argument("--db", required=True, help="Path to SQLite DB (read-only)")
    parser.add_argument("--out", required=True, help="Output JSONL path")
    parser.add_argument("--since", type=float, default=0.0, help="Unix epoch seconds (0 = no filter)")
    parser.add_argument("--limit", type=int, default=0, help="0 = no limit, otherwise limit rows")
    parser.add_argument("--out_gold", default=None, help="Optional gold positives output JSONL")
    parser.add_argument("--max_user_text_chars", type=int, default=800)
    parser.add_argument("--max_candidate_chars", type=int, default=800)
    args = parser.parse_args()

    try:
        build_dataset(
            db_path=args.db,
            out_path=args.out,
            since=args.since,
            limit=args.limit,
            out_gold=args.out_gold,
            max_user_text_chars=args.max_user_text_chars,
            max_candidate_chars=args.max_candidate_chars,
        )
    except sqlite3.OperationalError as e:
        print(f"DB open/query failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
