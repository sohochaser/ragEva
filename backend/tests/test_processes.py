import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def running(command: list[str], environment: dict[str, str]) -> Iterator[subprocess.Popen[str]]:
    process = subprocess.Popen(
        command,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


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
