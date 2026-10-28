"""Durable run state in SQLite: genuine continuation after an interruption.

Stored per run:
* listings  – every (category, subcategory) listing with the next page to fetch and status
* items     – every accepted record (JSON) keyed by Walmart item id → dedup across the run
* seen      – every item id encountered with the reason it was kept or skipped
* meta      – store verification, timings, counters

Records are written in the same transaction that advances the page pointer, so a crash
can never lose a page or record it twice.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS listings (
  category TEXT, sub_category TEXT, url TEXT, next_page INTEGER DEFAULT 1,
  max_page INTEGER DEFAULT 0, status TEXT DEFAULT 'pending', error TEXT DEFAULT '',
  kept INTEGER DEFAULT 0, seen INTEGER DEFAULT 0, capped INTEGER DEFAULT 0,
  reported_total INTEGER DEFAULT 0, page_size INTEGER DEFAULT 0,
  PRIMARY KEY (category, url));
CREATE TABLE IF NOT EXISTS items (item_id TEXT PRIMARY KEY, category TEXT, sub_category TEXT,
  record TEXT, enriched INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS seen (item_id TEXT, category TEXT, sub_category TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS events (ts TEXT DEFAULT CURRENT_TIMESTAMP, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS availability (item_id TEXT PRIMARY KEY, status TEXT, source_value TEXT,
  price_source TEXT, observed_at TEXT, url TEXT);
"""


def _clean(row: dict) -> dict:
    """Output boundary: product URLs without Walmart's listing filter / tracking query (also for older checkpoints)."""
    from .parse.walmart import product_url
    if row.get("url"):
        row["url"] = product_url(row["url"])
    return row


