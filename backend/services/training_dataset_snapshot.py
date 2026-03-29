from __future__ import annotations

import asyncio
import csv
import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.core.config import settings
from backend.core.db import managed_conn
from backend.core.logger import logger
from backend.services.canonical_dataset_service import (
    export_canonical_dataset,
    select_training_ready_samples,
    summarize_canonical_dataset,
)


def _read_kv(conn, key: str) -> str | None:
    row = conn.execute("SELECT v FROM telemetry_kv WHERE k=?", (key,)).fetchone()
    return row["v"] if row else None


def _write_kv(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, ?)",
        (key, value, int(time.time())),
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, set):
        return sorted(value)
    return str(value)


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _safe_scope_label(thread_id: str | None) -> str:
    raw = (thread_id or "all_threads").strip() or "all_threads"
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw)
    return cleaned[:80] or "all_threads"


def default_snapshot_dir() -> Path:
    raw = getattr(settings, "TRAINING_DATASET_SNAPSHOT_DIR", "data/training_exports")
    base = Path(raw)
    if not base.is_absolute():
        base = settings.PROJECT_ROOT / base
    return base


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=_json_default))
            f.write("\n")


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames: list[str] = sorted({key for row in rows for key in row.keys()})
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _write_dataset(path: Path, fmt: str, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        _write_csv(path, rows)
    else:
        _write_jsonl(path, rows)


def write_snapshot_bundle(
    *,
    snapshot_dir: Path,
    fmt: str,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    thread_id: str | None,
) -> dict[str, str]:
    date_slug = _local_now().strftime("%Y-%m-%d")
    scope_label = _safe_scope_label(thread_id)
    file_stem = f"{scope_label}_training_ready"
    ext = "csv" if fmt == "csv" else "jsonl"

    dated_dir = snapshot_dir / date_slug
    latest_dir = snapshot_dir / "latest"
    data_path = dated_dir / f"{file_stem}.{ext}"
    summary_path = dated_dir / f"{file_stem}.summary.json"
    latest_data_path = latest_dir / f"{file_stem}.{ext}"
    latest_summary_path = latest_dir / f"{file_stem}.summary.json"

    _write_dataset(data_path, fmt, rows)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )

    latest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(data_path, latest_data_path)
    shutil.copyfile(summary_path, latest_summary_path)
    return {
        "snapshot_data_path": str(data_path),
        "snapshot_summary_path": str(summary_path),
        "latest_data_path": str(latest_data_path),
        "latest_summary_path": str(latest_summary_path),
    }


def _scope_keys(thread_id: str | None) -> dict[str, str]:
    scope = _safe_scope_label(thread_id)
    return {
        "last_date": f"training_dataset_snapshot:last_date:{scope}",
        "last_run_at": f"training_dataset_snapshot:last_run_at:{scope}",
        "last_status": f"training_dataset_snapshot:last_status:{scope}",
        "last_row_count": f"training_dataset_snapshot:last_row_count:{scope}",
        "last_baseline_ts": f"training_dataset_snapshot:last_baseline_ts:{scope}",
        "latest_data_path": f"training_dataset_snapshot:latest_data_path:{scope}",
        "latest_summary_path": f"training_dataset_snapshot:latest_summary_path:{scope}",
        "last_error": f"training_dataset_snapshot:last_error:{scope}",
    }


