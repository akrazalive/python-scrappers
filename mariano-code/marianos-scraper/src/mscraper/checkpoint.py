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
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

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


class Checkpoint:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.executescript(SCHEMA)
        self.db.commit()

    @contextmanager
    def tx(self):
        try:
            yield self.db
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

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
        self.db.close()
