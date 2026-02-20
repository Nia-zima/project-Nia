"""
observation_report.py - 観測ログ集計レポート

turn_observations.jsonl を読み込み、Phase 2 メトリクスの分布を出力する。
データが蓄積されたらしきい値チューニングの判断材料として使う。

Usage:
    python -m backend.scripts.observation_report
    python -m backend.scripts.observation_report --last 100
    python -m backend.scripts.observation_report --since 2026-02-10

=== 評価メトリクス定義 ===

1. 誤検知率 (false_positive_rate)
   定義: external_used=True かつ feedback で useful=False だった割合
   データ源: feedback_log（Broker 内）+ turn_observations.jsonl
   目標: < 30%（初期は許容範囲広め、データ蓄積後に 20% 未満を目指す）

2. 取得率 (fetch_rate)
   定義: gate_a_pass=True のターンのうち、external_used=True になった割合
   データ源: turn_observations.jsonl (gate_a_pass, external_used)
   目標: gate が通ったら 60% 以上は実際に取得・統合される状態

3. 統合率 (integration_rate)
   定義: 外部取得を試みた（gate_a_pass=True）ターンのうち、
         confidence >= min_confidence かつ contradiction=False で統合された割合
   データ源: turn_observations.jsonl (gate_a_pass, external_used, external_confidence, contradiction_flag)
   目標: 50% 以上（低すぎるならしきい値を下げるか、ソース品質を改善）

4. 矛盾率 (contradiction_rate)
   定義: 外部取得したターンのうち contradiction_flag=True の割合
   データ源: turn_observations.jsonl
   目標: < 15%（高すぎるならソース選択やクエリ品質を見直す）

5. surprise/dissonance 分離精度
   評価方法: 両スコアの相関係数を算出。
   目標: r < 0.5（高相関なら分離が不十分 = 同じものを二重計測している）

=== しきい値チューニング指針 ===

- 初期しきい値は保守的に設定済み（min_confidence=0.65, surprise_threshold=0.8）
- 100ターン以上のデータ蓄積後に初回チューニングを実施
- 統合率が低すぎる → min_confidence を 0.05 下げる
- 誤検知率が高すぎる → surprise_threshold を 0.05 上げる
- 矛盾率が高い → ソース重みを再調整 or 単一ソースモードに切替
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT / "logs" / "observations"
LOG_FILE = LOG_DIR / "turn_observations.jsonl"


def _load_records(
    path: Path,
    *,
    last_n: int | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    """JSONL ファイルからレコードを読み込む。ローテーション済みファイルも含む。"""
    files = sorted(path.parent.glob(path.name + "*"))  # .1, .2, ... も含む
    records: list[dict[str, Any]] = []
    for f in files:
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except Exception:
            continue

    if since:
        records = [r for r in records if str(r.get("timestamp", "")) >= since]

    records.sort(key=lambda r: str(r.get("timestamp", "")))

    if last_n is not None and last_n > 0:
        records = records[-last_n:]

    return records


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[f]
    return s[f] * (c - k) + s[c] * (k - f)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _correlation(xs: list[float], ys: list[float]) -> float:
    """ピアソン相関係数。データが少ない場合は 0.0 を返す。"""
    n = min(len(xs), len(ys))
    if n < 5:
        return 0.0
    mx, my = _mean(xs[:n]), _mean(ys[:n])
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    dx = math.sqrt(sum((xs[i] - mx) ** 2 for i in range(n)))
    dy = math.sqrt(sum((ys[i] - my) ** 2 for i in range(n)))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def _histogram(values: list[float], bins: int = 10) -> list[tuple[str, int]]:
    if not values:
        return []
    lo, hi = 0.0, 1.0
    step = (hi - lo) / bins
    buckets: list[int] = [0] * bins
    for v in values:
        idx = min(int((v - lo) / step), bins - 1)
        buckets[idx] += 1
    return [(f"{lo + i * step:.2f}-{lo + (i + 1) * step:.2f}", buckets[i]) for i in range(bins)]


def _bar(count: int, total: int, width: int = 30) -> str:
    if total == 0:
        return ""
    filled = round(count / total * width)
    return "#" * filled + "." * (width - filled)


def _histogram_data(values: list[float], bins: int = 10) -> list[dict[str, Any]]:
    """JSON 向けヒストグラムデータ。"""
    if not values:
        return []
    lo, hi = 0.0, 1.0
    step = (hi - lo) / bins
    buckets: list[int] = [0] * bins
    for v in values:
        idx = min(int((v - lo) / step), bins - 1)
        buckets[idx] += 1
    total = len(values)
    return [
        {
            "range": f"{lo + i * step:.2f}-{lo + (i + 1) * step:.2f}",
            "count": buckets[i],
            "pct": round(buckets[i] / total * 100, 1) if total else 0.0,
        }
        for i in range(bins)
    ]


def _score_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"mean": 0.0, "median": 0.0, "p90": 0.0, "max": 0.0, "histogram": []}
    return {
        "mean": round(_mean(values), 4),
        "median": round(_percentile(values, 0.5), 4),
        "p90": round(_percentile(values, 0.9), 4),
        "max": round(max(values), 4),
        "histogram": _histogram_data(values),
    }


def generate_report_data(records: list[dict[str, Any]]) -> dict[str, Any]:
    """JSON API 向けの構造化レポートデータを生成する。"""
    n = len(records)
    if not records:
        return {"total_turns": 0, "period": None, "recommendations": [{"level": "info", "message": "No data."}]}

    first_ts = str(records[0].get("timestamp", ""))
    last_ts = str(records[-1].get("timestamp", ""))

    # Depth distribution
    depth_counts: dict[int, int] = {}
    for r in records:
        d = int(r.get("depth") or 0)
        depth_counts[d] = depth_counts.get(d, 0) + 1
    depth_distribution = [
        {"depth": d, "count": c, "pct": round(c / n * 100, 1)}
        for d, c in sorted(depth_counts.items())
    ]

    # Score distributions
    diss = [float(r.get("dissonance") or 0) for r in records]
    surp = [float(r.get("surprise_score") or 0) for r in records]
    corr = _correlation(diss, surp)

    # External pipeline
    gate_pass = [r for r in records if r.get("gate_a_pass")]
    ext_used = [r for r in records if r.get("external_used")]
    integrated = [r for r in gate_pass if r.get("external_used") and not r.get("contradiction_flag")]
    contradictions = [r for r in ext_used if r.get("contradiction_flag")]
    n_gate = len(gate_pass)
    n_ext = len(ext_used)
    n_contra = len(contradictions)

    ext_conf = [float(r.get("external_confidence") or 0) for r in ext_used if r.get("external_confidence") is not None]

    # Hold
    holds = [r for r in records if r.get("hold_required")]

    # Merge modes
    modes: dict[str, int] = {}
    for r in records:
        m = str(r.get("merge_mode") or "unknown")
        modes[m] = modes.get(m, 0) + 1
    merge_modes = sorted(
        [{"mode": m, "count": c, "pct": round(c / n * 100, 1)} for m, c in modes.items()],
        key=lambda x: x["count"],
        reverse=True,
    )

    # Recommendations
    recommendations: list[dict[str, str]] = []
    if n < 100:
        recommendations.append({"level": "info", "message": f"{n} turns collected. Need >= 100 for reliable tuning."})
    else:
        if n_gate > 0 and n_ext / n_gate < 0.5:
            recommendations.append({"level": "action", "message": "Fetch rate < 50%. Consider lowering surprise_threshold by 0.05."})
        if n_gate > 0 and len(integrated) / n_gate < 0.3:
            recommendations.append({"level": "action", "message": "Integration rate < 30%. Consider lowering min_confidence by 0.05."})
        if n_ext > 0 and n_contra / n_ext > 0.15:
            recommendations.append({"level": "action", "message": "Contradiction rate > 15%. Review source quality or switch to single-source mode."})
        if abs(corr) >= 0.5:
            recommendations.append({"level": "action", "message": "Surprise-Dissonance r >= 0.5. The two scores may overlap; review keyword sets."})
        if not recommendations:
            recommendations.append({"level": "ok", "message": "All metrics within target ranges."})

    return {
        "total_turns": n,
        "period": {"start": first_ts, "end": last_ts},
        "depth_distribution": depth_distribution,
        "dissonance": _score_summary(diss),
        "surprise": _score_summary(surp),
        "correlation": {"r": round(corr, 4), "status": "ok" if abs(corr) < 0.5 else "warning"},
        "external_pipeline": {
            "gate_pass_count": n_gate,
            "gate_pass_pct": round(n_gate / n * 100, 1),
            "external_used_count": n_ext,
            "external_used_pct": round(n_ext / n * 100, 1),
            "fetch_rate": round(n_ext / n_gate * 100, 1) if n_gate > 0 else None,
            "integration_rate": round(len(integrated) / n_gate * 100, 1) if n_gate > 0 else None,
            "contradiction_count": n_contra,
            "contradiction_rate": round(n_contra / n_ext * 100, 1) if n_ext > 0 else None,
        },
        "external_confidence": _score_summary(ext_conf),
        "hold": {"count": len(holds), "pct": round(len(holds) / n * 100, 1)},
        "merge_modes": merge_modes,
        "recommendations": recommendations,
    }


def generate_report(records: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    n = len(records)
    lines.append(f"=== Observation Report ({n} turns) ===")
    if not records:
        lines.append("No data.")
        return "\n".join(lines)

    first_ts = str(records[0].get("timestamp", "?"))
    last_ts = str(records[-1].get("timestamp", "?"))
    lines.append(f"Period: {first_ts} .. {last_ts}")
    lines.append("")

    # --- Depth distribution ---
    depths = [int(r.get("depth") or 0) for r in records]
    depth_counts: dict[int, int] = {}
    for d in depths:
        depth_counts[d] = depth_counts.get(d, 0) + 1
    lines.append("--- Depth Distribution ---")
    for d in sorted(depth_counts):
        c = depth_counts[d]
        lines.append(f"  depth={d}: {c:>5} ({c / n * 100:5.1f}%) {_bar(c, n)}")
    lines.append("")

    # --- Dissonance ---
    diss = [float(r.get("dissonance") or 0) for r in records]
    lines.append("--- Dissonance ---")
    lines.append(f"  mean={_mean(diss):.3f}  median={_percentile(diss, 0.5):.3f}  p90={_percentile(diss, 0.9):.3f}  max={max(diss):.3f}")
    for label, count in _histogram(diss):
        lines.append(f"  {label}: {count:>5} {_bar(count, n)}")
    lines.append("")

    # --- Surprise Score ---
    surp = [float(r.get("surprise_score") or 0) for r in records]
    lines.append("--- Surprise Score ---")
    lines.append(f"  mean={_mean(surp):.3f}  median={_percentile(surp, 0.5):.3f}  p90={_percentile(surp, 0.9):.3f}  max={max(surp):.3f}")
    for label, count in _histogram(surp):
        lines.append(f"  {label}: {count:>5} {_bar(count, n)}")
    lines.append("")

    # --- Surprise / Dissonance Correlation ---
    corr = _correlation(diss, surp)
    verdict = "OK (well separated)" if abs(corr) < 0.5 else "WARNING: high correlation, may be measuring same thing"
    lines.append(f"--- Surprise-Dissonance Correlation ---")
    lines.append(f"  r = {corr:+.3f}  ({verdict})")
    lines.append("")

    # --- External Data Pipeline ---
    gate_pass = [r for r in records if r.get("gate_a_pass")]
    ext_used = [r for r in records if r.get("external_used")]
    contradictions = [r for r in ext_used if r.get("contradiction_flag")]

    n_gate = len(gate_pass)
    n_ext = len(ext_used)
    n_contra = len(contradictions)

    lines.append("--- External Data Pipeline ---")
    lines.append(f"  Total turns:      {n}")
    lines.append(f"  Gate A passed:    {n_gate:>5} ({n_gate / n * 100:5.1f}%)")
    lines.append(f"  External used:    {n_ext:>5} ({n_ext / n * 100:5.1f}%)")

    # 取得率: gate通過のうち外部使用
    if n_gate > 0:
        fetch_rate = n_ext / n_gate
        lines.append(f"  Fetch rate:       {fetch_rate * 100:5.1f}% (external_used / gate_pass)")
    else:
        lines.append(f"  Fetch rate:       N/A (no gate passes)")

    # 統合率: gate通過のうち confidence >= 0.65 & contradiction=False
    integrated = [r for r in gate_pass if r.get("external_used") and not r.get("contradiction_flag")]
    if n_gate > 0:
        int_rate = len(integrated) / n_gate
        lines.append(f"  Integration rate: {int_rate * 100:5.1f}% (used & !contradiction / gate_pass)")
    else:
        lines.append(f"  Integration rate: N/A")

    # 矛盾率
    if n_ext > 0:
        contra_rate = n_contra / n_ext
        lines.append(f"  Contradiction:    {n_contra:>5} ({contra_rate * 100:5.1f}% of external_used)")
    else:
        lines.append(f"  Contradiction:    N/A")
    lines.append("")

    # --- External Confidence (when used) ---
    ext_conf = [float(r.get("external_confidence") or 0) for r in ext_used if r.get("external_confidence") is not None]
    if ext_conf:
        lines.append("--- External Confidence (when used) ---")
        lines.append(f"  mean={_mean(ext_conf):.3f}  median={_percentile(ext_conf, 0.5):.3f}  p90={_percentile(ext_conf, 0.9):.3f}")
        for label, count in _histogram(ext_conf):
            lines.append(f"  {label}: {count:>5} {_bar(count, len(ext_conf))}")
        lines.append("")

    # --- Hold / Review ---
    holds = [r for r in records if r.get("hold_required")]
    lines.append("--- Hold / Review ---")
    lines.append(f"  Hold required:    {len(holds):>5} ({len(holds) / n * 100:5.1f}%)")
    lines.append("")

    # --- Merge Mode Distribution ---
    modes: dict[str, int] = {}
    for r in records:
        m = str(r.get("merge_mode") or "unknown")
        modes[m] = modes.get(m, 0) + 1
    lines.append("--- Merge Mode ---")
    for m in sorted(modes, key=modes.get, reverse=True):  # type: ignore[arg-type]
        c = modes[m]
        lines.append(f"  {m:>20}: {c:>5} ({c / n * 100:5.1f}%)")
    lines.append("")

    # --- Tuning Recommendations ---
    lines.append("--- Tuning Recommendations ---")
    if n < 100:
        lines.append(f"  [INFO] {n} turns collected. Need >= 100 for reliable tuning.")
    else:
        if n_gate > 0 and n_ext / n_gate < 0.5:
            lines.append("  [ACTION] Fetch rate < 50%. Consider lowering surprise_threshold by 0.05.")
        if n_gate > 0 and len(integrated) / n_gate < 0.3:
            lines.append("  [ACTION] Integration rate < 30%. Consider lowering min_confidence by 0.05.")
        if n_ext > 0 and n_contra / n_ext > 0.15:
            lines.append("  [ACTION] Contradiction rate > 15%. Review source quality or switch to single-source mode.")
        if abs(corr) >= 0.5:
            lines.append("  [ACTION] Surprise-Dissonance r >= 0.5. The two scores may overlap; review keyword sets.")
        if not any(line.startswith("  [ACTION]") for line in lines):
            lines.append("  [OK] All metrics within target ranges.")

    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Observation log report")
    parser.add_argument("--last", type=int, default=None, help="Only use last N records")
    parser.add_argument("--since", type=str, default=None, help="Only records since this ISO timestamp (e.g. 2026-02-10)")
    parser.add_argument("--file", type=str, default=None, help="Path to JSONL file (default: logs/observations/turn_observations.jsonl)")
    args = parser.parse_args()

    path = Path(args.file) if args.file else LOG_FILE
    records = _load_records(path, last_n=args.last, since=args.since)
    print(generate_report(records))


if __name__ == "__main__":
    main()
