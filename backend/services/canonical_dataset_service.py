from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Any

from backend.core.db import managed_conn

_CURRENT_DECISION_SCHEMA = "decision_event.v2"
_CURRENT_COMMIT_SCHEMA = "commit_log.v2"


def _scope_meta(thread_id: str | None) -> dict[str, str | None]:
    return {
        "thread_id": thread_id,
        "scope_label": thread_id or "all_threads",
    }


def _load_json(raw: object, *, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _as_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_reason_codes(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in value:
        text = _as_string(item)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _coerce_ts(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _top_counts(counts: dict[str, int], *, limit: int = 10) -> list[dict[str, int | str]]:
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [{"code": code, "count": count} for code, count in ranked[:limit]]


def _decision_label(source: str, decision: str) -> tuple[str | None, str | None]:
    if source == "review_window":
        if decision == "approve":
            return "positive", None
        if decision == "reject":
            return "negative", None
        if decision == "hold":
            return None, "pending_decision"
        if decision == "cancel":
            return None, "cancelled_flow"
        if decision == "token_mismatch":
            return None, "token_mismatch"
        return None, "unsupported_decision"
    if source == "phase5":
        if decision == "approve":
            return "positive", None
        if decision == "reject":
            return "negative", None
        if decision in {"hold", "propose"}:
            return None, "pending_decision"
        return None, "unsupported_decision"
    return None, "unsupported_source"


def _x_post_label(status: str) -> tuple[str | None, str | None]:
    if status == "posted":
        return "positive", None
    if status == "rejected":
        return "negative", None
    if status in {"proposed", "approved", "posting"}:
        return None, "unresolved_status"
    if status == "failed":
        return None, "post_failed"
    return None, "unsupported_status"


def _required_join_fields(sample: dict[str, Any]) -> list[str]:
    sample_kind = str(sample.get("sample_kind") or "")
    source = str(sample.get("source") or "")
    if sample_kind in {"review_decision", "phase5_decision"}:
        return ["turn_id", "message_id", "stream_id"]
    if sample_kind == "x_post_proposal" and source == "phase5_action":
        return ["turn_id", "message_id", "stream_id"]
    return []


def _apply_training_policy(sample: dict[str, Any]) -> dict[str, Any]:
    sample = dict(sample)
    sample_kind = str(sample.get("sample_kind") or "")
    schema_version = str(sample.get("schema_version") or "")

    if sample_kind == "commit_log_orphan":
        label = None
        exclude_reason = _as_string(sample.get("exclude_reason")) or "orphan_commit_log"
        schema_ok = False
    elif sample_kind == "x_post_proposal":
        label, exclude_reason = _x_post_label(str(sample.get("status") or ""))
        schema_ok = True
    else:
        label, exclude_reason = _decision_label(
            str(sample.get("source") or ""),
            str(sample.get("decision") or ""),
        )
        schema_ok = schema_version == _CURRENT_DECISION_SCHEMA
        if not schema_ok:
            exclude_reason = "legacy_schema"

    confidence_issues: list[str] = []
    for field in _required_join_fields(sample):
        if not _as_string(sample.get(field)):
            confidence_issues.append(f"missing_{field}")
    if sample_kind == "review_decision" and sample.get("decision") in {"approve", "reject"}:
        if not sample.get("matched_commit_log"):
            confidence_issues.append("missing_commit_log")

    sample["training_label"] = label
    sample["eligible_for_training"] = bool(label) and schema_ok
    sample["confidence_issues"] = confidence_issues
    sample["high_confidence"] = bool(label) and schema_ok and not confidence_issues
    sample["confidence_tier"] = (
        "high"
        if sample["high_confidence"]
        else "low"
        if sample["eligible_for_training"]
        else "excluded"
    )
    sample["exclude_reason"] = None if sample["eligible_for_training"] else exclude_reason
    return sample


def _load_commit_logs(cursor, thread_id: str | None) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    sql = """
        SELECT id, ts, thread_id, payload_json
        FROM events
        WHERE event_type = 'commit_log'
    """
    params: list[Any] = []
    if thread_id:
        sql += " AND thread_id = ?"
        params.append(thread_id)
    sql += " ORDER BY id ASC"
    rows = cursor.execute(sql, tuple(params)).fetchall()

    by_review_token: dict[str, list[dict[str, Any]]] = defaultdict(list)
    orphan_samples: list[dict[str, Any]] = []

    for row in rows:
        payload = _load_json(row["payload_json"], fallback={})
        schema_version = str(payload.get("schema_version") or "")
        commit = {
            "commit_event_id": row["id"],
            "schema_version": schema_version,
            "thread_id": _as_string(payload.get("thread_id")) or _as_string(row["thread_id"]),
            "turn_id": _as_string(payload.get("turn_id")),
            "message_id": _as_string(payload.get("message_id")),
            "stream_id": _as_string(payload.get("stream_id")),
            "decision": _as_string(payload.get("decision")),
            "actor": _as_string(payload.get("actor")),
            "review_token": _as_string(payload.get("review_token")),
            "line": _as_string(payload.get("line")),
            "hold": _as_string(payload.get("hold")),
            "before_d": payload.get("before_d"),
            "after_d": payload.get("after_d"),
            "reason_codes": _as_reason_codes(payload.get("reason_codes")),
            "ts": _coerce_ts(payload.get("ts")) or _coerce_ts(row["ts"]),
            "matched": False,
        }
        if schema_version != _CURRENT_COMMIT_SCHEMA:
            orphan_samples.append(
                _apply_training_policy(
                    {
                        "sample_id": f"commit_log:{row['id']}",
                        "sample_kind": "commit_log_orphan",
                        "sample_family": "commit_log",
                        "source": "review_window",
                        "thread_id": commit["thread_id"],
                        "turn_id": commit["turn_id"],
                        "message_id": commit["message_id"],
                        "stream_id": commit["stream_id"],
                        "actor": commit["actor"],
                        "decision": commit["decision"],
                        "status": "legacy",
                        "schema_version": schema_version or "legacy",
                        "reason_codes": commit["reason_codes"],
                        "ts": commit["ts"],
                        "exclude_reason": "legacy_commit_schema",
                    }
                )
            )
            continue
        review_token = commit.get("review_token")
        if review_token:
            by_review_token[review_token].append(commit)
            continue
        orphan_samples.append(
            _apply_training_policy(
                {
                    "sample_id": f"commit_log:{row['id']}",
                    "sample_kind": "commit_log_orphan",
                    "sample_family": "commit_log",
                    "source": "review_window",
                    "thread_id": commit["thread_id"],
                    "turn_id": commit["turn_id"],
                    "message_id": commit["message_id"],
                    "stream_id": commit["stream_id"],
                    "actor": commit["actor"],
                    "decision": commit["decision"],
                    "status": "orphan",
                    "schema_version": schema_version,
                    "reason_codes": commit["reason_codes"],
                    "ts": commit["ts"],
                    "exclude_reason": "orphan_commit_log",
                }
            )
        )

    for commits in by_review_token.values():
        commits.sort(key=lambda item: (item.get("ts") or 0.0, item.get("commit_event_id") or 0))
    return by_review_token, orphan_samples


def _match_commit_log(
    *,
    review_token: str | None,
    decision: str | None,
    commit_by_review_token: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    token = _as_string(review_token)
    if not token:
        return None
    commits = commit_by_review_token.get(token) or []
    for item in commits:
        if item.get("matched"):
            continue
        if decision and item.get("decision") and item.get("decision") != decision:
            continue
        item["matched"] = True
        return item
    for item in commits:
        if item.get("matched"):
            continue
        item["matched"] = True
        return item
    return None


def export_canonical_dataset(
    *,
    thread_id: str | None = None,
    limit: int | None = None,
    include_excluded: bool = True,
    high_confidence_only: bool = False,
) -> list[dict[str, Any]]:
    with managed_conn() as conn:
        cursor = conn.cursor()
        commit_by_review_token, orphan_commit_samples = _load_commit_logs(cursor, thread_id)

        decision_sql = """
            SELECT id, ts, thread_id, payload_json
            FROM events
            WHERE event_type = 'decision_event'
        """
        decision_params: list[Any] = []
        if thread_id:
            decision_sql += " AND thread_id = ?"
            decision_params.append(thread_id)
        decision_sql += " ORDER BY id ASC"
        decision_rows = cursor.execute(decision_sql, tuple(decision_params)).fetchall()

        x_sql = "SELECT * FROM x_post_proposals"
        x_params: list[Any] = []
        if thread_id:
            x_sql += " WHERE thread_id = ?"
            x_params.append(thread_id)
        x_sql += " ORDER BY created_at ASC"
        x_rows = cursor.execute(x_sql, tuple(x_params)).fetchall()

    samples: list[dict[str, Any]] = []
    samples.extend(orphan_commit_samples)

    for row in decision_rows:
        payload = _load_json(row["payload_json"], fallback={})
        source = str(payload.get("source") or "")
        if source not in {"review_window", "phase5"}:
            continue
        review_token = _as_string(payload.get("review_token"))
        matched_commit = None
        if source == "review_window" and review_token:
            matched_commit = _match_commit_log(
                review_token=review_token,
                decision=_as_string(payload.get("decision")),
                commit_by_review_token=commit_by_review_token,
            )
        sample = {
            "sample_id": f"decision_event:{row['id']}",
            "sample_family": "decision_event",
            "sample_kind": "review_decision" if source == "review_window" else "phase5_decision",
            "event_id": row["id"],
            "schema_version": str(payload.get("schema_version") or ""),
            "source": source,
            "thread_id": _as_string(payload.get("thread_id")) or _as_string(row["thread_id"]),
            "turn_id": _as_string(payload.get("turn_id")) or (matched_commit or {}).get("turn_id"),
            "message_id": _as_string(payload.get("message_id")) or (matched_commit or {}).get("message_id"),
            "stream_id": _as_string(payload.get("stream_id")) or (matched_commit or {}).get("stream_id"),
            "actor": _as_string(payload.get("actor")),
            "decision": _as_string(payload.get("decision")),
            "status": _as_string(payload.get("status")),
            "reason": _as_string(payload.get("reason")),
            "reason_codes": _as_reason_codes(payload.get("reason_codes")),
            "review_token": review_token,
            "pending_id": _as_string(payload.get("pending_id")),
            "action_id": _as_string(payload.get("action_id")),
            "item_kind": _as_string(payload.get("item_kind")),
            "text": _as_string(payload.get("text")) or _as_string(payload.get("preview_text")),
            "ts": _coerce_ts(payload.get("ts")) or _coerce_ts(row["ts"]),
            "matched_commit_log": bool(matched_commit),
            "commit_log_line": (matched_commit or {}).get("line"),
            "commit_log_hold": (matched_commit or {}).get("hold"),
            "commit_log_before_d": (matched_commit or {}).get("before_d"),
            "commit_log_after_d": (matched_commit or {}).get("after_d"),
        }
        samples.append(_apply_training_policy(sample))

    for commits in commit_by_review_token.values():
        for item in commits:
            if item.get("matched"):
                continue
            samples.append(
                _apply_training_policy(
                    {
                        "sample_id": f"commit_log:{item['commit_event_id']}",
                        "sample_kind": "commit_log_orphan",
                        "sample_family": "commit_log",
                        "source": "review_window",
                        "thread_id": item.get("thread_id"),
                        "turn_id": item.get("turn_id"),
                        "message_id": item.get("message_id"),
                        "stream_id": item.get("stream_id"),
                        "actor": item.get("actor"),
                        "decision": item.get("decision"),
                        "status": "orphan",
                        "schema_version": item.get("schema_version"),
                        "reason_codes": item.get("reason_codes"),
                        "ts": item.get("ts"),
                        "exclude_reason": "orphan_commit_log",
                    }
                )
            )

    for row in x_rows:
        metadata = _load_json(row["metadata_json"], fallback={})
        sample = {
            "sample_id": f"x_post:{row['proposal_id']}",
            "sample_family": "x_post",
            "sample_kind": "x_post_proposal",
            "proposal_id": row["proposal_id"],
            "schema_version": "x_post_proposal.v1",
            "source": _as_string(row["source"]) or "x_post",
            "thread_id": _as_string(row["thread_id"]),
            "turn_id": _as_string(row["turn_id"]),
            "message_id": _as_string(row["message_id"]),
            "stream_id": _as_string(row["stream_id"]),
            "actor": _as_string(row["actor"]),
            "decision": "approve" if row["status"] == "posted" else "reject" if row["status"] == "rejected" else None,
            "status": _as_string(row["status"]),
            "reason": _as_string(row["failure_reason"]),
            "reason_codes": _as_reason_codes(_load_json(row["reason_codes_json"], fallback=[])),
            "tweet_id": _as_string(row["tweet_id"]),
            "text": _as_string(row["posted_text"]) or _as_string(row["approved_text"]) or _as_string(row["candidate_text"]),
            "ts": _coerce_ts(row["posted_at"]) or _coerce_ts(row["rejected_at"]) or _coerce_ts(row["approved_at"]) or _coerce_ts(row["created_at"]),
            "metadata": metadata,
            "source_ref": _as_string(row["source_ref"]),
        }
        samples.append(_apply_training_policy(sample))

    samples.sort(key=lambda item: (item.get("ts") or 0.0, str(item.get("sample_id") or "")), reverse=True)
    if high_confidence_only:
        samples = [item for item in samples if item.get("high_confidence")]
    elif not include_excluded:
        samples = [item for item in samples if item.get("eligible_for_training")]
    if limit is not None:
        samples = samples[: max(int(limit), 0)]
    return samples


def select_training_ready_samples(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baseline_candidates = [
        float(item["ts"])
        for item in samples
        if item.get("high_confidence") and item.get("ts") is not None
    ]
    if not baseline_candidates:
        return []
    baseline_ts = min(baseline_candidates)
    return [
        item
        for item in samples
        if item.get("high_confidence") and item.get("ts") is not None and float(item["ts"]) >= baseline_ts
    ]


def summarize_canonical_dataset(
    samples: list[dict[str, Any]],
    *,
    thread_id: str | None = None,
) -> dict[str, Any]:
    summary = {
        "scope": _scope_meta(thread_id),
        "total_samples": len(samples),
        "eligible_samples": 0,
        "high_confidence_samples": 0,
        "low_confidence_samples": 0,
        "excluded_samples": 0,
        "training_ready_samples": 0,
        "high_confidence_baseline_ts": None,
        "baseline_reason": "current canonical dataset policy: schema-valid labels plus join-complete review/phase5 and durable X proposals",
        "training_policy": "baseline_after_high_confidence_only",
        "sample_kind_breakdown": {},
        "source_breakdown": {},
        "label_breakdown": {},
        "source_audit": [],
        "exclude_reasons": [],
        "confidence_issues": [],
        "join_completeness": {
            "eligible_join_samples": 0,
            "turn_id_present": 0,
            "message_id_present": 0,
            "stream_id_present": 0,
            "full_triplet_present": 0,
        },
        "x_post_status_breakdown": {},
        "x_post_source_breakdown": {},
    }
    if not samples:
        return summary

    sample_kind_counts: dict[str, int] = defaultdict(int)
    source_counts: dict[str, int] = defaultdict(int)
    label_counts: dict[str, int] = defaultdict(int)
    exclude_counts: dict[str, int] = defaultdict(int)
    issue_counts: dict[str, int] = defaultdict(int)
    x_status_counts: dict[str, int] = defaultdict(int)
    x_source_counts: dict[str, int] = defaultdict(int)
    source_audit: dict[str, dict[str, Any]] = {}
    join = summary["join_completeness"]
    baseline_candidates: list[float] = []

    for item in samples:
        sample_kind = str(item.get("sample_kind") or "unknown")
        source = str(item.get("source") or "unknown")
        sample_kind_counts[sample_kind] += 1
        source_counts[source] += 1
        audit = source_audit.setdefault(
            source,
            {
                "source": source,
                "total_samples": 0,
                "eligible_samples": 0,
                "high_confidence_samples": 0,
                "low_confidence_samples": 0,
                "excluded_samples": 0,
                "join_required_samples": 0,
                "full_triplet_present": 0,
            },
        )
        audit["total_samples"] += 1

        label = item.get("training_label")
        if label:
            label_counts[str(label)] += 1

        if item.get("eligible_for_training"):
            summary["eligible_samples"] += 1
            audit["eligible_samples"] += 1
            if item.get("high_confidence"):
                summary["high_confidence_samples"] += 1
                audit["high_confidence_samples"] += 1
                if item.get("ts") is not None:
                    baseline_candidates.append(float(item["ts"]))
            else:
                summary["low_confidence_samples"] += 1
                audit["low_confidence_samples"] += 1
                for issue in item.get("confidence_issues") or []:
                    issue_counts[str(issue)] += 1
        else:
            summary["excluded_samples"] += 1
            audit["excluded_samples"] += 1
            reason = _as_string(item.get("exclude_reason")) or "excluded"
            exclude_counts[reason] += 1

        required_fields = _required_join_fields(item)
        if required_fields and item.get("eligible_for_training"):
            join["eligible_join_samples"] += 1
            audit["join_required_samples"] += 1
            has_turn = bool(_as_string(item.get("turn_id")))
            has_message = bool(_as_string(item.get("message_id")))
            has_stream = bool(_as_string(item.get("stream_id")))
            if has_turn:
                join["turn_id_present"] += 1
            if has_message:
                join["message_id_present"] += 1
            if has_stream:
                join["stream_id_present"] += 1
            if has_turn and has_message and has_stream:
                join["full_triplet_present"] += 1
                audit["full_triplet_present"] += 1

        if sample_kind == "x_post_proposal":
            status = _as_string(item.get("status")) or "unknown"
            x_status_counts[status] += 1
            x_source_counts[source] += 1

    if baseline_candidates:
        summary["high_confidence_baseline_ts"] = min(baseline_candidates)
    summary["training_ready_samples"] = len(select_training_ready_samples(samples))
    summary["sample_kind_breakdown"] = dict(sorted(sample_kind_counts.items(), key=lambda item: (-item[1], item[0])))
    summary["source_breakdown"] = dict(sorted(source_counts.items(), key=lambda item: (-item[1], item[0])))
    summary["label_breakdown"] = dict(sorted(label_counts.items(), key=lambda item: (-item[1], item[0])))
    summary["source_audit"] = sorted(source_audit.values(), key=lambda item: (-item["total_samples"], item["source"]))
    summary["exclude_reasons"] = _top_counts(exclude_counts)
    summary["confidence_issues"] = _top_counts(issue_counts)
    summary["x_post_status_breakdown"] = dict(sorted(x_status_counts.items(), key=lambda item: (-item[1], item[0])))
    summary["x_post_source_breakdown"] = dict(sorted(x_source_counts.items(), key=lambda item: (-item[1], item[0])))
    return summary
