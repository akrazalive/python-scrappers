"""Durable run state in SQLite: genuine continuation after an interruption.

Stored per run:
* listings – every (category, shelf) with the next search page to fetch, status and stop reason
* items    – every accepted record (JSON) keyed by identity (UPC, or product:<id> without UPC) → dedup
* ledger / listing_items / observations / exclusions – provenance and coverage evidence (see runner)
* seen     – every UPC encountered with the reason it was kept or skipped
* meta     – store verification, canaries, discovery results, counters
* events   – structured audit trail (retries, mismatches, failures)

A page's records are written in the same transaction that advances that listing's page
pointer, so a crash can never lose a page or store it twice.

Storage modes (MSCRAPER_CHECKPOINT_MODE):
* direct (default, local disk): SQLite works on <run>/checkpoint.sqlite itself.
* snapshot (Azure - the state directory is an SMB share, where SQLite's byte-range locks fail and must not be
  disabled): SQLite works on a LOCAL file, and the durable copy on the share is a series of consistent snapshots:

    <run>/checkpoint.snap-<seq>.sqlite   a complete database made with SQLite's online backup API
    <run>/checkpoint.manifest.json       {"seq", "file", "sha256", "bytes", "written_at", "integrity": "ok"}

  Flush (after a committed transaction, at most every MSCRAPER_SNAPSHOT_SECONDS, default 5; always at the end of a
  run and before publication): backup -> integrity_check -> write the snapshot file under a temp name and rename it ->
  write the manifest under a temp name and rename it (the COMMIT POINT) -> delete the previous snapshot. A crash at
  any step leaves the previous manifest pointing at the previous, still existing snapshot.
  Restore (every open): the manifest must parse, its snapshot must exist, have the recorded SHA-256 and pass
  PRAGMA integrity_check; then it is copied to the local working file. Any mismatch raises CheckpointError (fail
  closed - the run is not silently restarted). No manifest = nothing was committed durably = a new checkpoint.
  Work committed after the last snapshot is redone after a crash (at most ~5 s of pages); because a page and its
  pointer are one transaction, a redone page is never stored twice.
  Every checkpoint write first checks the exclusive locks (lock.check_active): after a lease loss nothing is written.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from . import lock


class CheckpointError(RuntimeError):
    """The durable checkpoint is missing, corrupt or inconsistent: resuming from it is refused."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS listings (
  category TEXT, sub_category TEXT, url TEXT, query TEXT, taxonomy TEXT, curated INTEGER DEFAULT 0,
  next_page INTEGER DEFAULT 1, status TEXT DEFAULT 'pending', error TEXT DEFAULT '',
  seen INTEGER DEFAULT 0, matched INTEGER DEFAULT 0, kept INTEGER DEFAULT 0, pages INTEGER DEFAULT 0,
  reported_total INTEGER DEFAULT 0, empty_streak INTEGER DEFAULT 0, stop_reason TEXT DEFAULT '',
  mode TEXT DEFAULT 'query', parent TEXT DEFAULT '',
  PRIMARY KEY (category, url));
