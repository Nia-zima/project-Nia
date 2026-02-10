# Usage:
#   python train_gate.py --data data.jsonl --out_dir ./gate_artifacts --seed 42 --dev_ratio 0.2 --max_train 0
#
# Minimal training pipeline for MemoryGate (Phase3 v1).
# Uses few-shot selection and optional DSPy inference.

from __future__ import annotations

import argparse
import json
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.services.gate_codes import validate_code


@dataclass
class Example:
    label: int
    weight: float
    user_text: str
    candidate_raw_text: str
    candidate_tags: str
    rationale_code: str | None = None


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _split(rows: List[Example], seed: int, dev_ratio: float) -> Tuple[List[Example], List[Example]]:
    rng = random.Random(seed)
    items = rows[:]
    rng.shuffle(items)
    dev_size = int(len(items) * dev_ratio)
    dev = items[:dev_size]
    train = items[dev_size:]
    return train, dev


def _select_fewshot(train: List[Example], *, max_pos: int = 6, max_neg: int = 6) -> List[Example]:
    gold_pos = [e for e in train if e.label == 1 and e.weight >= 1.4]
    other_pos = [e for e in train if e.label == 1 and e.weight < 1.4]
    neg = [e for e in train if e.label == 0]
    few = []
    few.extend(gold_pos[:max_pos])
    if len(few) < max_pos:
        few.extend(other_pos[: max_pos - len(few)])
    few.extend(neg[:max_neg])
    return few


def _to_examples(rows: List[Dict[str, Any]]) -> List[Example]:
    out: List[Example] = []
    for r in rows:
        try:
            out.append(
                Example(
                    label=int(r.get("label", 0)),
                    weight=float(r.get("weight", 1.0)),
                    user_text=str(r.get("user_text") or ""),
                    candidate_raw_text=str(r.get("candidate_raw_text") or ""),
                    candidate_tags=str(r.get("candidate_tags") or ""),
                )
            )
        except Exception:
            continue
    return out


def _metrics(pairs: List[Tuple[int, int]]) -> Dict[str, float]:
    tp = sum(1 for y, yhat in pairs if y == 1 and yhat == 1)
    tn = sum(1 for y, yhat in pairs if y == 0 and yhat == 0)
    fp = sum(1 for y, yhat in pairs if y == 0 and yhat == 1)
    fn = sum(1 for y, yhat in pairs if y == 1 and yhat == 0)
    total = max(1, tp + tn + fp + fn)
    acc = (tp + tn) / total
    prec = tp / max(1, tp + fp)
    rec = tp / max(1, tp + fn)
    return {"accuracy": acc, "precision": prec, "recall": rec}


def _baseline_predict(ex: Example) -> Tuple[int, str, str]:
    # Simple deterministic fallback: propose only if candidate_raw_text has content.
    should = 1 if ex.candidate_raw_text.strip() else 0
    code = "origin_preference" if should == 1 else "low_signal"
    code, _ = validate_code(code)
    rationale = "has candidate content" if should == 1 else "no candidate content"
    return should, rationale, code


def _save_json(path: Path, obj: Dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train/optimize MemoryGate (Phase3 v1).")
    parser.add_argument("--data", required=True, help="Input JSONL")
    parser.add_argument("--out_dir", required=True, help="Output directory")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dev_ratio", type=float, default=0.2)
    parser.add_argument("--max_train", type=int, default=0, help="0 = no limit")
    args = parser.parse_args()

    rows = _read_jsonl(args.data)
    examples = _to_examples(rows)
    if args.max_train and args.max_train > 0:
        examples = examples[: args.max_train]

    train, dev = _split(examples, args.seed, args.dev_ratio)
    fewshot = _select_fewshot(train)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _save_json(out_dir / "split_meta.json", {"train": len(train), "dev": len(dev), "seed": args.seed})

    fewshot_json = [
        {
            "label": e.label,
            "weight": e.weight,
            "user_text": e.user_text,
            "candidate_raw_text": e.candidate_raw_text,
            "candidate_tags": e.candidate_tags,
        }
        for e in fewshot
    ]
    _save_json(out_dir / "fewshot.json", {"examples": fewshot_json})

    # Optional DSPy inference
    dspy_available = False
    predictor = None
    try:
        import dspy  # type: ignore

        dspy_available = True

        class MemoryGateSignature(dspy.Signature):
            """
            Decide whether to propose memory_add. Output one rationale_code from:
            too_trivial, low_signal, already_known, out_of_context, ephemeral, private_sensitive,
            needs_confirmation, origin_preference, origin_goal, system_contract, high_value_insight, origin_essence
            """

            user_text: str = dspy.InputField()
            candidate_raw_text: str = dspy.InputField()
            candidate_tags: str = dspy.InputField()
            should_propose: bool = dspy.OutputField()
            rationale: str = dspy.OutputField()
            rationale_code: str = dspy.OutputField()

        predictor = dspy.Predict(MemoryGateSignature)
    except Exception:
        dspy_available = False

    preds: List[Tuple[int, int]] = []
    for ex in dev:
        if dspy_available and predictor is not None:
            try:
                out = predictor(
                    user_text=ex.user_text,
                    candidate_raw_text=ex.candidate_raw_text,
                    candidate_tags=ex.candidate_tags,
                )
                should = 1 if bool(getattr(out, "should_propose", False)) else 0
                code = getattr(out, "rationale_code", None)
                code, _ = validate_code(code)
            except Exception:
                should, _, code = _baseline_predict(ex)
        else:
            should, _, code = _baseline_predict(ex)
        preds.append((ex.label, should))

    metrics = _metrics(preds)
    _save_json(out_dir / "metrics.json", metrics)

    config = {
        "dspy_available": dspy_available,
        "seed": args.seed,
        "dev_ratio": args.dev_ratio,
        "max_train": args.max_train,
    }
    _save_json(out_dir / "config.json", config)

    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
