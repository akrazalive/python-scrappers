"""Persistent total request budget: one approved test = one named total that no process can exceed.

State lives in the run storage (Azure: the walmart-scraper blob container; locally: the output directory):

    _budgets/<name>.json          {"name", "total", "used", "created_at", "updated_at"}
    _budgets/<name>.jsonl         ledger lines 1-200 (one per provider request: ts, n, command, store, url)
    _budgets/<name>.jsonl.<k>     ledger lines 200*(k-1)+1 .. 200*k for k >= 2 (bounded rewrite cost per request)

Safety rules (1.1.8, client review of 27 Oct):
* Exclusive ownership – a budget is only opened and used while this process holds the live lock (lock.live_lock,
  a Blob lease in Azure), and every reservation re-checks it.
* Atomic reservation – each take() re-reads the state with its ETag and writes the new count with a conditional
  write (If-Match / create-if-absent). If anything else changed the state in between, the write fails
  (ConflictError -> BudgetError): two holders can never both reserve the same request.
* Order per request: ledger line first, then the conditional state write, then the request is sent. A crash
  between the two writes leaves exactly one extra ledger line; the next open counts that request as used.
* Fail closed (BudgetError, nothing sent): state missing while ledger lines exist (never reset to zero), state
  unreadable/invalid/misnamed, used outside 0..total, ledger lines fewer than used or more than used+1.
* A total cannot be raised under the same name.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
JS_RATE_USD_PER_1000 = 1.35   # client's dashboard rate for JS-rendered results (the higher of the two rates)
CHUNK = 200


class BudgetError(RuntimeError):
    """The persistent budget is missing, inconsistent, contended or not exclusively owned: no request may be sent."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_spec(spec: str) -> tuple[str, int]:
    name, _, total = spec.partition(":")
    if not total.isdigit():
        raise ValueError(f"budget must be NAME:TOTAL, got {spec!r}")
    return name, int(total)


class TotalBudget:
    def __init__(self, storage, name: str, total: int, command: str = "", require_lock: bool = True):
        if not _NAME_RE.match(name):
            raise ValueError(f"budget name must be lowercase letters/digits/-/_: {name!r}")
        if total <= 0:
            raise ValueError("budget total must be > 0")
        self.st, self.name, self.command, self.want_total = storage, name, command, total
        self.require_lock = require_lock
        self.key = f"_budgets/{name}.json"
        self._owned()
        raw, etag = storage.get_bytes_etag(self.key)
        if raw is None:
            if self._ledger_lines():
                raise BudgetError(f"budget {name!r}: ledger exists but state is missing – refusing to reset to 0")
            self._write({"name": name, "total": total, "used": 0, "created_at": _now(), "updated_at": _now()}, None)
        self.state, self._etag = self._load()

    # ------------------------------------------------------------------ helpers
    def _owned(self) -> None:
        from . import lock

        if self.require_lock and not lock.live_held():
            raise BudgetError("a persistent request budget may only be used while holding the live lock")
        lock.check_active()

    def _chunk_key(self, k: int) -> str:
        return f"_budgets/{self.name}.jsonl" if k == 1 else f"_budgets/{self.name}.jsonl.{k}"

    def _chunk(self, k: int) -> list[str]:
        raw = self.st.get_bytes(self._chunk_key(k))
        return [ln for ln in raw.decode("utf-8").splitlines() if ln.strip()] if raw else []

    def _ledger_lines(self) -> int:
        n, k = 0, 1
        while True:
            lines = self._chunk(k)
            n += len(lines)
            if len(lines) < CHUNK:
                return n
            k += 1

    def _write(self, state: dict, etag) -> None:
        from .storage import ConflictError

        try:
            self.st.put_bytes_if(self.key, json.dumps(state, indent=2).encode("utf-8"), etag)
        except ConflictError as exc:
            raise BudgetError(f"budget {self.name!r}: concurrent change detected ({exc}) – no request sent") from exc

    def _load(self) -> tuple[dict, str]:
        """Read + validate the state from storage; repair only the single crash window described above."""
        raw, etag = self.st.get_bytes_etag(self.key)
        if raw is None:
            raise BudgetError(f"budget {self.name!r}: state disappeared")
        try:
            st = json.loads(raw)
            total, used = int(st["total"]), int(st["used"])
        except Exception as exc:
            raise BudgetError(f"budget {self.name!r}: state unreadable/invalid ({exc})") from exc
        if st.get("name") != self.name:
            raise BudgetError(f"budget {self.name!r}: state names {st.get('name')!r}")
        if total != self.want_total:
            raise ValueError(f"budget {self.name!r} already exists with total {total} (asked {self.want_total}); "
                             f"a cap is never raised – use a new budget name")
        if not 0 <= used <= total:
            raise BudgetError(f"budget {self.name!r}: used {used} outside 0..{total}")
        lines = self._ledger_lines()
        if lines == used + 1 and lines <= total:          # ledger written, state not: count it as used
            st = {**st, "used": lines, "updated_at": _now(), "repaired_at": _now()}
            self._write(st, etag)
            return self._load()
        if lines != used:
            raise BudgetError(f"budget {self.name!r}: ledger has {lines} lines but state says used={used}")
        return st, etag

    @property
    def total(self) -> int:
        return int(self.state["total"])

    @property
    def used(self) -> int:
        return int(self.state["used"])

    @property
    def remaining(self) -> int:
        return self.total - self.used

    def flush(self) -> None:          # kept for callers of 1.1.7; every line is written before its request now
        return None

    def take(self, url: str, store_id: str = "") -> int:
        """Reserve one provider request (ledger, then conditional state write) before it is sent."""
        from .fetch import FetchError

        self._owned()
        self.state, self._etag = self._load()             # never trust an in-memory counter
        if self.used >= self.total:
            raise FetchError(f"total budget {self.name!r} of {self.total} requests used up", "budget")
        n = self.used + 1
        k = (n - 1) // CHUNK + 1
        lines = self._chunk(k) + [json.dumps({"ts": _now(), "n": n, "command": self.command, "store": store_id,
                                              "url": url})]
        self.st.put_bytes(self._chunk_key(k), ("\n".join(lines) + "\n").encode("utf-8"))   # (1) ledger
        new = {**self.state, "used": n, "updated_at": _now()}
        self._write(new, self._etag)                                                    # (2) conditional count
        self.state, self._etag = self._load()
        return n

    def summary(self) -> dict:
        return {**self.state, "remaining": self.remaining, "ledger": self._chunk_key(1),
                "max_cost_usd_at_js_rate": round(self.used * JS_RATE_USD_PER_1000 / 1000, 4)}
