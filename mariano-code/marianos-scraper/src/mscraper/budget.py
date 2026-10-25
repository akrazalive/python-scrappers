"""Total request budget shared by every command of one bounded test (Test 1 = 19, Test 2 = 300, ...).

The per-process caps (`--max-requests`) restart with each process; this budget does not. It is a file in the state
directory (Azure: the mounted Azure Files share), so it holds across commands, retries, resumes, container restarts
and repeated job executions:

    state/_budgets/<name>.json     {"name", "total", "used", "created_at", "updated_at"}
    state/_budgets/<name>.jsonl    one line per provider request: ts, n, command, store, url

A request is counted BEFORE it is sent; once `used == total` every further request is refused (FetchError "budget").
The total is fixed when the budget is created – calling it again with a different total is an error, so a cap can
only be raised by starting a new, separately named budget.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from .fetch import FetchError

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TotalBudget:
    def __init__(self, directory: Path, name: str, total: int, command: str = ""):
        if not _NAME_RE.match(name):
            raise ValueError(f"budget name must be lowercase letters/digits/-/_: {name!r}")
        if total <= 0:
            raise ValueError("budget total must be > 0")
        self.dir, self.name, self.command = Path(directory), name, command
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path, self.log = self.dir / f"{name}.json", self.dir / f"{name}.jsonl"
        if self.path.exists():
            st = json.loads(self.path.read_text(encoding="utf-8"))
            if int(st["total"]) != total:
                raise ValueError(f"budget {name!r} already exists with total {st['total']} (asked {total}); "
                                 f"a cap is never raised – use a new budget name")
            self.state = st
        else:
            self.state = {"name": name, "total": total, "used": 0, "created_at": _now(), "updated_at": _now()}
            self._save()

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
        """Count one provider request before it is sent; refuse when the total is used up."""
        if self.used >= self.total:
            raise FetchError(f"total budget {self.name!r} of {self.total} requests used up", "budget")
        self.state["used"] = self.used + 1
        self.state["updated_at"] = _now()
        self._save()
        with self.log.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": self.state["updated_at"], "n": self.used, "command": self.command,
                                "store": store_id, "url": url}) + "\n")
        return self.used

    def summary(self) -> dict:
        return {**self.state, "remaining": self.remaining, "ledger": str(self.log)}


def parse_spec(spec: str) -> tuple[str, int]:
    """'test1:19' -> ('test1', 19)"""
    name, _, total = (spec or "").partition(":")
    if not name or not total.isdigit():
        raise ValueError(f"budget must look like NAME:TOTAL (e.g. test1:19), got {spec!r}")
    return name.strip(), int(total)
