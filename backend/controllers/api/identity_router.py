"""Identity Proposal review endpoints (admin-authenticated)."""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.core.auth import verify_system_token
from backend.core.db import managed_conn
from backend.core.logger import logger
from backend.services.identity_manager import identity_manager
from backend.services.memory.self_model import _mark_identity_updated
from backend.scripts.sleep_cycle import (
    extract_section_content,
    replace_section_content,
    normalize_learnings_safe,
)

router = APIRouter()


class ProposalDecisionRequest(BaseModel):
    review_note: Optional[str] = None


@router.get(
    "/identity/proposals",
    dependencies=[Depends(verify_system_token)],
)
async def list_proposals(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List identity proposals, optionally filtered by status."""
    with managed_conn() as conn:
        if status:
            statuses = [s.strip() for s in status.split(",")]
            placeholders = ",".join("?" * len(statuses))
            rows = conn.execute(
                f"""SELECT * FROM identity_proposals
                    WHERE status IN ({placeholders})
                    ORDER BY created_at DESC LIMIT ?""",
                (*statuses, limit),
            ).fetchall()
            total_row = conn.execute(
                f"SELECT COUNT(*) as c FROM identity_proposals WHERE status IN ({placeholders})",
                statuses,
            ).fetchone()
        else:
            rows = conn.execute(
                "SELECT * FROM identity_proposals ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            total_row = conn.execute(
                "SELECT COUNT(*) as c FROM identity_proposals",
            ).fetchone()
        return {"items": [dict(r) for r in rows], "total": total_row["c"]}


@router.post(
    "/identity/proposals/{proposal_id}/approve",
    dependencies=[Depends(verify_system_token)],
)
async def approve_proposal(proposal_id: str, req: ProposalDecisionRequest):
    """Approve a proposal and apply it to identity.md."""
    with managed_conn() as conn:
        row = conn.execute(
            "SELECT * FROM identity_proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "proposal_not_found")
        proposal = dict(row)
        if proposal["status"] != "pending":
            raise HTTPException(409, f"proposal_already_{proposal['status']}")

    # Apply to identity.md
    current_identity = identity_manager.get_identity()
    header = "## Recent Learnings"
    current_learnings = extract_section_content(current_identity, header)
    normalized_block = await normalize_learnings_safe(
        current_learnings, proposal["proposal"]
    )
    new_identity = replace_section_content(
        current_identity, header, normalized_block
    )
    success = identity_manager.update_identity(
        new_identity, key=identity_manager._secret_key
    )
    if not success:
        raise HTTPException(500, "identity_update_failed")

    # Update DB record
    with managed_conn() as conn:
        now = time.time()
        conn.execute(
            """UPDATE identity_proposals
               SET status = 'approved', review_note = ?, resolved_at = ?
               WHERE id = ?""",
            (req.review_note, now, proposal_id),
        )
        # Keep telemetry_kv and identity_proposals in the same DB transaction.
        _mark_identity_updated(conn)
        conn.commit()
    logger.info("[IDENTITY] Proposal %s approved and applied", proposal_id)
    return {"ok": True, "applied": True}


@router.post(
    "/identity/proposals/{proposal_id}/reject",
    dependencies=[Depends(verify_system_token)],
)
async def reject_proposal(proposal_id: str, req: ProposalDecisionRequest):
    """Reject a proposal without applying changes."""
    with managed_conn() as conn:
        row = conn.execute(
            "SELECT status FROM identity_proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "proposal_not_found")
        if row["status"] != "pending":
            raise HTTPException(409, f"proposal_already_{row['status']}")

        now = time.time()
        conn.execute(
            """UPDATE identity_proposals
               SET status = 'rejected', review_note = ?, resolved_at = ?
               WHERE id = ?""",
            (req.review_note, now, proposal_id),
        )
        conn.commit()
    logger.info("[IDENTITY] Proposal %s rejected", proposal_id)
    return {"ok": True}
