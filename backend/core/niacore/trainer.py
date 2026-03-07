"""NiaCore Trainer — 報酬計算 + バッチ学習.

Sleep Cycle で呼ばれ、Experience Buffer から学習する。
Design doc: docs/niacore_lnn_design.md §3
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from backend.core.config import settings
from backend.core.db import managed_conn
from backend.core.logger import logger

try:
    import torch
    import torch.nn as nn

    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False

# ═══════════════════════════════════════════════════════════════
# Reward Table (§3.2)
# ═══════════════════════════════════════════════════════════════

_REWARD_TABLE = {
    "rejected": -1.0,
    "correction": -0.8,
    "deviation_success": +1.0,
    "agreement_continued": +0.1,
    "unknown": 0.0,
}

# Credit assignment: γ decay over past turns within same session
_CREDIT_GAMMA = 0.9
_CREDIT_CORRECTION_LOOKBACK = 5
_CREDIT_REJECTED_LOOKBACK = 2
_CREDIT_DEVIATION_SUCCESS_LOOKBACK = 2


# ═══════════════════════════════════════════════════════════════
# 1. Mark conversation_continued
# ═══════════════════════════════════════════════════════════════

def mark_conversation_continued() -> int:
    """correction_window_closed=1 AND rejected=0 AND correction=0 → continued=1.

    Returns number of rows updated.
    """
    try:
        with managed_conn() as conn:
            cursor = conn.execute(
                """UPDATE niacore_experience
                   SET conversation_continued = 1
                   WHERE correction_window_closed = 1
                     AND review_rejected = 0
                     AND user_correction = 0
                     AND conversation_continued = 0
                     AND reward IS NULL"""
            )
            return cursor.rowcount
    except Exception:
        logger.warning("[NiaCore] mark_conversation_continued failed", exc_info=True)
        return 0


# ═══════════════════════════════════════════════════════════════
# 2. Reward Computation
# ═══════════════════════════════════════════════════════════════

def _determine_event_type(row: dict) -> str:
    """行の状態から報酬イベントタイプを決定."""
    if row["review_rejected"]:
        return "rejected"
    if row["user_correction"]:
        return "correction"
    if row["is_deviation"] and row["conversation_continued"]:
        return "deviation_success"
    if not row["is_deviation"] and row["conversation_continued"]:
        return "agreement_continued"
    return "unknown"


def compute_rewards() -> int:
    """outcome_known かつ reward IS NULL の行に報酬を計算。

    outcome_known = review_checked AND correction_window_closed
    Returns number of rows rewarded.
    """
    rewarded = 0
    try:
        with managed_conn() as conn:
            rows = conn.execute(
                """SELECT id, session_id, turn_id, is_deviation,
                          review_rejected, user_correction,
                          conversation_continued, timestamp
                   FROM niacore_experience
                   WHERE review_checked = 1
                     AND correction_window_closed = 1
                     AND reward IS NULL
                   ORDER BY timestamp ASC"""
            ).fetchall()

            for row in rows:
                row_dict = dict(row)
                event_type = _determine_event_type(row_dict)
                reward = _REWARD_TABLE.get(event_type, 0.0)

                # Direct reward
                conn.execute(
                    "UPDATE niacore_experience SET reward = ? WHERE id = ?",
                    (reward, row_dict["id"]),
                )
                rewarded += 1

                # Credit assignment to past turns
                if event_type in ("correction", "rejected", "deviation_success"):
                    lookback = {
                        "correction": _CREDIT_CORRECTION_LOOKBACK,
                        "rejected": _CREDIT_REJECTED_LOOKBACK,
                        "deviation_success": _CREDIT_DEVIATION_SUCCESS_LOOKBACK,
                    }[event_type]
                    _apply_credit_assignment(
                        conn,
                        session_id=row_dict["session_id"],
                        current_ts=row_dict["timestamp"],
                        reward=reward,
                        lookback=lookback,
                    )

    except Exception:
        logger.warning("[NiaCore] compute_rewards failed", exc_info=True)
    return rewarded


def _apply_credit_assignment(
    conn,
    *,
    session_id: str | None,
    current_ts: float,
    reward: float,
    lookback: int,
) -> None:
    """過去ターンへの報酬分配。session_id 内限定。γ=0.9 で減衰。"""
    if not session_id:
        return

    past_rows = conn.execute(
        """SELECT id, reward FROM niacore_experience
           WHERE session_id = ?
             AND timestamp < ?
             AND reward IS NOT NULL
           ORDER BY timestamp DESC
           LIMIT ?""",
        (session_id, current_ts, lookback),
    ).fetchall()

    for i, past_row in enumerate(past_rows):
        gamma_factor = _CREDIT_GAMMA ** (i + 1)
        credit = reward * gamma_factor
        existing = past_row["reward"] or 0.0
        new_reward = existing + credit
        conn.execute(
            "UPDATE niacore_experience SET reward = ? WHERE id = ?",
            (new_reward, past_row["id"]),
        )


# ═══════════════════════════════════════════════════════════════
# 3. Training Result
# ═══════════════════════════════════════════════════════════════

@dataclass
class TrainingResult:
    rows_used: int
    epochs: int
    final_loss: float
    elapsed_sec: float
    skipped: bool = False
    skip_reason: str = ""


# ═══════════════════════════════════════════════════════════════
# 4. Batch Training
# ═══════════════════════════════════════════════════════════════

async def run_training(
    *,
    epochs: int = 3,
    batch_size: int = 32,
    lr: float = 1e-3,
) -> TrainingResult | None:
    """Sleep Cycle で呼ばれるバッチ学習。

    1. conversation_continued をマーク
    2. 報酬計算
    3. outcome_known + state_vector IS NOT NULL の行をロード
    4. < batch_size なら skip
    5. 模倣学習 + 報酬重み付きクロスエントロピー
    6. clamp_weights
    7. used_in_training=1 マーク
    """
    if not _TORCH_AVAILABLE:
        return TrainingResult(rows_used=0, epochs=0, final_loss=0.0,
                              elapsed_sec=0.0, skipped=True, skip_reason="torch_not_available")

    t0 = time.time()

    # Phase 1: Mark continued conversations
    continued = mark_conversation_continued()
    logger.info("[NiaCore] marked %d continued conversations", continued)

    # Phase 2: Compute rewards
    rewarded = compute_rewards()
    logger.info("[NiaCore] computed rewards for %d rows", rewarded)

    # Phase 3: Load training data
    try:
        with managed_conn() as conn:
            rows = conn.execute(
                """SELECT state_vector, rule_based_depth, reward
                   FROM niacore_experience
                   WHERE review_checked = 1
                     AND correction_window_closed = 1
                     AND state_vector IS NOT NULL
                     AND reward IS NOT NULL
                     AND used_in_training = 0
                   ORDER BY timestamp ASC"""
            ).fetchall()
    except Exception:
        logger.warning("[NiaCore] training data load failed", exc_info=True)
        return None

    if len(rows) < batch_size:
        return TrainingResult(
            rows_used=len(rows), epochs=0, final_loss=0.0,
            elapsed_sec=time.time() - t0,
            skipped=True, skip_reason=f"insufficient_data ({len(rows)}<{batch_size})",
        )

    # Phase 4: Build tensors
    from backend.core.niacore.model import (
        StateVector,
        STATE_VECTOR_DIM,
        clamp_weights,
        load_or_create_model,
    )

    depth_label_to_idx = {"0": 0, "1": 1, "2": 2, "D0": 0, "D1": 1, "D2": 2, "WAIT": 3}
    state_vectors = []
    targets = []
    weights = []
    row_ids_for_mark: list[str] = []

    for row in rows:
        try:
            sv = StateVector.from_blob(row["state_vector"])
            depth_idx = depth_label_to_idx.get(str(row["rule_based_depth"]).upper(), 0)
            reward = float(row["reward"])

            state_vectors.append(sv.values)
            targets.append(depth_idx)
            # Reward-weighted: shift reward to positive range for loss weighting
            # rejected=-1.0 → weight=0.0, continued=+0.1 → weight=1.1
            weights.append(max(0.0, reward + 1.0))
        except Exception:
            continue

    if len(state_vectors) < batch_size:
        return TrainingResult(
            rows_used=len(state_vectors), epochs=0, final_loss=0.0,
            elapsed_sec=time.time() - t0,
            skipped=True, skip_reason=f"insufficient_valid_data ({len(state_vectors)}<{batch_size})",
        )

    x_tensor = torch.tensor(state_vectors, dtype=torch.float32).unsqueeze(1)  # (N, 1, 34)
    y_tensor = torch.tensor(targets, dtype=torch.long)  # (N,)
    w_tensor = torch.tensor(weights, dtype=torch.float32)  # (N,)
    # Normalize weights to mean=1.0
    w_mean = w_tensor.mean()
    if w_mean > 0:
        w_tensor = w_tensor / w_mean

    # Phase 5: Train
    model = load_or_create_model()
    default_state_dict = {k: v.clone() for k, v in model.state_dict().items()}
    model.train()

    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.CrossEntropyLoss(reduction="none")

    final_loss = 0.0
    for epoch in range(epochs):
        optimizer.zero_grad()
        logits = model(x_tensor)  # (N, 4)
        per_sample_loss = loss_fn(logits, y_tensor)  # (N,)
        weighted_loss = (per_sample_loss * w_tensor).mean()
        weighted_loss.backward()
        optimizer.step()
        final_loss = weighted_loss.item()

    # Phase 6: Clamp weights
    clamped = clamp_weights(model, default_state_dict, max_drift=0.3)
    if clamped > 0:
        logger.info("[NiaCore] clamped %d parameters", clamped)

    # Phase 7: Mark used_in_training
    try:
        with managed_conn() as conn:
            conn.execute(
                """UPDATE niacore_experience
                   SET used_in_training = 1
                   WHERE review_checked = 1
                     AND correction_window_closed = 1
                     AND state_vector IS NOT NULL
                     AND reward IS NOT NULL
                     AND used_in_training = 0"""
            )
    except Exception:
        logger.warning("[NiaCore] mark used_in_training failed", exc_info=True)

    # Checkpoint saving is handled by orchestrator (health.py validates first).
    # Update shadow singleton to use new weights immediately.
    model.eval()
    try:
        from backend.core.niacore.shadow import _set_model
        _set_model(model)
    except Exception:
        pass

    elapsed = time.time() - t0
    logger.info(
        "[NiaCore] training complete: rows=%d epochs=%d loss=%.4f elapsed=%.1fs clamped=%d",
        len(state_vectors), epochs, final_loss, elapsed, clamped,
    )

    return TrainingResult(
        rows_used=len(state_vectors),
        epochs=epochs,
        final_loss=final_loss,
        elapsed_sec=elapsed,
    )
