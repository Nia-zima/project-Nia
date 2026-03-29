from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.controllers.api.system_router import router
from backend.core.config import settings
from backend.core.db import get_conn, init_schema


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_status_endpoint_is_public() -> None:
    with _make_client() as client:
        res = client.get("/api/status")
        assert res.status_code == 200


def test_system_endpoints_require_system_token() -> None:
    with _make_client() as client:
        assert client.post("/api/system/vision", json={"enabled": True}).status_code == 401
        assert client.post("/api/system/sleep").status_code == 401
        assert client.post("/api/system/training_dataset_snapshot", json={}).status_code == 401


def test_system_vision_accepts_valid_token() -> None:
    with _make_client() as client:
        res = client.post(
            "/api/system/vision",
            json={"enabled": True},
            headers={"x-system-token": settings.IDENTITY_SECRET_KEY},
        )
        assert res.status_code == 200
        assert res.json().get("vision_enabled") is True


def test_system_training_dataset_snapshot_returns_service_result(monkeypatch) -> None:
    expected = {
        "ok": True,
        "ran": True,
        "thread_id": "default_thread",
        "row_count": 3,
        "training_ready_samples": 3,
    }

    def _fake_runner(*, thread_id=None, fmt=None, force=False, snapshot_dir=None, current_time=None):
        assert thread_id == "default_thread"
        assert fmt == "csv"
        assert force is True
        return expected

    monkeypatch.setattr(
        "backend.controllers.api.system_router.run_daily_training_dataset_snapshot_if_due",
        _fake_runner,
    )

    with _make_client() as client:
        res = client.post(
            "/api/system/training_dataset_snapshot",
            json={"thread_id": "default_thread", "format": "csv", "force": True},
            headers={"x-system-token": settings.IDENTITY_SECRET_KEY},
        )

    assert res.status_code == 200
    assert res.json() == expected


def test_system_diagnostics_includes_training_snapshot_telemetry() -> None:
    init_schema()
    scope = (getattr(settings, "TRAINING_DATASET_SNAPSHOT_THREAD_ID", None) or "all_threads").strip() or "all_threads"
    conn = get_conn()
    try:
        conn.execute("DELETE FROM telemetry_kv")
        conn.execute(
            "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, strftime('%s','now'))",
            (f"training_dataset_snapshot:last_status:{scope}", "ok"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, strftime('%s','now'))",
            (f"training_dataset_snapshot:last_row_count:{scope}", "7"),
        )
    finally:
        conn.close()

    with _make_client() as client:
        res = client.get(
            "/api/system/diagnostics",
            headers={"x-system-token": settings.IDENTITY_SECRET_KEY},
        )

    assert res.status_code == 200
    payload = res.json()["training_dataset_snapshot"]
    assert payload["last_status"] == "ok"
    assert payload["last_row_count"] == "7"
