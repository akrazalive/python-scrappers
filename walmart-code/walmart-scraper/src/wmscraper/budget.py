"""Persistent total request budget (1.1.7): one approved test = one named total that no process can exceed.

`--max-requests` is a per-process cap and restarts with each process. This budget does not: its state lives in the
run storage (Azure: the walmart-scraper blob container; locally: the output directory), so it holds across retries,
resumed runs, container restarts and repeated job executions:

    _budgets/<name>.json     {"name", "total", "used", "created_at", "updated_at"}
    _budgets/<name>.jsonl    one line per provider request: ts, n, command, store, url

A request is counted and saved BEFORE it is sent; once `used == total` every further request is refused
(FetchError "budget"). The total is fixed when the budget is created – opening it again with a different total is
an error, so a cap can only be raised by a new, separately named budget (i.e. a new approval).
"""
from __future__ import annotations

import atexit
import json
import re
from datetime import datetime, timezone

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
JS_RATE_USD_PER_1000 = 1.35   # client's dashboard rate for JS-rendered results (the higher of the two rates)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_spec(spec: str) -> tuple[str, int]:
    name, _, total = spec.partition(":")
    if not total.isdigit():
        raise ValueError(f"budget must be NAME:TOTAL, got {spec!r}")
    return name, int(total)


class TotalBudget:
    def __init__(self, storage, name: str, total: int, command: str = ""):
        from .fetch import FetchError  # noqa: F401  (import check: budget errors are FetchErrors)

        if not _NAME_RE.match(name):
            raise ValueError(f"budget name must be lowercase letters/digits/-/_: {name!r}")
        if total <= 0:
            raise ValueError("budget total must be > 0")
        self.st, self.name, self.command = storage, name, command
        self.key, self.log_key = f"_budgets/{name}.json", f"_budgets/{name}.jsonl"
        state = storage.get_json(self.key)
        if state:
            if int(state["total"]) != total:
                raise ValueError(f"budget {name!r} already exists with total {state['total']} (asked {total}); "
                                 f"a cap is never raised – use a new budget name")
            self.state = state
        else:
            self.state = {"name": name, "total": total, "used": 0, "created_at": _now(), "updated_at": _now()}
            self._save()
        old = storage.get_bytes(self.log_key)
        self._lines = old.decode("utf-8").splitlines() if old else []
        self._unflushed = 0
        atexit.register(self.flush)

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
        self.st.put_json(self.key, self.state)

    def flush(self):
        if self._unflushed:
            self.st.put_bytes(self.log_key, ("\n".join(self._lines) + "\n").encode("utf-8"))
            self._unflushed = 0

    def take(self, url: str, store_id: str = "") -> int:
        """Count one provider request and persist the count before it is sent; refuse when the total is used up."""
        from .fetch import FetchError

        if self.used >= self.total:
            raise FetchError(f"total budget {self.name!r} of {self.total} requests used up", "budget")
        self.state["used"] = self.used + 1
        self.state["updated_at"] = _now()
        self._save()
        self._lines.append(json.dumps({"ts": self.state["updated_at"], "n": self.used, "command": self.command,
                                       "store": store_id, "url": url}))
        self._unflushed += 1
        if self.total <= 1000 or self._unflushed >= 50:   # small tests: every line saved at once
            self.flush()
        return self.used

    def summary(self) -> dict:
        return {**self.state, "remaining": self.remaining, "ledger": self.log_key,
                "max_cost_usd_at_js_rate": round(self.used * JS_RATE_USD_PER_1000 / 1000, 4)}
