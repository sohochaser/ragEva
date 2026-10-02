import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.config import Settings
from backend.health import clear_worker_heartbeat, write_worker_heartbeat


def test_liveness_and_missing_worker(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(data_dir=tmp_path)))
    assert client.get("/api/v1/health/live").json() == {"status": "ok", "component": "api"}
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "component": "worker"}


def test_readiness_tracks_worker_heartbeat(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(data_dir=tmp_path, worker_stale_after=8)))
    write_worker_heartbeat(tmp_path, os.getpid())
    assert client.get("/api/v1/health/ready").json() == {"status": "ok", "component": "worker"}
    assert client.get("/api/v1/health/ready").status_code == 200

    write_worker_heartbeat(tmp_path, os.getpid(), now=time.time() - 10)
    assert client.get("/api/v1/health/ready").status_code == 503
    clear_worker_heartbeat(tmp_path, os.getpid())
    assert client.get("/api/v1/health/ready").status_code == 503
