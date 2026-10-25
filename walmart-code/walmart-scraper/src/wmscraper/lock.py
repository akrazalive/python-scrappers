"""Prevents overlapping runs for the same location.

* Local: an exclusive lock file (atomic create) with stale-lock recovery.
* Azure: a Blob lease, renewed while the run is alive; a crashed run's lease expires
  automatically, so the next scheduled run can continue from its checkpoint.
"""
from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path


class LockError(RuntimeError):
    pass


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class FileLock:
    def __init__(self, path: Path, stale_seconds: int = 6 * 3600):
        self.path = Path(path)
        self.stale = stale_seconds

    def _holder_dead(self) -> bool:
        """True when the lock was left by a process on this host that no longer exists."""
        try:
            info = self.path.read_text(errors="ignore").split()
            host, pid = info[0], int(info[1].split("=")[1])
        except Exception:
            return False
        if host != socket.gethostname():
            return False
        return not _pid_alive(pid)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and (time.time() - self.path.stat().st_mtime > self.stale or self._holder_dead()):
            self.path.unlink()  # previous run crashed (process gone) – safe to take over and resume
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise LockError(f"another run holds {self.path} ({self.path.read_text(errors='ignore')})")
        os.write(fd, f"{socket.gethostname()} pid={os.getpid()} {time.ctime()}".encode())
        os.close(fd)
        return self

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


class BlobLeaseLock:
    def __init__(self, container_client, key: str, lease_seconds: int = 60):
        self.blob = container_client.get_blob_client(key)
        self.seconds = lease_seconds
        self._stop = threading.Event()

    def __enter__(self):
        from azure.core.exceptions import HttpResponseError

        if not self.blob.exists():
            self.blob.upload_blob(b"lock", overwrite=True)
        try:
            self.lease = self.blob.acquire_lease(lease_duration=self.seconds)
        except HttpResponseError as exc:
            raise LockError(f"another run holds the lease on {self.blob.blob_name}") from exc
        threading.Thread(target=self._renew, daemon=True).start()
        return self

    def _renew(self):
        while not self._stop.wait(self.seconds / 3):
            try:
                self.lease.renew()
            except Exception:
                return

    def __exit__(self, *exc):
        self._stop.set()
        try:
            self.lease.release()
        except Exception:
            pass


def run_lock(storage, location_key: str):
    from .storage import BlobStorage

    if isinstance(storage, BlobStorage):
        return BlobLeaseLock(storage.cc, f"{location_key}/.run.lock")
    return FileLock(storage.local_path(f"{location_key}/.run.lock"))