CREATE TABLE IF NOT EXISTS items (upc TEXT PRIMARY KEY, category TEXT, sub_category TEXT, record TEXT);
CREATE TABLE IF NOT EXISTS seen (upc TEXT, category TEXT, sub_category TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS events (ts TEXT DEFAULT CURRENT_TIMESTAMP, kind TEXT, detail TEXT);
-- one row per fetched page: what was asked, what came back, which store it was for (provenance ledger)
CREATE TABLE IF NOT EXISTS ledger (ts TEXT, kind TEXT, category TEXT, sub_category TEXT, query TEXT, url TEXT,
  response_sha256 TEXT, response_bytes INTEGER, evidence_file TEXT, store_location_id TEXT, request_location_id TEXT,
  active_modality TEXT, listed INTEGER, priced INTEGER, price_source_locations TEXT, reported_total INTEGER,
  store_ok INTEGER);
-- every product a query listed (coverage reconciliation: query total vs distinct products actually read)
CREATE TABLE IF NOT EXISTS listing_items (url TEXT, upc TEXT, brand TEXT, PRIMARY KEY (url, upc));
-- every kept product's source facts kept outside the 22-field record (identity, availability, offers, page)
CREATE TABLE IF NOT EXISTS observations (identity TEXT PRIMARY KEY, upc TEXT, source_product_id TEXT,
  identity_source TEXT, availability TEXT, sell_by TEXT, modalities TEXT, offers TEXT, response_sha256 TEXT,
  observed_at TEXT, query TEXT);
-- products Mariano's own search filter savings=Coupons returns (retailer-supported "has a digital coupon" flag)
CREATE TABLE IF NOT EXISTS coupon_flags (identity TEXT, query TEXT, response_sha256 TEXT, PRIMARY KEY (identity, query));
CREATE TABLE IF NOT EXISTS exclusions (identity TEXT, category TEXT, sub_category TEXT, reason TEXT,
  trigger_field TEXT, trigger_text TEXT, response_sha256 TEXT, PRIMARY KEY (identity, reason));
"""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _integrity_ok(path: Path) -> bool:
    db = sqlite3.connect(path)
    try:
        return db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    except sqlite3.DatabaseError:
        return False
    finally:
        db.close()


class Checkpoint:
    def __init__(self, path: Path, mode: str | None = None, snapshot_seconds: float | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.mode = mode or os.getenv("MSCRAPER_CHECKPOINT_MODE", "direct")
        if self.mode not in ("direct", "snapshot"):
            raise CheckpointError(f"unknown checkpoint mode {self.mode!r}")
        self.interval = float(os.getenv("MSCRAPER_SNAPSHOT_SECONDS", "5") if snapshot_seconds is None else snapshot_seconds)
        self.manifest = self.path.parent / "checkpoint.manifest.json"
        self.seq, self._dirty, self._last_flush = 0, False, 0.0
        if self.mode == "snapshot":
            work = Path(os.getenv("MSCRAPER_LOCAL_WORK") or tempfile.gettempdir()) / "mscraper-ckpt"
            self.work = work / hashlib.sha1(str(self.path.resolve()).encode()).hexdigest()[:16] / "checkpoint.sqlite"
            self.work.parent.mkdir(parents=True, exist_ok=True)
            self._restore()
            self.db = sqlite3.connect(self.work)
        else:
            self.db = sqlite3.connect(self.path)
        before = self.db.total_changes
        self.db.executescript(SCHEMA)
        self.db.commit()
        self._dirty = self.mode == "snapshot" and (self.db.total_changes != before or self.seq == 0)

    # -- snapshot mode: restore / flush ---------------------------------------------------------------------------
    def _restore(self) -> None:
        for stale in (self.work, self.work.with_name(self.work.name + "-journal")):
            stale.unlink(missing_ok=True)       # the local copy is never trusted: always rebuilt from the share
        if not self.manifest.exists():
            if self.path.exists() and self.path.stat().st_size > 0:
                raise CheckpointError(f"{self.path}: a direct-mode database exists but no snapshot manifest - "
                                      f"refusing to guess which state is current")
            return
        try:
            m = json.loads(self.manifest.read_text(encoding="utf-8"))
            snap, seq, sha = self.path.parent / m["file"], int(m["seq"]), m["sha256"]
        except Exception as exc:
            raise CheckpointError(f"{self.manifest}: unreadable manifest ({exc})") from exc
        if not snap.exists():
            raise CheckpointError(f"{self.manifest}: snapshot {m['file']} is missing")
        if _sha256(snap) != sha:
            raise CheckpointError(f"{snap}: SHA-256 differs from the manifest (corrupt or partial snapshot)")
        tmp = self.work.with_suffix(".restore")
        tmp.write_bytes(snap.read_bytes())
        if _sha256(tmp) != sha or not _integrity_ok(tmp):
            tmp.unlink(missing_ok=True)
            raise CheckpointError(f"{snap}: restored copy fails SHA-256 / PRAGMA integrity_check")
        os.replace(tmp, self.work)
        self.seq = seq

    def flush(self, force: bool = False) -> dict | None:
        """Write a consistent snapshot + manifest to the share (snapshot mode). Returns the manifest written."""
        if self.mode != "snapshot" or not self._dirty:
            return None
        if not force and time.monotonic() - self._last_flush < self.interval:
            return None
        lock.check_active()                     # lease lost -> no further checkpoint writes
        seq = self.seq + 1
        local = self.work.with_name(f"snap-{seq:06d}.sqlite")
        dst = sqlite3.connect(local)
        try:
            self.db.backup(dst)
        finally:
            dst.close()
        if not _integrity_ok(local):
            local.unlink(missing_ok=True)
            raise CheckpointError("snapshot failed PRAGMA integrity_check - not written")
        sha, size = _sha256(local), local.stat().st_size
        name = f"checkpoint.snap-{seq:06d}.sqlite"
        target = self.path.parent / name
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(local.read_bytes())
        os.replace(tmp, target)
        local.unlink(missing_ok=True)
        m = {"seq": seq, "file": name, "sha256": sha, "bytes": size, "integrity": "ok",
             "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        mtmp = self.manifest.with_suffix(".tmp")
        mtmp.write_text(json.dumps(m, indent=2), encoding="utf-8")
        lock.check_active()                     # never commit a snapshot after losing ownership
        os.replace(mtmp, self.manifest)         # commit point
        old = self.path.parent / f"checkpoint.snap-{self.seq:06d}.sqlite"
        if self.seq and old != target:
            old.unlink(missing_ok=True)
        self.seq, self._dirty, self._last_flush = seq, False, time.monotonic()
        return m

    @contextmanager
    def tx(self):
        try:
            yield self.db
            lock.check_active()                 # lease lost -> roll back instead of committing
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self._dirty = True
        self.flush()

    # meta / events
    def set(self, key: str, value) -> None:
        with self.tx() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, json.dumps(value)))

    def get(self, key: str, default=None):
        row = self.db.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def incr(self, key: str, by: int = 1) -> int:
        v = int(self.get(key, 0)) + by
        self.set(key, v)
        return v

    def event(self, kind: str, detail: dict) -> None:
        with self.tx() as db:
            db.execute("INSERT INTO events(kind, detail) VALUES (?, ?)", (kind, json.dumps(detail, default=str)))

    # listings
    def add_listing(self, category: str, sub: str, url: str, query: str, taxonomy: str, curated: bool,
                    mode: str = "query", parent: str = "") -> bool:
        with self.tx() as db:
            cur = db.execute("INSERT OR IGNORE INTO listings(category, sub_category, url, query, taxonomy, curated, mode, parent) "
                             "VALUES (?,?,?,?,?,?,?,?)", (category, sub, url, query, taxonomy, int(curated), mode, parent))
            return bool(cur.rowcount)

    def listings(self) -> list[dict]:
        cur = self.db.execute("SELECT * FROM listings ORDER BY rowid")
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def pending(self) -> list[dict]:
        return [l for l in self.listings() if l["status"] in ("pending", "running")]

    def commit_page(self, category: str, url: str, page: int, accepted: list[tuple[str, str, dict]],
                    skipped: list[tuple[str, str]], seen: int, matched: int, done: bool, stop_reason: str,
                    empty_streak: int, reported_total: int) -> int:
        """Atomically store a page's records and advance the listing pointer. Returns # newly kept."""
        new = 0
        with self.tx() as db:
            for upc, sub, rec in accepted:
                cur = db.execute("INSERT OR IGNORE INTO items VALUES (?,?,?,?)", (upc, category, sub, json.dumps(rec)))
                if cur.rowcount:
                    new += 1
                db.execute("INSERT INTO seen VALUES (?,?,?,?)", (upc, category, sub, "kept" if cur.rowcount else "duplicate"))
            for upc, reason in skipped:
                db.execute("INSERT INTO seen VALUES (?,?,?,?)", (upc, category, "", reason))
            db.execute("UPDATE listings SET next_page=?, status=?, seen=seen+?, matched=matched+?, kept=kept+?, pages=pages+1, "
                       "empty_streak=?, stop_reason=?, reported_total=MAX(reported_total, ?) WHERE category=? AND url=?",
                       (page + 1, "done" if done else "running", seen, matched, new, empty_streak, stop_reason,
                        reported_total, category, url))
        return new

    def ledger_add(self, row: dict) -> None:
        cols = ("ts", "kind", "category", "sub_category", "query", "url", "response_sha256", "response_bytes",
                "evidence_file", "store_location_id", "request_location_id", "active_modality", "listed", "priced",
                "price_source_locations", "reported_total", "store_ok")
        with self.tx() as db:
            db.execute(f"INSERT INTO ledger ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                       tuple(row.get(c, "") for c in cols))

    def listing_items_add(self, url: str, items: list[tuple[str, str]]) -> None:
        with self.tx() as db:
            db.executemany("INSERT OR IGNORE INTO listing_items VALUES (?,?,?)", [(url, u, b) for u, b in items])

    def observe(self, rows: list[dict]) -> None:
        cols = ("identity", "upc", "source_product_id", "identity_source", "availability", "sell_by", "modalities",
                "offers", "response_sha256", "observed_at", "query")
        with self.tx() as db:
            db.executemany(f"INSERT OR IGNORE INTO observations VALUES ({','.join('?' * len(cols))})",
                           [tuple(r.get(c, "") for c in cols) for r in rows])

    def exclude(self, rows: list[dict]) -> None:
        cols = ("identity", "category", "sub_category", "reason", "trigger_field", "trigger_text", "response_sha256")
        with self.tx() as db:
            db.executemany(f"INSERT OR IGNORE INTO exclusions VALUES ({','.join('?' * len(cols))})",
                           [tuple(r.get(c, "") for c in cols) for r in rows])

    def flag_coupons(self, rows: list[tuple[str, str, str]]) -> None:
        with self.tx() as db:
            db.executemany("INSERT OR IGNORE INTO coupon_flags VALUES (?,?,?)", rows)

    def table(self, name: str) -> list[dict]:
        cur = self.db.execute(f"SELECT * FROM {name} ORDER BY rowid")
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def finish_listing(self, category: str, url: str, stop_reason: str) -> None:
        with self.tx() as db:
            db.execute("UPDATE listings SET status='done', stop_reason=? WHERE category=? AND url=?", (stop_reason, category, url))

    def fail_listing(self, category: str, url: str, error: str) -> None:
        with self.tx() as db:
            db.execute("UPDATE listings SET status='failed', error=? WHERE category=? AND url=?", (error[:500], category, url))

    def retry_failed(self) -> int:
        with self.tx() as db:
            return db.execute("UPDATE listings SET status='pending', error='' WHERE status='failed'").rowcount

    # items
    def kept_in_category(self, category: str) -> int:
        return self.db.execute("SELECT COUNT(*) FROM items WHERE category=?", (category,)).fetchone()[0]

    def records(self) -> list[dict]:
        return [json.loads(r[0]) for r in self.db.execute("SELECT record FROM items ORDER BY rowid")]

    def identified_records(self) -> dict[str, dict]:
        """identity -> record (identity = UPC, or product:<Mariano's product id> when the product has no UPC)."""
        return {r[0]: json.loads(r[1]) for r in self.db.execute("SELECT upc, record FROM items ORDER BY rowid")}

    def skip_reasons(self) -> dict[str, int]:
        return dict(self.db.execute("SELECT reason, COUNT(*) FROM seen GROUP BY reason").fetchall())

    def close(self) -> None:
        try:
            self.flush(force=True)
        finally:
            self.db.close()


def read_meta(run_dir: Path, key: str):
    """Read one meta value of a run's checkpoint in either mode without modifying it (None if absent)."""
    run_dir = Path(run_dir)
    manifest = run_dir / "checkpoint.manifest.json"
    if manifest.exists():
        m = json.loads(manifest.read_text(encoding="utf-8"))
        path = run_dir / m["file"]
        if _sha256(path) != m["sha256"]:
            raise CheckpointError(f"{path}: SHA-256 differs from the manifest")
    else:
        path = run_dir / "checkpoint.sqlite"
        if not path.exists() or path.stat().st_size == 0:
            return None
    with tempfile.TemporaryDirectory() as d:     # read a private copy: no lock on the share is ever needed
        copy = Path(d) / "c.sqlite"
        copy.write_bytes(path.read_bytes())
        db = sqlite3.connect(copy)
        try:
            row = db.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
        except sqlite3.DatabaseError:
            row = None
        finally:
            db.close()
    return json.loads(row[0]) if row else None
