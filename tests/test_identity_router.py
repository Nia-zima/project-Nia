from __future__ import annotations

import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.controllers.api.identity_router import router
from backend.core.config import settings
from backend.core.db import managed_conn


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def _seed_pending_proposal(proposal_id: str, proposal_text: str) -> None:
    now = time.time()
    with managed_conn() as conn:
        conn.execute("DELETE FROM identity_proposals")
        conn.execute(
            "DELETE FROM telemetry_kv WHERE k = 'self_model_last_identity_update'"
        )
        conn.execute(
            """
            INSERT INTO identity_proposals (
                id, created_at, date, status, importance, proposal
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (proposal_id, now, "2026-03-24", "pending", 0.4, proposal_text),
        )


def test_identity_approve_requires_system_token() -> None:
    with _make_client() as client:
        res = client.post(
            "/api/identity/proposals/proposal_1/approve",
            json={"review_note": "ok"},
        )
    assert res.status_code == 401


def test_identity_approve_updates_status_and_staleness_timestamp(monkeypatch) -> None:
    proposal_id = "proposal_identity_1"
    proposal_text = "- 新しい学び"
    _seed_pending_proposal(proposal_id, proposal_text)

    async def _fake_normalize(current_text: str, new_patch: str, max_lines: int = 6) -> str:
        assert proposal_text in new_patch
        return f"{current_text}\n{new_patch}".strip()

    monkeypatch.setattr(
        "backend.controllers.api.identity_router.normalize_learnings_safe",
        _fake_normalize,
    )
    monkeypatch.setattr(
        "backend.controllers.api.identity_router.identity_manager.get_identity",
        lambda: "# Identity\n\n## Recent Learnings\n\n古い学び\n",
    )

    updated_payload: dict[str, str] = {}

    def _fake_update_identity(new_content: str, key: str | None = None) -> bool:
        updated_payload["content"] = new_content
        updated_payload["key"] = key or ""
        return True

    monkeypatch.setattr(
        "backend.controllers.api.identity_router.identity_manager.update_identity",
        _fake_update_identity,
    )

    with _make_client() as client:
        res = client.post(
            f"/api/identity/proposals/{proposal_id}/approve",
            json={"review_note": "approved in test"},
            headers={"x-system-token": settings.IDENTITY_SECRET_KEY},
        )

    assert res.status_code == 200
    assert res.json() == {"ok": True, "applied": True}
    assert proposal_text in updated_payload["content"]

    with managed_conn() as conn:
        proposal_row = conn.execute(
            "SELECT status, review_note, resolved_at FROM identity_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
        telemetry_row = conn.execute(
            "SELECT v, updated_at FROM telemetry_kv WHERE k = 'self_model_last_identity_update'"
        ).fetchone()

    assert proposal_row is not None
    assert proposal_row["status"] == "approved"
    assert proposal_row["review_note"] == "approved in test"
    assert proposal_row["resolved_at"] is not None
    assert telemetry_row is not None
    assert float(telemetry_row["v"]) > 0
    assert telemetry_row["updated_at"] > 0
