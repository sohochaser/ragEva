import http.server
import io
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from backend.adapters.dataset_store import DatasetStore
from backend.adapters.target_store import TargetStore
from backend.api.main import create_app
from backend.config import Settings
from backend.domain.datasets import EvaluationCase, ReferenceChunk


@contextmanager
def running(command: list[str], environment: dict[str, str]) -> Iterator[subprocess.Popen[str]]:
    process = subprocess.Popen(
        command,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        text=True,
    )
    try:
        yield process
    finally:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_status(url: str, expected: int, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                status = response.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        except (urllib.error.URLError, TimeoutError):
            status = None
        if status == expected:
            return
        time.sleep(0.1)
    raise AssertionError(f"{url} did not return {expected}")


def test_real_api_and_worker_lifecycle(tmp_path: Path) -> None:
    port = free_port()
    frontend_port = free_port()
    environment = {
        **os.environ,
        "RAGEVA_DATA_DIR": str(tmp_path),
        "RAGEVA_API_PORT": str(port),
        "RAGEVA_API_URL": f"http://127.0.0.1:{port}",
        "RAGEVA_HEARTBEAT_INTERVAL": "1",
    }
    url = f"http://127.0.0.1:{port}/api/v1/health"
    with running([sys.executable, "-m", "backend.api"], environment) as api:
        wait_for_status(f"{url}/live", 200)
        wait_for_status(f"{url}/ready", 503)
        with running([sys.executable, "-m", "backend.worker"], environment) as worker:
            wait_for_status(f"{url}/ready", 200)
            assert worker.poll() is None
            with running(
                ["npm", "--prefix", "frontend", "run", "dev", "--", "--port", str(frontend_port)],
                environment,
            ) as frontend:
                wait_for_status(f"http://127.0.0.1:{frontend_port}/", 200)
                wait_for_status(f"http://127.0.0.1:{frontend_port}/api/v1/health/ready", 200)
                wait_for_status(f"http://127.0.0.1:{frontend_port}/docs", 200)
                assert frontend.poll() is None
            collision = subprocess.run(
                [sys.executable, "-m", "backend.api"],
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            assert collision.returncode != 0
            assert "address already in use" in collision.stderr.lower()
        wait_for_status(f"{url}/ready", 503)
        assert api.poll() is None


def test_worker_consumes_run_from_api_queue(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(data_dir=tmp_path)))
    gold = client.post(
        "/api/v1/datasets/import",
        data={"dataset_name": "integration"},
        files={
            "file": (
                "gold.jsonl",
                io.BytesIO(
                    json.dumps(
                        {
                            "case_id": "q1",
                            "question": "Q",
                            "reference_chunks": [{"text": "known", "document_id": "doc"}],
                        }
                    ).encode()
                ),
            )
        },
    )
    assert gold.status_code == 201, gold.text
    prediction = client.post(
        "/api/v1/predictions/import",
        data={"dataset_id": gold.json()["dataset_id"], "evaluation_type": "retrieval"},
        files={
            "file": (
                "pred.jsonl",
                io.BytesIO(
                    json.dumps(
                        {
                            "case_id": "q1",
                            "contexts": [{"text": "known", "document_id": "doc"}],
                        }
                    ).encode()
                ),
            )
        },
    )
    assert prediction.status_code == 201, prediction.text

    port = free_port()
    environment = {
        **os.environ,
        "RAGEVA_DATA_DIR": str(tmp_path),
        "RAGEVA_API_PORT": str(port),
        "RAGEVA_HEARTBEAT_INTERVAL": "1",
    }
    base = f"http://127.0.0.1:{port}/api/v1"
    with running([sys.executable, "-m", "backend.api"], environment):
        wait_for_status(f"{base}/health/live", 200)
        with running([sys.executable, "-m", "backend.worker"], environment):
            wait_for_status(f"{base}/health/ready", 200)
            payload = json.dumps(
                {
                    "prediction_batch_id": prediction.json()["id"],
                    "model_name": "missing-local-model",
                    "offline": True,
                }
            ).encode()
            request = urllib.request.Request(
                f"{base}/runs",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                assert response.status == 202
                run_id = json.load(response)["id"]
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                with urllib.request.urlopen(f"{base}/runs/{run_id}", timeout=2) as response:
                    run = json.load(response)
                if run["status"] == "failed":
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("Worker did not finish queued run")
            assert run["failed_count"] == 1


def test_worker_collects_http_predictions_from_real_queue(tmp_path: Path) -> None:
    class RagHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert payload == {"case_id": "q1", "question": "Q"}
            body = json.dumps({"contexts": [{"text": "A", "document_id": "d"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    rag = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RagHandler)
    thread = threading.Thread(target=rag.serve_forever)
    thread.start()
    try:
        dataset = DatasetStore(tmp_path).import_cases(
            "gold",
            None,
            "generated",
            [EvaluationCase("q1", "Q", None, (ReferenceChunk("A", "d"),))],
        )
        target = TargetStore(tmp_path).create_target(
            "test",
            f"http://127.0.0.1:{rag.server_port}/rag",
            None,
            2,
            0,
        )
        port = free_port()
        environment = {
            **os.environ,
            "RAGEVA_DATA_DIR": str(tmp_path),
            "RAGEVA_API_PORT": str(port),
            "RAGEVA_HEARTBEAT_INTERVAL": "1",
        }
        base = f"http://127.0.0.1:{port}/api/v1"
        with running([sys.executable, "-m", "backend.api"], environment):
            wait_for_status(f"{base}/health/live", 200)
            with running([sys.executable, "-m", "backend.worker"], environment):
                wait_for_status(f"{base}/health/ready", 200)
                payload = json.dumps(
                    {
                        "target_id": target["id"],
                        "dataset_id": dataset["dataset_id"],
                        "dataset_version": 1,
                        "evaluation_type": "retrieval",
                    }
                ).encode()
                request = urllib.request.Request(
                    f"{base}/target-jobs",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    job_id = json.load(response)["id"]
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    with urllib.request.urlopen(
                        f"{base}/target-jobs/{job_id}", timeout=2
                    ) as response:
                        job = json.load(response)
                    if job["status"] == "completed":
                        break
                    time.sleep(0.1)
                else:
                    raise AssertionError("Worker did not complete HTTP collection")
                with urllib.request.urlopen(
                    f"{base}/predictions/{job['batch_id']}", timeout=2
                ) as response:
                    batch = json.load(response)
                assert batch["predictions"][0]["contexts"][0]["document_id"] == "d"
    finally:
        rag.shutdown()
        thread.join(timeout=5)
        rag.server_close()