class Checkpoint:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.executescript(SCHEMA)
        for col in ("reported_total", "page_size", "expected_store_total", "store_available", "store_oos",
                    "zero_streak", "stop_reason"):  # forward-compatible with older checkpoints
            try:
                kind = "TEXT DEFAULT ''" if col == "stop_reason" else "INTEGER DEFAULT 0"
                self.db.execute(f"ALTER TABLE listings ADD COLUMN {col} {kind}")
            except sqlite3.OperationalError:
                pass
        self.db.commit()

    @contextmanager
    def tx(self):
        from .lock import check_active
        try:
            yield self.db
            check_active()                  # lease lost -> roll back instead of committing
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    # meta
    def set(self, key: str, value) -> None:
        with self.tx() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, json.dumps(value)))

    def get(self, key: str, default=None):
        row = self.db.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def event(self, kind: str, detail: dict) -> None:
        with self.tx() as db:
            db.execute("INSERT INTO events(kind, detail) VALUES (?, ?)", (kind, json.dumps(detail)))

    # listings
    def add_listing(self, category: str, sub: str, url: str, expected_store_total: int = 0) -> None:
        with self.tx() as db:
            db.execute("INSERT OR IGNORE INTO listings(category, sub_category, url, expected_store_total) VALUES (?,?,?,?)",
                       (category, sub, url, expected_store_total))

    def listing_progress(self, category: str, url: str, store_available: int, store_oos: int, zero_streak: int,
                         stop_reason: str = "") -> None:
        with self.tx() as db:
            db.execute("UPDATE listings SET store_available=store_available+?, store_oos=store_oos+?, zero_streak=?, "
                       "stop_reason=? WHERE category=? AND url=?",
                       (store_available, store_oos, zero_streak, stop_reason, category, url))

    def listing_row(self, category: str, url: str) -> dict:
        return next(l for l in self.listings() if l["category"] == category and l["url"] == url)

    def pending_listings(self):
        return self.db.execute(
            "SELECT category, sub_category, url, next_page FROM listings WHERE status IN ('pending','running') ORDER BY rowid"
        ).fetchall()

    def listings(self):
        cur = self.db.execute("SELECT category, sub_category, url, next_page, max_page, status, error, kept, seen, capped, "
                              "reported_total, page_size, expected_store_total, store_available, store_oos, zero_streak, "
                              "stop_reason FROM listings ORDER BY rowid")
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def commit_page(self, category: str, url: str, page: int, max_page: int,
                    accepted: list[tuple[str, str, dict]], skipped: list[tuple[str, str]], sub: str, done: bool, capped: bool,
                    reported_total: int = 0, page_size: int = 0) -> int:
        """Atomically store a page's records and advance the pointer. Returns # newly kept."""
        new = 0
        with self.tx() as db:
            for item_id, sub_cat, rec in accepted:
                cur = db.execute("INSERT OR IGNORE INTO items(item_id, category, sub_category, record) VALUES (?,?,?,?)",
                                 (item_id, category, sub_cat, json.dumps(rec)))
                if cur.rowcount:
                    new += 1
                    db.execute("INSERT INTO seen VALUES (?,?,?,?)", (item_id, category, sub_cat, "kept"))
                else:
                    db.execute("INSERT INTO seen VALUES (?,?,?,?)", (item_id, category, sub_cat, "duplicate"))
            for item_id, reason in skipped:
                db.execute("INSERT INTO seen VALUES (?,?,?,?)", (item_id, category, sub, reason))
            db.execute(
                "UPDATE listings SET next_page=?, max_page=?, status=?, kept=kept+?, seen=seen+?, capped=? WHERE category=? AND url=?",
                (page + 1, max_page, "done" if done else "running", new, len(accepted) + len(skipped), int(capped), category, url),
            )
            if page == 1:  # Walmart's own count for this listing → basis for thin-result detection
                db.execute("UPDATE listings SET reported_total=?, page_size=? WHERE category=? AND url=?",
                           (reported_total, page_size, category, url))
        return new

    def set_availability(self, rows: list[tuple]) -> None:
        with self.tx() as db:
            db.executemany("INSERT OR IGNORE INTO availability VALUES (?,?,?,?,?,?)", rows)

    def availability_rows(self) -> list[dict]:
        cur = self.db.execute("SELECT item_id, status, source_value, price_source, observed_at, url FROM availability")
        cols = [c[0] for c in cur.description]
        return [_clean(dict(zip(cols, r))) for r in cur.fetchall()]

    def item_ids(self) -> set[str]:
        return {r[0] for r in self.db.execute("SELECT item_id FROM items")}

    def add_carried(self, item_id: str, category: str, sub: str, record: dict) -> None:
        with self.tx() as db:
            db.execute("INSERT OR IGNORE INTO items(item_id, category, sub_category, record, enriched) VALUES (?,?,?,?,4)",
                       (item_id, category, sub, json.dumps(record)))

    def fail_listing(self, category: str, url: str, error: str) -> None:
        with self.tx() as db:
            db.execute("UPDATE listings SET status='failed', error=? WHERE category=? AND url=?", (error[:500], category, url))

    TRANSIENT = ("HTTP 429", "QUOTA_EXCEEDED", "HTTP 5", "provider HTTP 5", "Timeout", "timed out", "disconnected",
                 "request budget", "RemoteProtocolError", "ConnectError", "ReadError")

    def _transient_sql(self) -> str:
        return "(" + " OR ".join("error LIKE ?" for _ in self.TRANSIENT) + ")"

    def retry_transient(self) -> int:
        """Re-queue listings that failed for a transient reason (quota, provider/server error, timeout)."""
        with self.tx() as db:
            return db.execute(f"UPDATE listings SET status='pending', error='' WHERE status='failed' AND "
                              f"{self._transient_sql()} AND error NOT LIKE 'discovery failed%' "
                              f"AND error NOT LIKE 'store assortment count%' AND error NOT LIKE 'price band%'",
                              [f"%{t}%" for t in self.TRANSIENT]).rowcount

    def replan_transient_failures(self) -> list[str]:
        """Categories whose PLANNING hit a transient failure: their failed planning rows are removed so the
        category is planned again (already planned listings and their progress are kept)."""
        rows = self.db.execute(
            f"SELECT DISTINCT category FROM listings WHERE status='failed' AND {self._transient_sql()} AND "
            f"(error LIKE 'discovery failed%' OR error LIKE 'store assortment count%' OR error LIKE 'price band%')",
            [f"%{t}%" for t in self.TRANSIENT]).fetchall()
        with self.tx() as db:
            db.execute(f"DELETE FROM listings WHERE status='failed' AND {self._transient_sql()} AND "
                       f"(error LIKE 'discovery failed%' OR error LIKE 'store assortment count%' OR error LIKE 'price band%')",
                       [f"%{t}%" for t in self.TRANSIENT])
        return [r[0] for r in rows]

    def retry_failed(self) -> int:
        with self.tx() as db:
            return db.execute("UPDATE listings SET status='pending', error='' WHERE status='failed'").rowcount

    # items
    def has_item(self, item_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM items WHERE item_id=?", (item_id,)).fetchone() is not None

    def unenriched(self):
        return [(r[0], _clean(json.loads(r[1]))) for r in
                self.db.execute("SELECT item_id, record FROM items WHERE enriched=0 ORDER BY rowid")]

    def update_item(self, item_id: str, record: dict | None, enriched: int = 1) -> None:
        with self.tx() as db:
            if record is None:  # dropped during enrichment (e.g. marketplace on product page)
                db.execute("DELETE FROM items WHERE item_id=?", (item_id,))
            else:
                db.execute("UPDATE items SET record=?, enriched=? WHERE item_id=?", (json.dumps(record), enriched, item_id))

    def defer_items(self, item_ids: list[str]) -> None:
        """Mark items whose product page (UPC) is fetched first on the next run - one transaction."""
        with self.tx() as db:
            db.executemany("UPDATE items SET enriched=6 WHERE item_id=? AND enriched=0", [(i,) for i in item_ids])

    def records(self) -> list[dict]:
        return [_clean(json.loads(r[0])) for r in self.db.execute("SELECT record FROM items ORDER BY rowid")]

    def count_items(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM items").fetchone()[0]

    def skip_reasons(self) -> dict[str, int]:
        return dict(self.db.execute("SELECT reason, COUNT(*) FROM seen GROUP BY reason").fetchall())

    def close(self) -> None:
        self.db.close()
