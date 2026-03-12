from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import shutil
import sys
from typing import Any
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.services.canonical_dataset_service import (
    export_canonical_dataset,
    select_training_ready_samples,
    summarize_canonical_dataset,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export canonical Nia dataset rows to JSONL or CSV.")
    parser.add_argument("--thread-id", default=None, help="Optional thread scope. Omit for all threads.")
    parser.add_argument("--limit", type=int, default=None, help="Optional max row count before export.")
    parser.add_argument("--format", choices=("jsonl", "csv"), default="jsonl")
    parser.add_argument("--out", default=None, help="Optional explicit output file path.")
    parser.add_argument(
        "--snapshot-dir",
        default=None,
        help="Optional base directory for dated snapshots. Writes YYYY-MM-DD and latest copies.",
    )
    parser.add_argument("--summary-out", default=None, help="Optional JSON summary path.")
    parser.add_argument("--include-excluded", action="store_true", help="Keep excluded rows in the export.")
    parser.add_argument("--high-confidence-only", action="store_true", help="Export only high-confidence rows.")
    parser.add_argument(
        "--training-ready-only",
        action="store_true",
        help="Export only training-ready rows (baseline-after high-confidence subset).",
    )
    return parser


def _json_default(value: Any) -> Any:
    if isinstance(value, set):
        return sorted(value)
    return str(value)


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


def _safe_scope_label(thread_id: str | None) -> str:
    raw = (thread_id or "all_threads").strip() or "all_threads"
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw)
    return cleaned[:80] or "all_threads"


def _default_snapshot_dir() -> Path:
    return PROJECT_ROOT / "data" / "training_exports"


def _write_dataset(path: Path, fmt: str, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        _write_csv(path, rows)
    else:
        _write_jsonl(path, rows)


def _write_snapshot_bundle(
    *,
    snapshot_dir: Path,
    fmt: str,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    thread_id: str | None,
) -> dict[str, str]:
    date_slug = datetime.now().astimezone().strftime("%Y-%m-%d")
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


def main() -> int:
    args = _build_parser().parse_args()
    if not args.out and not args.snapshot_dir:
        raise SystemExit("--out or --snapshot-dir is required")
    rows = export_canonical_dataset(
        thread_id=args.thread_id,
        limit=args.limit,
        include_excluded=args.include_excluded or not (args.high_confidence_only or args.training_ready_only),
        high_confidence_only=args.high_confidence_only,
    )
    if args.training_ready_only:
        rows = select_training_ready_samples(rows)

    summary = summarize_canonical_dataset(rows, thread_id=args.thread_id)
    summary["export_format"] = args.format
    summary["row_count"] = len(rows)
    outputs: dict[str, str] = {}
    if args.out:
        out_path = Path(args.out)
        _write_dataset(out_path, args.format, rows)
        outputs["output_path"] = str(out_path)
        summary["output_path"] = str(out_path)
    if args.snapshot_dir:
        snapshot_outputs = _write_snapshot_bundle(
            snapshot_dir=Path(args.snapshot_dir) if args.snapshot_dir else _default_snapshot_dir(),
            fmt=args.format,
            rows=rows,
            summary=summary,
            thread_id=args.thread_id,
        )
        outputs.update(snapshot_outputs)
    if args.summary_out:
        summary_path = Path(args.summary_out)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "ok": True,
                "row_count": len(rows),
                "high_confidence_samples": summary.get("high_confidence_samples"),
                "training_ready_samples": summary.get("training_ready_samples"),
                "high_confidence_baseline_ts": summary.get("high_confidence_baseline_ts"),
                **outputs,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
