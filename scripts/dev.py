"""Start the local API, worker, and frontend as one supervised command."""

import shutil
import subprocess
import sys
import time

from backend.config import Settings


def main() -> int:
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    if shutil.which("npm") is None:
        print("npm is missing; install Node.js and run make setup", file=sys.stderr)
        return 2
    commands = {
        "worker": [sys.executable, "-m", "backend.worker"],
        "api": [sys.executable, "-m", "backend.api"],
        "frontend": ["npm", "--prefix", "frontend", "run", "dev"],
    }
    processes: dict[str, subprocess.Popen[bytes]] = {}
    try:
        for name, command in commands.items():
            processes[name] = subprocess.Popen(command)
        print(f"API: http://{settings.api_host}:{settings.api_port}/docs", flush=True)
        print("Frontend: http://127.0.0.1:5173 (or next free port)", flush=True)
        while True:
            for name, process in processes.items():
                if process.poll() is not None:
                    print(f"{name} exited with code {process.returncode}", file=sys.stderr)
                    return process.returncode or 1
            time.sleep(0.2)
    except KeyboardInterrupt:
        return 0
    finally:
        for process in processes.values():
            if process.poll() is None:
                process.terminate()
        for process in processes.values():
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
