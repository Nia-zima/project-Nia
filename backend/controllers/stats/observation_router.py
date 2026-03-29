"""Observation Report API - 観測ログの集計レポートを返す"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from backend.scripts.observation_report import (
    LOG_FILE,
    _load_records,
    generate_report_data,
)

router = APIRouter()


@router.get("/observation_report")
def get_observation_report(
    last: int | None = Query(None, ge=1, description="直近 N ターンのみ集計"),
    since: str | None = Query(None, description="この ISO timestamp 以降のみ (例: 2026-02-10)"),
    file: str | None = Query(None, description="JSONL ファイルパス (デフォルト: 標準ログ)"),
) -> dict[str, Any]:
    path = Path(file) if file else LOG_FILE
    records = _load_records(path, last_n=last, since=since)
    return generate_report_data(records)
