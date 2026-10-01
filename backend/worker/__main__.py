"""Supervise the Huey consumer and publish its liveness."""

import os
import shutil
import signal
import subprocess
import sys
import threading

from backend.config import Settings
from backend.health import clear_worker_heartbeat, write_worker_heartbeat


def main() -> int:
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    consumer_command = shutil.which("huey_consumer")
    if consumer_command is None:
        print("huey_consumer is missing; run make setup", file=sys.stderr)
        return 2

    stop = threading.Event()

    def request_stop(_signal: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    consumer = subprocess.Popen(
        [consumer_command, "backend.worker.queue.huey", "-w", "1", "-k", "thread"]
    )
    pid = os.getpid()
    try:
        while not stop.is_set() and consumer.poll() is None:
            write_worker_heartbeat(settings.data_dir, pid)
            stop.wait(settings.heartbeat_interval)
        return 0 if stop.is_set() else (consumer.returncode or 1)
    finally:
        if consumer.poll() is None:
            consumer.terminate()
            try:
                consumer.wait(timeout=5)
            except subprocess.TimeoutExpired:
                consumer.kill()
                consumer.wait()
        clear_worker_heartbeat(settings.data_dir, pid)


if __name__ == "__main__":
    raise SystemExit(main())