def write_training_dataset_snapshot(
    *,
    thread_id: str | None = None,
    fmt: str | None = None,
    snapshot_dir: Path | None = None,
) -> dict[str, Any]:
    resolved_fmt = (fmt or getattr(settings, "TRAINING_DATASET_SNAPSHOT_FORMAT", "jsonl")).strip().lower()
    if resolved_fmt not in {"jsonl", "csv"}:
        resolved_fmt = "jsonl"
    target_dir = snapshot_dir or default_snapshot_dir()
    keys = _scope_keys(thread_id)

    try:
        rows = export_canonical_dataset(
            thread_id=thread_id,
            include_excluded=True,
            high_confidence_only=False,
        )
        rows = select_training_ready_samples(rows)
        summary = summarize_canonical_dataset(rows, thread_id=thread_id)
        summary["export_format"] = resolved_fmt
        summary["row_count"] = len(rows)
        outputs = write_snapshot_bundle(
            snapshot_dir=target_dir,
            fmt=resolved_fmt,
            rows=rows,
            summary=summary,
            thread_id=thread_id,
        )
        now = time.time()
        with managed_conn() as conn:
            _write_kv(conn, keys["last_date"], _local_now().strftime("%Y-%m-%d"))
            _write_kv(conn, keys["last_run_at"], str(now))
            _write_kv(conn, keys["last_status"], "ok")
            _write_kv(conn, keys["last_row_count"], str(len(rows)))
            _write_kv(conn, keys["last_baseline_ts"], str(summary.get("high_confidence_baseline_ts") or ""))
            _write_kv(conn, keys["latest_data_path"], outputs["latest_data_path"])
            _write_kv(conn, keys["latest_summary_path"], outputs["latest_summary_path"])
            _write_kv(conn, keys["last_error"], "")
        result = {
            "ok": True,
            "thread_id": thread_id,
            "row_count": len(rows),
            "training_ready_samples": summary.get("training_ready_samples", 0),
            "high_confidence_baseline_ts": summary.get("high_confidence_baseline_ts"),
            **outputs,
        }
        logger.info(
            "[TRAINING_DATASET] snapshot ok scope=%s rows=%s path=%s",
            _safe_scope_label(thread_id),
            len(rows),
            outputs["snapshot_data_path"],
        )
        return result
    except Exception as exc:
        with managed_conn() as conn:
            _write_kv(conn, keys["last_run_at"], str(time.time()))
            _write_kv(conn, keys["last_status"], "error")
            _write_kv(conn, keys["last_error"], str(exc)[:500])
        logger.exception("[TRAINING_DATASET] snapshot failed scope=%s", _safe_scope_label(thread_id))
        raise


def run_daily_training_dataset_snapshot_if_due(
    *,
    thread_id: str | None = None,
    fmt: str | None = None,
    snapshot_dir: Path | None = None,
    force: bool = False,
    current_time: datetime | None = None,
) -> dict[str, Any]:
    now = current_time or _local_now()
    keys = _scope_keys(thread_id)
    today = now.strftime("%Y-%m-%d")
    target_hour = int(getattr(settings, "TRAINING_DATASET_SNAPSHOT_HOUR_LOCAL", 4))

    with managed_conn() as conn:
        last_date = _read_kv(conn, keys["last_date"])
        if not force:
            if now.hour < target_hour:
                return {"ok": True, "ran": False, "reason": "before_target_hour", "target_hour": target_hour}
            if last_date == today:
                return {"ok": True, "ran": False, "reason": "already_snapshotted_today", "date": today}

    result = write_training_dataset_snapshot(thread_id=thread_id, fmt=fmt, snapshot_dir=snapshot_dir)
    result["ran"] = True
    result["date"] = today
    return result


async def training_dataset_snapshot_loop() -> None:
    interval = int(getattr(settings, "TRAINING_DATASET_SNAPSHOT_INTERVAL_SEC", 3600))
    thread_id = getattr(settings, "TRAINING_DATASET_SNAPSHOT_THREAD_ID", None)
    fmt = getattr(settings, "TRAINING_DATASET_SNAPSHOT_FORMAT", "jsonl")
    snapshot_dir = default_snapshot_dir()
    boot = bool(getattr(settings, "TRAINING_DATASET_SNAPSHOT_BOOT", True))

    logger.info(
        "[TRAINING_DATASET] loop started interval=%ss hour=%s scope=%s",
        interval,
        getattr(settings, "TRAINING_DATASET_SNAPSHOT_HOUR_LOCAL", 4),
        _safe_scope_label(thread_id),
    )

    while True:
        try:
            if boot:
                boot = False
                await asyncio.to_thread(
                    run_daily_training_dataset_snapshot_if_due,
                    thread_id=thread_id,
                    fmt=fmt,
                    snapshot_dir=snapshot_dir,
                )
            await asyncio.sleep(interval)
            await asyncio.to_thread(
                run_daily_training_dataset_snapshot_if_due,
                thread_id=thread_id,
                fmt=fmt,
                snapshot_dir=snapshot_dir,
            )
        except asyncio.CancelledError:
            logger.info("[TRAINING_DATASET] loop stopped")
            raise
        except Exception:
            logger.exception("[TRAINING_DATASET] loop error")
