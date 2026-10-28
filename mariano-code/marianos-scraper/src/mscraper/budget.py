"""Total request budget shared by every command of one bounded test (Test 1 = 19, Test 2 = 300, ...).

The per-process caps (`--max-requests`) restart with each process; this budget does not. It is a pair of files in the
state directory (Azure: the mounted Azure Files share), so it holds across commands, retries, resumes, container
restarts and repeated job executions:

    state/_budgets/<name>.json     {"name", "total", "used", "created_at", "updated_at"}
    state/_budgets/<name>.jsonl    one line per provider request: ts, n, command, store, url

Exclusive ownership (1.1.5): a budget may only be opened and used while this process holds the live lock
(lock.live_lock – a Blob lease in Azure), so two executions can never draw on it at the same time. Every take()
re-checks the lock, re-reads the state from disk (no cached counter) and only then reserves the next request.

Order of writes per request: (1) the ledger line is appended and flushed, (2) the state file is replaced atomically,
(3) the request is sent. A crash between (1) and (2) leaves one ledger line more than `used`; on the next open that
request is counted as used (fail safe). Anything else is inconsistent and fails closed (BudgetError): a missing or
invalid state file next to an existing ledger, fewer ledger lines than `used`, more than one extra line, a total that
differs from the requested one, or used > total. A cap can only be raised by a new, separately named budget.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from .fetch import FetchError
from . import lock

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


class BudgetError(RuntimeError):
    """The persistent budget is missing, inconsistent or not exclusively owned: no request may be sent."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TotalBudget:
    def __init__(self, directory: Path, name: str, total: int, command: str = "", require_lock: bool = True):
        if not _NAME_RE.match(name):
            raise ValueError(f"budget name must be lowercase letters/digits/-/_: {name!r}")
        if total <= 0:
            raise ValueError("budget total must be > 0")
        self.require_lock = require_lock
        self._owned()
        self.dir, self.name, self.command, self.want_total = Path(directory), name, command, total
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path, self.log = self.dir / f"{name}.json", self.dir / f"{name}.jsonl"
        if not self.path.exists():
            if self.log.exists() and self._lines():
                raise BudgetError(f"budget {name!r}: ledger exists but state file is missing – refusing to reset")
            self.state = {"name": name, "total": total, "used": 0, "created_at": _now(), "updated_at": _now()}
            self._save()
        self.state = self._load()

    def _owned(self) -> None:
        if self.require_lock and not lock.live_held():
            raise BudgetError("a persistent request budget may only be used while holding the live lock")
        lock.check_active()

    def _lines(self) -> int:
        if not self.log.exists():
            return 0
        return sum(1 for ln in self.log.read_text(encoding="utf-8").splitlines() if ln.strip())

    def _load(self) -> dict:
        """Read and validate the state from disk; repair only the single crash window described above."""
        try:
            st = json.loads(self.path.read_text(encoding="utf-8"))
            total, used = int(st["total"]), int(st["used"])
        except Exception as exc:
            raise BudgetError(f"budget {self.name!r}: state file unreadable/invalid ({exc})") from exc
        if st.get("name") != self.name:
            raise BudgetError(f"budget {self.name!r}: state file names {st.get('name')!r}")
        if total != self.want_total:
            raise ValueError(f"budget {self.name!r} already exists with total {total} (asked {self.want_total}); "
                             f"a cap is never raised – use a new budget name")
        if not 0 <= used <= total:
            raise BudgetError(f"budget {self.name!r}: used {used} outside 0..{total}")
        lines = self._lines()
        if lines == used + 1 and lines <= total:      # ledger written, state not yet: count it as used
            st["used"], st["updated_at"], st["repaired_at"] = lines, _now(), _now()
            self.state = st
            self._save()
        elif lines != used:
            raise BudgetError(f"budget {self.name!r}: ledger has {lines} lines but state says used={used}")
        return st

    @property
    def total(self) -> int:
        return int(self.state["total"])

    @property
    def used(self) -> int:
        return int(self.state["used"])

    @property
    def remaining(self) -> int:
        return self.total - self.used

    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def take(self, url: str, store_id: str = "") -> int:
        """Reserve one provider request before it is sent; refuse when the total is used up or ownership is gone."""
        self._owned()
        self.state = self._load()                      # never trust an in-memory counter
        if self.used >= self.total:
            raise FetchError(f"total budget {self.name!r} of {self.total} requests used up", "budget")
        n = self.used + 1
        with self.log.open("a", encoding="utf-8") as f:   # (1) ledger first
            f.write(json.dumps({"ts": _now(), "n": n, "command": self.command, "store": store_id, "url": url}) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self.state = {**self.state, "used": n, "updated_at": _now()}
        self._save()                                       # (2) then the counter
        return n

    def summary(self) -> dict:
        return {**self.state, "remaining": self.remaining, "ledger": str(self.log)}


def parse_spec(spec: str) -> tuple[str, int]:
    """'test1:19' -> ('test1', 19)"""
    name, _, total = (spec or "").partition(":")
    if not name or not total.isdigit():
        raise ValueError(f"budget must look like NAME:TOTAL (e.g. test1:19), got {spec!r}")
    return name.strip(), int(total)
