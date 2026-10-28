"""Exclusive locks.

* `run_lock(storage, location)` – one run per location (unchanged purpose).
* `live_lock(storage)` – ONE process at a time may send provider requests at all, whatever the command or location
  (verify-store, run, run-all). It is held around every use of a persistent request budget. Re-entrant.

Backends:
* Local: an exclusive lock file (atomic create) holding a random owner token; stale-lock recovery only when the
  holder process on this host is gone.
* Azure: a Blob lease (60 s), renewed every 20 s by a background thread. A crashed holder's lease expires on its own,
  so a restarted execution can take over and resume.

Lease loss fails closed: when a renewal fails (or the local lock file is no longer ours), the lock is marked LOST and
`check_active()` raises `LockLost`. It is called before every provider request (fetch/base.py), every checkpoint write
(checkpoint.py / runner sync) and every publication step (storage.py), so nothing more is sent, written or published.
"""
from __future__ import annotations

import os
import secrets
import socket
import threading
import time
from pathlib import Path


class LockError(RuntimeError):
    pass


class LockLost(LockError):
    """The exclusive lock was lost while work was in progress: stop requests, checkpoint writes and publication."""


_ACTIVE: list = []          # locks held by this process (checked before requests / checkpoint writes / publication)
_LIVE_DEPTH = 0             # re-entrancy of live_lock() inside one process


def check_active() -> None:
    for lk in list(_ACTIVE):
        lk.check()


def live_held() -> bool:
    return _LIVE_DEPTH > 0


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
        self.token = secrets.token_hex(8)
        self.lost = False

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
        os.write(fd, f"{socket.gethostname()} pid={os.getpid()} token={self.token} {time.ctime()}".encode())
        os.close(fd)
        _ACTIVE.append(self)
        return self

    def check(self) -> None:
        try:
            ours = f"token={self.token}" in self.path.read_text(errors="ignore")
        except OSError:
            ours = False
        if self.lost or not ours:
            self.lost = True
            raise LockLost(f"lock {self.path} is no longer held by this process")

    def __exit__(self, *exc):
        if self in _ACTIVE:
            _ACTIVE.remove(self)
        try:
            if f"token={self.token}" in self.path.read_text(errors="ignore"):
                self.path.unlink()
        except OSError:
            pass


class BlobLeaseLock:
    def __init__(self, container_client, key: str, lease_seconds: int = 60):
        self.blob = container_client.get_blob_client(key)
        self.seconds = lease_seconds
        self._stop = threading.Event()
        self.lost = False
        self.lost_reason = ""

    def __enter__(self):
        from azure.core.exceptions import HttpResponseError

        if not self.blob.exists():
            self.blob.upload_blob(b"lock", overwrite=True)
        try:
            self.lease = self.blob.acquire_lease(lease_duration=self.seconds)
        except HttpResponseError as exc:
            raise LockError(f"another run holds the lease on {self.blob.blob_name}") from exc
        _ACTIVE.append(self)
        threading.Thread(target=self._renew, daemon=True).start()
        return self

    def _renew(self):
        while not self._stop.wait(self.seconds / 3):
            try:
                self.lease.renew()
            except Exception as exc:  # lease lost: fail closed – check() now raises everywhere
                self.lost, self.lost_reason = True, f"{type(exc).__name__}: {exc}"[:200]
                return

    def check(self) -> None:
        if self.lost:
            raise LockLost(f"lease on {self.blob.blob_name} lost ({self.lost_reason})")

    def __exit__(self, *exc):
        self._stop.set()
        if self in _ACTIVE:
            _ACTIVE.remove(self)
        try:
            self.lease.release()
        except Exception:
            pass


def run_lock(storage, location_key: str):
    from .storage import BlobStorage

    if isinstance(storage, BlobStorage):
        return BlobLeaseLock(storage.cc, f"{location_key}/.run.lock")
    return FileLock(storage.local_path(f"{location_key}/.run.lock"))


class live_lock:
    """Process-wide exclusive right to send provider requests (all tests, all locations). Re-entrant."""

    def __init__(self, storage):
        self.storage, self.inner = storage, None

    def __enter__(self):
        global _LIVE_DEPTH
        if _LIVE_DEPTH == 0:
            self.inner = run_lock(self.storage, "_live").__enter__()
        _LIVE_DEPTH += 1
        return self

    def __exit__(self, *exc):
        global _LIVE_DEPTH
        _LIVE_DEPTH -= 1
        if self.inner is not None:
            self.inner.__exit__(*exc)
