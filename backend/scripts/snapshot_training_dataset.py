from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.services.training_dataset_snapshot import (
    default_snapshot_dir,
    write_training_dataset_snapshot,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write dated training-ready dataset snapshots to data/training_exports.")
    parser.add_argument("--thread-id", default=None, help="Optional thread scope.")
    parser.add_argument("--format", choices=("jsonl", "csv"), default="jsonl")
    parser.add_argument("--snapshot-dir", default=None, help="Optional override for the snapshot base directory.")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    snapshot_dir = Path(args.snapshot_dir) if args.snapshot_dir else default_snapshot_dir()
    result = write_training_dataset_snapshot(
        thread_id=args.thread_id,
        fmt=args.format,
        snapshot_dir=snapshot_dir,
    )
    print(
        json.dumps(
            {
                **result,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
