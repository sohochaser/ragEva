"""Supervise the Huey consumer and publish its liveness."""

import os
import shutil
import signal
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from backend.adapters.run_store import RunStore
from backend.adapters.target_store import TargetStore
from backend.config import Settings
from backend.health import clear_worker_heartbeat, worker_is_ready, write_worker_heartbeat


def recover_work(
    data_dir: Path, submit_run: Callable[[str], object], submit_target: Callable[[str], object]
) -> tuple[int, int]:
    runs = RunStore(data_dir).requeue_unfinished()
    targets = TargetStore(data_dir).requeue_unfinished()
    for run_id in runs:
        submit_run(run_id)
    for job_id in targets:
        submit_target(job_id)
    return len(runs), len(targets)


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
    if worker_is_ready(settings.data_dir, settings.worker_stale_after):
        print("Another Worker is already running", file=sys.stderr)
        return 2

    from backend.worker.queue import collect_target_task, score_run_task

    recover_work(settings.data_dir, score_run_task, collect_target_task)

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
