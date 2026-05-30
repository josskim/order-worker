from __future__ import annotations

import os
from pathlib import Path


class WorkerLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.acquired = False

    def acquire(self) -> bool:
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                file.write(str(os.getpid()))
            self.acquired = True
            return True
        except FileExistsError:
            return False

    def release(self) -> None:
        if self.acquired:
            try:
                self.path.unlink(missing_ok=True)
            finally:
                self.acquired = False

    def __enter__(self) -> "WorkerLock":
        if not self.acquire():
            raise RuntimeError(f"Another order-worker process is already running: {self.path}")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

