"""Supervise isolated services used by the Playwright browser test."""

import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
STOP = False


def stop(_signal: int, _frame: object) -> None:
    global STOP
    STOP = True


def ready(url: str) -> bool:
    try:
        with urlopen(url, timeout=1) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def main() -> int:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    processes: list[subprocess.Popen[bytes]] = []
    with tempfile.TemporaryDirectory(prefix="rageva-browser-e2e-") as data_dir:
        env = {
            **os.environ,
            "RAGEVA_DATA_DIR": data_dir,
            "RAGEVA_API_PORT": "18000",
            "RAGEVA_API_URL": "http://127.0.0.1:18000",
            "RAGEVA_DOWNLOAD_PORT": "18001",
            "RAGEVA_DOWNLOAD_PUBLIC_URL": "http://127.0.0.1:18001",
            "RAGEVA_DOWNLOAD_TOKEN": "browser-e2e-token",
            "RAGEVA_HEARTBEAT_INTERVAL": "1",
        }

        def start(command: list[str]) -> None:
            processes.append(subprocess.Popen(command, cwd=ROOT, env=env, start_new_session=True))

        try:
            start([PYTHON, "scripts/e2e_fixture.py"])
            start([PYTHON, "-m", "backend.worker"])
            start([PYTHON, "-m", "backend.api"])
            start([PYTHON, "-m", "backend.download"])
            start(
                [
                    "npm",
                    "--prefix",
                    "frontend",
                    "run",
                    "dev",
                    "--",
                    "--port",
                    "15173",
                    "--strictPort",
                ]
            )
            deadline = time.monotonic() + 45
            urls = (
                "http://127.0.0.1:18002/health",
                "http://127.0.0.1:18000/api/v1/health/ready",
                "http://127.0.0.1:15173/",
            )
            while not STOP and time.monotonic() < deadline:
                if all(ready(url) for url in urls):
                    print("Browser E2E services ready", flush=True)
                    break
                if any(process.poll() is not None for process in processes):
                    raise RuntimeError("A browser E2E service exited during startup")
                time.sleep(0.2)
            else:
                if not STOP:
                    raise RuntimeError("Browser E2E services did not become ready")
            while not STOP:
                if any(process.poll() is not None for process in processes):
                    raise RuntimeError("A browser E2E service exited unexpectedly")
                time.sleep(0.2)
        finally:
            for process in processes:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
            for process in processes:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
