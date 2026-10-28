"""Run orchestration for one location.

Phases (each resumable from the checkpoint):
  1. lock          – refuse to start if another run for this location is active
  2. store         – fetch the store page, confirm id / name / address / ZIP
  3. canary:start  – known items must show a local (pickup / in-store) Walmart offer
  4. discovery     – category pages → subcategory listings (CSV exclusions applied)
  5. listings      – paginate every listing; per page: shape check, store check,
                     filter sponsored / marketplace / shipping-only / approx-weight, dedup
  6. enrichment    – product pages: UPC, size, store-level offer re-check, deals
  7. canary:end
  8. validate      – publish to latest/ only if every check passes
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse

from .checkpoint import Checkpoint
from .config import Category, Location, Settings
from .fetch import FetchError, build_fetcher
from .lock import run_lock
from .models import Record
from .parse import deals
from .parse.text import clean_text, extract_weight, format_price, is_approximate_weight, is_private_label
from .parse.walmart import (ChallengeError, ListingItem, ShapeError, category_id_of, children_of, department_children,
                            discover_links, next_data, parse_listing, parse_product, parse_store, store_context_excerpt)
from .report import build_report
from .storage import build_storage
from .validate import validate_run
from .version import version_info

log = logging.getLogger("wmscraper.run")


def item_id_from_url(url: str) -> str:
    m = re.search(r"/ip/(?:[^/?#]+/)?(\d+)(?:[?#]|$)", url or "")
    return m.group(1) if m else ""


def with_params(url: str, **params) -> str:
    u = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(u.query) if k not in params and k != "povid"]
    q += [(k, str(v)) for k, v in params.items() if v not in (None, "")]
    return urlunparse(u._replace(query=urlencode(q)))


class Run:
    def __init__(self, settings: Settings, location: Location, run_id: str | None = None,
                 categories: list[Category] | None = None, limit: int = 0, demo: bool = False):
        self.s = settings
        self.loc = location
        self.crawl = {**(settings.get("crawl") or {}), **dict(location.crawl)}  # location overrides win
        self.categories = categories or settings.categories_for(location)
        self.limit = limit or int(settings.get("crawl.max_products_per_run", 0))
        self.demo = demo
        self.storage = build_storage(settings)
        prefix = f"{location.key}/runs/"
        if run_id is None:
            run_id = self._resumable_run() or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
        self.run_id = run_id
        self.prefix = prefix + run_id
        self.ck = Checkpoint(self._checkpoint_path())
        self.crawl_date = self.ck.get("crawl_date") or datetime.now(timezone.utc).date().isoformat()
        self.ck.set("crawl_date", self.crawl_date)
        self.store: dict = self.ck.get("store_verification") or {}

    # ------------------------------------------------------------------ helpers
    def _archive(self, kind: str, res, note: str = "", always: bool = False) -> dict | None:
        """Keep raw source responses (gzip) + a store-context excerpt as evidence. Bounded per kind unless `always`
        (store page and canaries: every response is kept, before it is validated)."""
        import gzip
        import hashlib

        limit = int(self.s.get("evidence.raw_samples_per_kind", 5))
        counts = self.ck.get("raw_counts", {})
        if counts.get(kind, 0) >= limit and not always:
            return None
        counts[kind] = counts.get(kind, 0) + 1
        self.ck.set("raw_counts", counts)
        name = f"{kind}-{counts[kind]:02d}"
        body = res.html.encode("utf-8")
        self.storage.put_bytes(f"{self.prefix}/raw/{name}.html.gz", gzip.compress(body))
        try:
            excerpt = store_context_excerpt(next_data(res.html, res.final_url))
        except Exception as exc:  # archived even when unparsable – that is evidence too
            excerpt = [{"error": str(exc)}]
        index = self.storage.get_json(f"{self.prefix}/raw/index.json") or []
        index.append({"file": f"{name}.html.gz", "kind": kind, "url": res.url, "final_url": res.final_url,
                      "status": res.status, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                      "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "note": note,
                      "store_context": excerpt})
        self.storage.put_json(f"{self.prefix}/raw/index.json", index)
        return index[-1]

    def _checkpoint_path(self):
        local = self.storage.local_path(f"{self.prefix}/checkpoint.sqlite")
        if local:
            return local
        # Azure: work on a local copy and upload it after every committed page
        from pathlib import Path
        p = Path("/tmp") / self.prefix.replace("/", "_") / "checkpoint.sqlite"
        p.parent.mkdir(parents=True, exist_ok=True)
        data = self.storage.get_bytes(f"{self.prefix}/checkpoint.sqlite")
        if data:
            p.write_bytes(data)
        return p

    def _sync_checkpoint(self):
        from .lock import check_active
        check_active()                      # lease lost -> no further checkpoint upload
        if not self.storage.local_path(f"{self.prefix}/checkpoint.sqlite"):
            self.ck.db.commit()
            self.storage.put_bytes(f"{self.prefix}/checkpoint.sqlite", self.ck.path.read_bytes())

    def _resumable_run(self) -> str | None:
        state = self.storage.get_json(f"{self.loc.key}/state.json") or {}
        return state.get("open_run")

    def _set_state(self, open_run: str | None):
        state = self.storage.get_json(f"{self.loc.key}/state.json") or {}
        state["open_run"] = open_run
        self.storage.put_json(f"{self.loc.key}/state.json", state)

    # ------------------------------------------------------------------ main
    async def execute(self) -> dict:
        t0 = time.monotonic()
        with run_lock(self.storage, self.loc.key):
            self._set_state(self.run_id)
            resumed = bool(self.ck.listings())
            if resumed:
                pending = self.ck.pending_listings()
                self.ck.event("run_resumed", {"pending_listings": len(pending), "items_already_kept": self.ck.count_items(),
                                              "next_pages": [[c, s, p] for c, s, _u, p in pending[:20]]})
            log.info("run_start", extra={"run_id": self.run_id, "location": self.loc.key, "store_id": self.loc.store_id,
                                         "fulfillment": self.loc.fulfillment, "resumed": resumed,
                                         "items_already_kept": self.ck.count_items(), **version_info()})
            self.ck.event("session_start", {"resumed": resumed, "items_already_kept": self.ck.count_items(),
                                            **version_info()})  # which exact source ran each part of the run
            self.fetcher = build_fetcher(self.s, self.loc)
            await self.fetcher.start()
            self.aborted = ""
            try:
                await self.verify_store()
                await self.canary("start")
                await self.discover()
                await self.crawl_listings()
                if self.crawl.get("enrich_product_pages", True):
                    await self.enrich()
                await self.canary("end")
            except Exception as exc:  # report, keep checkpoint, stay resumable
                self.aborted = f"{type(exc).__name__}: {exc}"
                self.ck.event("run_aborted", {"error": self.aborted})
                log.exception("run_aborted")
            finally:
                await self.fetcher.close()
            runtime = float(self.ck.get("runtime_total", 0)) + time.monotonic() - t0
            self.ck.set("runtime_total", runtime)
            self._sync_checkpoint()
            return self.finish(runtime)

    def _carry_forward(self) -> None:
        """Products in the last published dataset that Walmart did not return this run are kept with their
        last-observed values and ORIGINAL crawl_date (never presented as newly verified)."""
        if not self.s.get("crawl.carry_forward", True) or self.ck.get("carry_forward_done"):
            return
        prev = self.storage.get_json(f"{self.loc.key}/latest/records.json") or []
        prev_avail = {r["item_id"]: r for r in self.storage.get_json(f"{self.loc.key}/latest/availability.json") or []}
        in_scope = {c.name for c in self.categories}
        done = {l["category"] for l in self.ck.listings() if l["status"] == "done"}
        have = self.ck.item_ids()
        rows, n = [], 0
        for rec in prev:
            iid = item_id_from_url(rec["url"])
            if not iid or iid in have or rec["category"] not in in_scope or rec["category"] not in done:
                continue
            if prev_avail.get(iid, {}).get("status") == "shipping_only_not_sold_at_store":
                continue  # never carry an online-only offer into the store assortment
            self.ck.add_carried(iid, rec["category"], rec["sub_category"], rec)
            last = prev_avail.get(iid, {})
            rows.append((iid, "not_returned_this_run", last.get("source_value", ""), "last_observed",
                         last.get("observed_at", rec.get("crawl_date", "")), rec["url"]))
            n += 1
        self.ck.set_availability(rows)
        self.ck.set("carried_forward", n)
        self.ck.set("carry_forward_done", True)
        log.info("carry_forward", extra={"carried_forward": n, "from_run": (self.storage.get_json(
            f"{self.loc.key}/latest/manifest.json") or {}).get("run_id")})

    def finish(self, runtime: float) -> dict:
        if not getattr(self, "aborted", ""):
            self._carry_forward()
        records = self.ck.records()
        previous = self.storage.get_json(f"{self.loc.key}/latest/report.json")
        validation = validate_run(self.s, self.ck, records, self.categories, previous)
        if getattr(self, "aborted", ""):
            validation.fail(f"run aborted: {self.aborted} (checkpoint kept – next run resumes)")
        if self.demo:
            validation.warn("DEMO run (category subset / record limit) – never published to latest/")
        report = build_report(self.run_id, self.loc, self.store, self.ck, records, runtime,
                              self.fetcher.stats, validation.as_dict(), self.s)
        avail = self.ck.availability_rows()
        self.storage.put_json(f"{self.prefix}/records.json", records)
        self.storage.put_json(f"{self.prefix}/availability.json", avail)
        self.storage.put_bytes(f"{self.prefix}/availability-log.jsonl",
                               "\n".join(json.dumps(a, ensure_ascii=False) for a in avail).encode("utf-8"))
        self.storage.put_json(f"{self.prefix}/report.json", report)
        published = None
        if validation.ok and not self.demo:
            published = self.storage.publish(self.loc.key, self.run_id, records, report)
            self.storage.put_json(f"{self.loc.key}/latest/availability.json", avail)
            log.info("published", extra=published)
        else:
            log.error("not_published", extra={"run_id": self.run_id, "errors": validation.errors[:20], "demo": self.demo})
        if not getattr(self, "aborted", "") or self.demo:
            self._set_state(None)  # aborted production runs stay open for resumption
        report["published"] = published
        self.storage.put_json(f"{self.prefix}/report.json", report)
        log.info("run_end", extra={"run_id": self.run_id, "records": len(records), "ok": validation.ok,
                                   "runtime_s": round(runtime, 1)})
        return report

    # ------------------------------------------------------------------ phases
    async def verify_store(self):
        if self.store.get("verified"):
            return
        url = f"https://www.walmart.com/store/{self.loc.store_id}"
        try:
            res = await self.fetcher.get(url)
            self._archive("store", res, "store verification page", always=True)
            info = parse_store(res.html, self.loc.store_id, res.final_url)
        except (FetchError, ShapeError, ChallengeError) as exc:
            self.store = {"verified": False, "reason": str(exc), "url": url}
            self.ck.set("store_verification", self.store)
            raise RuntimeError(f"store verification failed: {exc}") from exc
        problems = []
        if self.loc.zipcode and info.zipcode != self.loc.zipcode:
            problems.append(f"ZIP {info.zipcode} != configured {self.loc.zipcode}")
        if self.loc.expected_address and self.loc.expected_address.lower() not in info.address.lower():
            problems.append(f"address '{info.address}' does not contain configured '{self.loc.expected_address}'")
        zip_ok = not problems
        self.store = {"verified": zip_ok, "store_id": info.store_id, "store_name": info.name,
                      "store_location": info.address, "zipcode": info.zipcode, "url": url,
                      "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "reason": "; ".join(problems)}
        self.ck.set("store_verification", self.store)
        log.info("store_verified" if zip_ok else "store_mismatch", extra=self.store)
        if not zip_ok:
            raise RuntimeError(self.store["reason"])

    # ------------------------------------------------------------------ context checks (explicit)
    def _check_context(self, location: dict, where: str) -> bool:
        """The page's SELECTED location must be the configured store (explicit path), not merely contain its id."""
        if location.get("storeId") == self.loc.store_id:
            self.ck.set("store_verified_pages", self.ck.get("store_verified_pages", 0) + 1)
            return True
        self.ck.set("store_mismatches", self.ck.get("store_mismatches", 0) + 1)
        self.ck.event("store_mismatch", {"where": where, "selected_location": location})
        log.error("store_context_mismatch", extra={"where": where, "selected_location": location})
        return False

    def _product_context_ok(self, p) -> bool:
        loc = p.location or {}
        return loc.get("pickupStoreId") == self.loc.store_id or self.loc.store_id in (loc.get("storeIds") or [])

    def canary_problems(self, p, item_id: str) -> list[str]:
        """Store identity AND fulfillment AND store-sourced price, all from the returned product (not from labels,
        cookies or request parameters). A store id somewhere in the response is not enough."""
        want = self.loc.store_id
        loc = p.location or {}
        probs = []
        if p.item_id != item_id:
            probs.append(f"response identity {p.item_id}")
        if loc.get("pickupStoreId") != want:
            probs.append(f"selected pickup store {loc.get('pickupStoreId') or '-'} (location {loc})")
        if want not in (loc.get("storeIds") or []):
            probs.append(f"location.storeIds {loc.get('storeIds')} lacks {want}")
        if self.loc.fulfillment == "pickup":
            if (loc.get("intent") or "").upper() != "PICKUP":
                probs.append(f"intent {loc.get('intent') or '-'} (expected PICKUP)")
            if ("PICKUP", want) not in [(f.upper(), s) for f, s in p.fulfillment_options]:
                probs.append(f"no PICKUP option for store {want} in fulfillmentSummary {p.fulfillment_options}")
        if (p.fulfillment_type or "").upper() != "STORE":
            probs.append(f"fulfillmentType {p.fulfillment_type or '-'} (expected STORE: store-sourced offer)")
        shown = re.sub(r"[^0-9.]", "", p.current_price or "")
        if not ((p.price_value or 0) > 0 or (shown and float(shown or 0) > 0)):
            probs.append("no current price on the store offer")
        if self.loc.zipcode and loc.get("postalCode") and loc.get("postalCode") != self.loc.zipcode:
            probs.append(f"postalCode {loc.get('postalCode')} != {self.loc.zipcode}")
        return probs

    async def canary(self, phase: str):
        """Every configured canary must pass. Stops at the FIRST failing item (no further request) and raises;
        every response is archived with its hash and returned context BEFORE it is validated."""
        items = list(self.loc.canary_items)
        self.ck.set("canary_configured", bool(items))
        if not items:
            return
        state = self.ck.get("canary", {})
        if state.get(phase, {}).get("ok"):
            return
        checked = []
        for item_id in items:
            res = await self.fetcher.get(f"https://www.walmart.com/ip/{item_id}")   # terminal errors propagate
            arch = self._archive("canary", res, f"canary {phase} {item_id}", always=True)
            try:
                probs = self.canary_problems(parse_product(res.html, res.final_url), item_id)
            except Exception as exc:
                probs = [f"unparsable product response: {exc}"]
            checked.append({"item": item_id, "ok": not probs, "problems": probs,
                            "evidence": (arch or {}).get("file"), "sha256": (arch or {}).get("sha256")})
            if probs:
                break
        ok = all(c["ok"] for c in checked) and len(checked) == len(items)
        state[phase] = {"ok": ok, "items": items, "checked": checked,
                        "detail": [f"{c['item']}: {'; '.join(c['problems'])}" for c in checked if not c["ok"]],
                        "not_requested": items[len(checked):]}
        self.ck.set("canary", state)
        log.info("canary", extra={"phase": phase, "ok": ok, "checked": checked, "not_requested": items[len(checked):]})
        if not ok:
            raise FetchError(f"canary failed at {phase}: {state[phase]['detail']} – stopped, "
                             f"{len(items) - len(checked)} canary item(s) not requested", "store")

    # ------------------------------------------------------------------ discovery / planning
    def _listing_url(self, cid: str) -> str:
        return f"https://www.walmart.com/browse/{cid}"

    async def _root_id(self, cat) -> str:
        """Real category id for a CSV URL. /browse/ URLs carry it; /cp/ landing pages carry only their own node id
        (e.g. /cp/feeding/133283 -> category path 5427_133283), which is resolved from the page's own links."""
        cid = cat.category_id
        if "/cp/" not in cat.url or "_" in cid:
            return cid
        try:
            res = await self.fetcher.get(cat.url.split("?")[0])
            self._archive("category", res, f"{cat.name} landing page")
            data = next_data(res.html, res.final_url)
            paths = [category_id_of(u) for _n, u in discover_links(data, res.html)]
            paths += [k for _n, k in department_children(data)]
        except (FetchError, ShapeError, ChallengeError) as exc:
            log.warning("root_id_unresolved", extra={"category": cat.name, "error": str(exc)})
            return cid
        roots = sorted({"_".join(p.split("_")[: p.split("_").index(cid) + 1]) for p in paths if cid in p.split("_")},
                       key=len)
        root = roots[0] if roots else cid
        log.info("category_root", extra={"category": cat.name, "csv_id": cid, "root_id": root})
        return root

    def _window(self) -> int:
        """Products one listing can expose (Walmart serves at most 25 pages of ~40 products)."""
        return int(self.s.get("crawl.max_pages_per_listing", 25)) * int(self.crawl.get("page_size", 40))

    def _store_window(self) -> int:
        """Store-assortment products a listing may hold so that ALL of them (plus online-only items Walmart
        interleaves) are reachable within the page window. Above this, the node is split."""
        return int(self._window() * float(self.crawl.get("store_window_ratio", 0.75)))

    async def _store_count(self, url: str) -> int | None:
        """Walmart's own count of the store's AVAILABLE assortment for a listing (pickup facet): the floor the
        store-pinned crawl must reach (count reconciliation)."""
        try:
            res = await self.fetcher.get(with_params(url, facet="fulfillment_method:Pickup", **self._listing_params()))
            return parse_listing(res.html, res.final_url).total_count
        except (FetchError, ShapeError, ChallengeError) as exc:
            log.warning("store_count_failed", extra={"url": url, "error": str(exc)})
            return None

    async def discover(self):
        """Plan the full store-assortment traversal. Every node is opened store-pinned (no availability facet).
        A node whose store assortment exceeds the store window is split into its Departments children, then into
        whole-dollar price bands, until every planned listing can be paginated to exhaustion."""
        for cat in self.ck.replan_transient_failures():
            self.ck.set(f"discovered:{cat}", False)
            self.ck.set("discovery_done", False)
            log.info("category_replan", extra={"category": cat, "reason": "transient failure during planning"})
        if self.ck.get("discovery_done"):
            return
        sem = asyncio.Semaphore(int(self.crawl.get("category_concurrency", 4)))

        async def one(cat):
            async with sem:
                await self._discover_category(cat)

        await asyncio.gather(*(one(c) for c in self.categories))
        self.ck.set("discovery_done", True)
        self._sync_checkpoint()

    def _source_mode(self) -> bool:
        """source_count (production): listings are Walmart-sold (retailer facet) and store-pinned; every planned
        listing fits the page window and is paginated to Walmart's last page, so the products seen reconcile with
        Walmart's own reported total. store_count (legacy): pickup-facet counts as the reconciliation floor."""
        return self.crawl.get("coverage", "source_count") == "source_count"

    async def _discover_category(self, cat):
        if self.ck.get(f"discovered:{cat.name}"):
            return
        if self._source_mode():
            return await self._discover_source(cat)
        depth_max = int(self.crawl.get("subcategory_max_depth", 5))
        per_cat = int(self.crawl.get("max_listings_per_category", 0))  # 0 = all (production)
        skip = [re.compile(p, re.I) for p in self.crawl.get("skip_subcategory_patterns") or []]
        excluded = {e.lower() for e in cat.excluded_subcategories}
        extra = self._listing_params()
        leaves: list[tuple[str, str, int]] = []
        root = await self._root_id(cat)
        stack = [(cat.name, self._listing_url(root), root, 0)]
        seen = set()
        while stack and not (per_cat and len(leaves) >= per_cat):
            name, url, cid, depth = stack.pop(0)
            if cid.split("_")[-1] in seen:
                continue
            seen.add(cid.split("_")[-1])
            sub = name if depth else cat.name
            try:
                res = await self.fetcher.get(with_params(url, **extra))
                lp = parse_listing(res.html, res.final_url)
            except ShapeError as exc:
                kids = self._landing_children(res, cid, excluded, skip)
                if kids and depth < depth_max:
                    stack[0:0] = [(n, self._listing_url(k), k, depth + 1) for n, k in kids]
                    log.info("landing_page_split", extra={"category": cat.name, "node": name, "children": len(kids)})
                elif depth:
                    # merchandising/brand landing page with no listing and no child categories: its products are
                    # listed under the real departments; recorded, not a coverage gap
                    self.ck.event("landing_page_without_listing", {"category": cat.name, "node": name, "url": url})
                    log.info("landing_page_without_listing", extra={"category": cat.name, "node": name, "url": url})
                else:
                    self.ck.add_listing(cat.name, sub, url)
                    self.ck.fail_listing(cat.name, url, f"discovery failed: {exc}")
                continue
            except (FetchError, ChallengeError) as exc:
                self.ck.add_listing(cat.name, sub, url)
                self.ck.fail_listing(cat.name, url, f"discovery failed: {exc}")
                log.error("discovery_failed", extra={"category": cat.name, "url": url, "error": str(exc)})
                continue
            store_total = await self._store_count(url)
            if store_total is None:
                self.ck.add_listing(cat.name, sub, url)
                self.ck.fail_listing(cat.name, url, "store assortment count unavailable")
                continue
            if lp.total_count <= self._window() or store_total <= self._store_window():
                if self.loc.only_subcategories and sub.lower() not in {x.lower() for x in self.loc.only_subcategories}:
                    continue
                leaves.append((sub, url, store_total))
                self.ck.add_listing(cat.name, sub, url, store_total)
                if not self._check_context(lp.location, url):
                    self.ck.fail_listing(cat.name, url, f"page 1: selected store context {lp.location}")
                elif self.ck.listing_row(cat.name, url)["next_page"] == 1:
                    self._process_page(cat.name, sub, url, 1, lp, res, int(self.crawl.get("max_pages_per_listing", 25)))
                continue
            kids = [(n, k) for n, k in lp.children if k.startswith(cid + "_")
                    and n.lower() not in excluded and not any(p.search(n) for p in skip)]
            ids = {k for _n, k in kids}
            kids = [(n, k) for n, k in kids if not any(k != o and k.startswith(o + "_") for o in ids)]
            if kids and depth < depth_max:
                stack[0:0] = [(n, self._listing_url(k), k, depth + 1) for n, k in kids]
                log.info("category_split", extra={"category": cat.name, "node": name, "walmart_total": lp.total_count,
                                                  "store_assortment": store_total, "children": len(kids)})
            else:
                leaves += await self._price_partitions(cat.name, sub, url)
        if self.loc.only_subcategories:
            keep = {x.lower() for x in self.loc.only_subcategories}
            leaves = [l for l in leaves if l[0].lower() in keep]
        for sub, url, expected in leaves:
            self.ck.add_listing(cat.name, sub, url, expected)
        self.ck.set(f"discovered:{cat.name}", True)
        log.info("category_discovered", extra={"category": cat.name, "listings": len(leaves),
                                               "store_assortment_expected": sum(l[2] for l in leaves)})

    async def _discover_source(self, cat):
        """Source-count planning. Each node is opened once (store-pinned, Walmart-sold). A node whose Walmart total
        fits the page window is a listing (its page 1 is processed at once); a larger node is split into its direct
        Departments children, or - when it has none, or fans out into many overlapping merchandising shelves - into
        whole-dollar price bands. A node reached again by another path (alias) is planned once. Every planning
        decision is checkpointed per node, so a resumed run never re-plans (or re-pays for) finished nodes."""
        depth_max = int(self.crawl.get("subcategory_max_depth", 5))
        skip = [re.compile(p, re.I) for p in self.crawl.get("skip_subcategory_patterns") or []]
        excluded = {e.lower() for e in cat.excluded_subcategories}
        root = await self._root_id(cat)
        stack = [(cat.name, self._listing_url(root), root, 0)]
        seen: dict[str, str] = {}
        active = 0
        cond = asyncio.Condition()

        async def visit(name, url, cid, depth):
            sub = name if depth else cat.name
            plan = self.ck.get(f"plan:{cat.name}:{cid}")
            if plan is None:
                plan = await self._plan_node(cat.name, sub, url, cid, depth, depth_max, excluded, skip)
                if plan is None:
                    return []  # recorded as a failed listing; re-planned on resume when transient
                self.ck.set(f"plan:{cat.name}:{cid}", plan)
            return [(n, self._listing_url(k), k, depth + 1) for n, k in plan.get("kids") or []]

        async def worker():  # several nodes of one category are planned at once (shared queue, depth-first order)
            nonlocal active
            while True:
                async with cond:
                    while not stack and active:
                        await cond.wait()
                    if not stack:
                        cond.notify_all()
                        return
                    name, url, cid, depth = stack.pop(0)
                    nid = cid.split("_")[-1]
                    if nid in seen:
                        if seen[nid] != cid:
                            self.ck.event("alias_node_skipped", {"category": cat.name, "node": name, "path": cid,
                                                                 "planned_as": seen[nid]})
                        continue
                    seen[nid] = cid
                    active += 1
                try:
                    kids = await visit(name, url, cid, depth)
                    async with cond:
                        stack[0:0] = kids
                finally:
                    async with cond:
                        active -= 1
                        cond.notify_all()

        await asyncio.gather(*(worker() for _ in range(int(self.crawl.get("planning_concurrency", 4)))))
        self.ck.set(f"discovered:{cat.name}", True)
        rows = [l for l in self.ck.listings() if l["category"] == cat.name]
        log.info("category_discovered", extra={"category": cat.name, "listings": len(rows),
                                               "walmart_total_planned": sum(l["reported_total"] or 0 for l in rows)})

    async def _plan_node(self, category, sub, url, cid, depth, depth_max, excluded, skip) -> dict | None:
        max_pages = int(self.crawl.get("max_pages_per_listing", 25))
        max_kids = int(self.crawl.get("max_split_children", 30))
        try:
            page_url = with_params(url, **self._listing_params())
            res = await self.fetcher.get(page_url)
            res, lp = await self._get_listing(page_url, res)
        except ShapeError as exc:
            kids = self._landing_children(res, cid, excluded, skip)
            if kids and depth < depth_max:
                log.info("landing_page_split", extra={"category": category, "node": sub, "children": len(kids)})
                return {"kids": kids, "landing": True}
            if depth:
                self.ck.event("landing_page_without_listing", {"category": category, "node": sub, "url": url})
                return {"landing_without_listing": True}
            self.ck.add_listing(category, sub, url)
            self.ck.fail_listing(category, url, f"discovery failed: {exc}")
            return None
        except (FetchError, ChallengeError) as exc:
            self.ck.add_listing(category, sub, url)
            self.ck.fail_listing(category, url, f"discovery failed: {exc}")
            log.error("discovery_failed", extra={"category": category, "url": url, "error": str(exc)})
            return None
        if not self._check_context(lp.location, url):
            self.ck.add_listing(category, sub, url)
            self.ck.fail_listing(category, url, f"page 1: selected store context {lp.location}")
            return None
        total = lp.total_count
        raw = [(n, k) for n, k in lp.children if k.startswith(cid + "_")]
        if self._fits(lp, max_pages, has_kids=bool(raw)):
            self._plan_leaf(category, sub, url, lp, res, max_pages)
            return {"leaf": True, "walmart_total": total}
        kids = [(n, k) for n, k in raw if n.lower() not in excluded and not any(p.search(n) for p in skip)]
        ids = {k for _n, k in kids}
        kids = [(n, k) for n, k in kids if not any(k != o and k.startswith(o + "_") for o in ids)]
        has_excluded = len(kids) < len(raw)  # an excluded subcategory must never be pulled in by a price band
        if kids and depth < depth_max and (len(kids) <= max_kids or has_excluded):
            log.info("category_split", extra={"category": category, "node": sub, "walmart_total": total,
                                              "children": len(kids)})
            return {"kids": kids, "walmart_total": total}
        reason = "no_subcategories" if not kids else "max_depth" if depth >= depth_max else "merchandising_fan_out"
        self.ck.event("price_partition", {"category": category, "sub_category": sub, "url": url,
                                          "walmart_total": total, "reason": reason, "children": len(kids)})
        n, failed = await self._source_bands(category, sub, url, total, max_pages)
        return None if failed else {"bands": n, "walmart_total": total, "reason": reason}

    async def _get_listing(self, page_url: str, res=None):
        """Fetch + parse one listing page. A page that reports products but serves none is fetched once more
        before it is accepted as Walmart's own answer (guards against a transient empty response)."""
        res = res or await self.fetcher.get(page_url)
        lp = parse_listing(res.html, res.final_url)
        if not lp.items and lp.total_count:
            res = await self.fetcher.get(page_url)
            lp = parse_listing(res.html, res.final_url)
            self.ck.event("empty_page_refetched", {"url": page_url, "walmart_total": lp.total_count,
                                                   "items_after_refetch": len(lp.items), "final_url": res.final_url})
        return res, lp

    def _fits(self, lp, max_pages: int, has_kids: bool = False) -> bool:
        """All of a listing's products are reachable: Walmart exposes fewer pages than the window, its total fits the
        window, or - for a node without subcategories - its first page is not even full: then Walmart's total is not
        backed by served products (e.g. a search-fallback count) and the listing is paginated until Walmart stops
        serving products. A node WITH subcategories is always split (a category root may show a short first page)."""
        if lp.max_page < max_pages or lp.total_count <= self._window():
            return True
        return not has_kids and len(lp.items) < int(self.crawl.get("full_page_min_items", 20))

    def _plan_leaf(self, category, sub, url, lp, res, max_pages) -> None:
        self.ck.add_listing(category, sub, url)
        if self.ck.listing_row(category, url)["next_page"] == 1:
            self._process_page(category, sub, url, 1, lp, res, max_pages)

    async def _source_bands(self, category, sub, url, node_total, max_pages) -> tuple[int, int]:
        """Whole-dollar price bands (Walmart ignores fractional min/max) of a node, each opened store-pinned and
        Walmart-sold, split until its Walmart total fits the page window. A band that does not shrink although
        narrower means Walmart ignores the price filter there: recorded as an unresolved route (blocks publication)."""
        edges = [float(x) for x in self.crawl.get("price_band_edges", [0, 3, 5, 10, 20, 50, 100, 100000])]
        full = (edges[0], edges[-1])
        bands = list(zip(edges[:-1], edges[1:]))
        n = failed = 0
        while bands:
            lo, hi = bands.pop(0)
            band_url = with_params(url, min_price=f"{lo:g}", max_price=f"{hi:g}")
            try:
                res, lp = await self._get_listing(with_params(band_url, **self._listing_params()))
            except (FetchError, ShapeError, ChallengeError) as exc:
                self.ck.add_listing(category, sub, band_url)
                self.ck.fail_listing(category, band_url, f"price band failed: {exc}")
                failed += 1
                continue
            if not self._check_context(lp.location, band_url):
                self.ck.add_listing(category, sub, band_url)
                self.ck.fail_listing(category, band_url, f"page 1: selected store context {lp.location}")
                failed += 1
                continue
            total = lp.total_count
            fits = self._fits(lp, max_pages)
            if not fits and (lo, hi) != full and total >= 0.95 * node_total:
                self.ck.event("price_filter_ignored", {"category": category, "sub_category": sub, "url": band_url,
                                                       "band": [lo, hi], "walmart_total": total, "node_total": node_total})
                self.ck.add_listing(category, sub, band_url)
                self.ck.fail_listing(category, band_url, f"unresolved route: Walmart ignores the price filter "
                                                         f"({total} of {node_total} results in band {lo:g}-{hi:g})")
                return n, failed
            if not fits and hi - lo > 1:
                mid = int((lo + hi) // 2) if hi < 100000 else int(lo * 2 + 50)
                bands[0:0] = [(lo, mid), (mid, hi)]
                continue
            self.ck.event("price_band", {"category": category, "sub_category": sub, "band": [lo, hi], "walmart_total": total})
            self._plan_leaf(category, sub, band_url, lp, res, max_pages)  # a $1 band still too large ends capped
            n += 1
        log.info("price_partitioned", extra={"category": category, "sub_category": sub, "bands": n})
        return n, failed

    async def _price_partitions(self, category: str, sub: str, url: str) -> list[tuple[str, str, int]]:
        """Split an oversize store assortment into whole-dollar price bands (Walmart honours whole-dollar
        min_price / max_price only) until each band's store assortment fits the store window."""
        edges = [float(x) for x in self.crawl.get("price_band_edges", [0, 3, 5, 10, 20, 50, 100, 100000])]
        bands = list(zip(edges[:-1], edges[1:]))
        out: list[tuple[str, str, int]] = []
        while bands:
            lo, hi = bands.pop(0)
            band_url = with_params(url, min_price=f"{lo:g}", max_price=f"{hi:g}")
            total = await self._store_count(band_url)
            if total is None:
                self.ck.add_listing(category, sub, band_url)
                self.ck.fail_listing(category, band_url, "price band count failed")
                continue
            if total > self._store_window() and hi - lo > 1:
                mid = int((lo + hi) // 2) if hi < 100000 else int(lo * 2 + 50)
                bands[0:0] = [(lo, mid), (mid, hi)]
                continue
            self.ck.event("price_band", {"category": category, "sub_category": sub, "band": [lo, hi], "store_assortment": total})
            if total > self._store_window():
                log.warning("price_band_still_too_large", extra={"category": category, "sub_category": sub,
                                                                 "band": [lo, hi], "store_assortment": total})
            out.append((sub, band_url, total))
        log.info("price_partitioned", extra={"category": category, "sub_category": sub, "bands": len(out)})
        return out

    @staticmethod
    def _landing_children(res, cid: str, excluded: set, skip: list) -> list[tuple[str, str]]:
        try:
            data = next_data(res.html, res.final_url)
        except (ShapeError, ChallengeError):
            return []
        pairs = [(n, category_id_of(u)) for n, u in discover_links(data, res.html)] + department_children(data)
        kids, seen = [], set()
        for n, k in pairs:
            if k.startswith(cid + "_") and k not in seen and n and n.lower() not in excluded \
                    and not any(p.search(n) for p in skip) and n.lower() not in ("view all", "shop all", "shop now", "see all"):
                seen.add(k)
                kids.append((n, k))
        ids = {k for _n, k in kids}
        return [(n, k) for n, k in kids if not any(k != o and k.startswith(o + "_") for o in ids)]

    # ------------------------------------------------------------------ crawling
    async def crawl_listings(self):
        max_pages = int(self.crawl.get("max_pages_per_listing", 25))
        self.ck.set("pages_per_listing", max_pages)
        n = self.ck.retry_transient()
        if n:
            log.info("transient_failures_requeued", extra={"listings": n})
        sem = asyncio.Semaphore(int(self.s.get("fetch.concurrency", 1)))

        async def one(row):
            async with sem:
                await self._crawl_listing(*row, max_pages=max_pages)

        await asyncio.gather(*(one(r) for r in self.ck.pending_listings()))

    async def _crawl_listing(self, category: str, sub: str, url: str, next_page: int, max_pages: int):
        """Paginate one store-pinned listing until Walmart's last page or until the store assortment is exhausted
        (Walmart's available-store count reached and a following page carries no store offers). Ending any other
        way before the last page is incomplete coverage (capped) and blocks publication."""
        extra = self._listing_params()
        page = next_page
        while True:
            if self.limit and self.ck.count_items() >= self.limit:
                return
            page_url = with_params(url, page=page if page > 1 else None, **extra)
            try:
                res, lp = await self._get_listing(page_url)
            except (FetchError, ShapeError, ChallengeError) as exc:
                self.ck.fail_listing(category, url, f"page {page}: {exc}")
                log.error("listing_failed", extra={"category": category, "sub_category": sub, "page": page, "error": str(exc)})
                return
            if not self._check_context(lp.location, page_url):
                self.ck.fail_listing(category, url, f"page {page}: selected store context {lp.location}")
                return
            if self._process_page(category, sub, url, page, lp, res, max_pages):
                return
            page += 1

    def _process_page(self, category: str, sub: str, url: str, page: int, lp, res, max_pages: int) -> bool:
        """Keep the store's own offers on one verified page, update reconciliation counters, decide stop.
        Returns True when the listing is finished (exhausted or capped)."""
        self._archive("listing", res, f"{category} / {sub} page {page}")
        row = self.ck.listing_row(category, url)
        expected = int(row.get("expected_store_total") or 0)
        streak = int(row.get("zero_streak") or 0)
        need_empty = int(self.crawl.get("store_exhausted_empty_pages", 1))
        accepted, skipped, avail = [], [], []
        self._census([(it.item_id, t) for it in lp.items if it.is_store_item(self.loc.store_id)
                      for t in it.promo_texts], "listing")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        n_avail = n_oos = 0
        for it in lp.items:
            if it.is_store_item(self.loc.store_id):  # reconciliation counts every store offer Walmart counts
                status = it.availability(self.loc.store_id)
                n_oos += status == "out_of_stock"
                n_avail += status != "out_of_stock"
            reason = self._reject_reason(it)
            if reason:
                skipped.append((it.item_id, reason))
                continue
            status = it.availability(self.loc.store_id)
            accepted.append((it.item_id, sub, self._record(it, category, sub)))
            avail.append((it.item_id, status, it.availability_value, "fresh_store_offer", now, it.url))
        self.ck.set_availability(avail)
        streak = streak + 1 if not (n_avail or n_oos) else 0
        row_avail = int(row.get("store_available") or 0) + n_avail
        done_store = expected > 0 and row_avail >= expected and streak >= need_empty
        last_page = page >= lp.max_page or not lp.items
        stop = last_page or done_store
        reason = ("walmart_served_no_more_products" if not lp.items and page < lp.max_page else
                  "walmart_last_page" if last_page else "store_assortment_exhausted" if done_store else "")
        capped = (not stop) and page >= max_pages
        self.ck.listing_progress(category, url, n_avail, n_oos, streak, reason or ("page_window_reached" if capped else ""))
        new = self.ck.commit_page(category, url, page, lp.max_page, accepted, skipped, sub, stop or capped, capped,
                                  reported_total=lp.total_count, page_size=len(lp.items))
        log.info("page", extra={"category": category, "sub_category": sub, "page": page, "max_page": lp.max_page,
                                "items": len(lp.items), "store_offers": len(accepted), "kept_new": new,
                                "expected_store": expected, "store_available_so_far": row_avail,
                                "stop": reason, "total": self.ck.count_items()})
        self._sync_checkpoint()
        return stop or capped

    def _census(self, pairs: list[tuple[str, str]], where: str) -> None:
        """Offer census: every promotion / badge label Walmart displayed on store offers, with counts and examples."""
        if not pairs:
            return
        census = self.ck.get("offer_census", {})
        for item_id, text in pairs:
            e = census.setdefault(text, {"count": 0, "examples": [], "seen_on": []})
            e["count"] += 1
            if len(e["examples"]) < 3 and item_id not in e["examples"]:
                e["examples"].append(item_id)
            if where not in e["seen_on"]:
                e["seen_on"].append(where)
        self.ck.set("offer_census", census)

    def _listing_params(self) -> dict:
        return {k: str(v).replace("{store_id}", self.loc.store_id) for k, v in (self.crawl.get("listing_params") or {}).items()}

    def _reject_reason(self, it: ListingItem) -> str:
        # Scope = the selected store's assortment. Availability never removes a store product.
        if it.is_marketplace:
            return "marketplace_seller"
        if not it.is_store_item(self.loc.store_id):
            return "not_store_assortment_online_only"
        if it.approx_weight or is_approximate_weight(it.title):
            return "approximate_weight"
        return ""

    def _record(self, it: ListingItem, category: str, sub: str) -> dict:
        """Prices, PPM and promotions come ONLY from this store offer on the store-pinned listing."""
        regular, sale = (it.was_price, it.current_price) if it.was_price else (it.current_price, "")
        d = deals.classify(it.promo_texts)
        rec = Record(
            zipcode=self.store.get("zipcode", self.loc.zipcode), store_name=self.store.get("store_name", ""),
            store_location=self.store.get("store_location", ""), store_logo=self.s.get("store_logo_url", ""),
            store_brand="yes" if is_private_label(it.brand, it.title, self.s.private_label_brands) else "no",
            category=category, sub_category=sub, product_title=it.title, weight=extract_weight(it.title),
            regular_price=format_price(regular), sale_price=format_price(sale),
            volume_deals_description=d.volume_description, volume_deals_price=d.volume_price,
            digital_deals_description=d.digital_description, digital_deals_price=d.digital_price,
            image_url=it.image_url, url=it.url, upc=it.upc, ppm=it.ppm, crawl_date=self.crawl_date,
        )
        return rec.to_ordered_dict()

    # ------------------------------------------------------------------ product pages (identity only)
    async def enrich(self):
        """Product pages supply IDENTITY only (UPC, size, brand) - never prices, PPM or promotions, which are bound
        to the store offer on the listing and therefore always fresh. Known identities are reused; new items are
        fetched first, within the per-run product-page budget."""
        sem = asyncio.Semaphore(int(self.s.get("fetch.concurrency", 1)))

        async def one(item_id, rec):
            async with sem:
                await self._enrich_one(item_id, rec)

        todo = self.ck.unenriched()
        if self.crawl.get("reuse_product_details", True) and not self.s.get("_refresh_product_pages"):
            todo = self._reuse_known(todo)
        budget = int(self.crawl.get("max_product_pages_per_run", 0))
        if budget and len(todo) > budget:
            self.ck.defer_items([i for i, _r in todo[budget:]])  # UPC pending: next run fetches it first
            log.info("product_page_budget", extra={"budget": budget, "deferred": len(todo) - budget})
            todo = todo[:budget]
        await asyncio.gather(*(one(i, r) for i, r in todo))

    def _reuse_known(self, todo: list) -> list:
        """UPC / size / brand do not change for a Walmart item id: reuse them from the last published dataset.
        Price-sensitive fields are NOT reused - they were just collected from this run's store offer."""
        prev = {item_id_from_url(r["url"]): r for r in self.storage.get_json(f"{self.loc.key}/latest/records.json") or []}
        rest, n = [], 0
        for item_id, rec in todo:
            p = prev.get(item_id)
            if p and p.get("upc"):
                rec["upc"], rec["weight"] = p["upc"], p.get("weight") or rec["weight"]
                if p.get("store_brand") == "yes":
                    rec["store_brand"] = "yes"
                self.ck.update_item(item_id, rec, enriched=5)
                n += 1
            else:
                rest.append((item_id, rec))
        log.info("product_details_reused", extra={"reused": n, "product_pages_to_fetch": len(rest)})
        return rest

    async def _enrich_one(self, item_id: str, rec: dict):
        try:
            res = await self.fetcher.get(rec["url"])
            self._archive("product", res, rec["product_title"][:80])
            p = parse_product(res.html, res.final_url)
            attempts = [(rec["url"], res.final_url, p.item_id)]
            if p.item_id != item_id:  # Walmart served another variant: retry the canonical item URL once
                res = await self.fetcher.get(f"https://www.walmart.com/ip/{item_id}")
                p = parse_product(res.html, res.final_url)
                attempts.append((f"https://www.walmart.com/ip/{item_id}", res.final_url, p.item_id))
            match = p.item_id == item_id
            ctx = self._product_context_ok(p)
            log.info("product_identity", extra={
                "item_id": item_id, "match": match, "attempts": attempts, "response_item_id": p.item_id,
                "response_name": p.name, "response_upc": p.upc, "selected_pickup_store": p.location.get("pickupStoreId"),
                "output_title": rec["product_title"],
                "decision": "identity_enriched" if match and ctx else "variant_mismatch_kept_listing_data" if not match
                else "store_context_not_confirmed_kept_listing_data"})
            if not match:
                self.ck.event("variant_mismatch", {"item_id": item_id, "attempts": attempts, "response_name": p.name})
                self.ck.update_item(item_id, rec, enriched=3)
                return
            if not ctx:
                self.ck.event("product_context_unconfirmed", {"item_id": item_id, "location": p.location})
                self.ck.update_item(item_id, rec, enriched=2)
                return
        except (FetchError, ShapeError, ChallengeError) as exc:
            self.ck.event("enrich_failed", {"item_id": item_id, "error": str(exc)})
            log.warning("enrich_failed", extra={"item_id": item_id, "error": str(exc)})
            self.ck.update_item(item_id, rec, enriched=2)
            return
        weight = p.size if p.size and not p.size.replace(".", "").isdigit() else (rec["weight"] or
                  (f"{p.size} count" if p.size else ""))
        if is_approximate_weight(weight):
            self.ck.update_item(item_id, None)
            self.ck.event("dropped_approx_weight", {"item_id": item_id, "weight": weight})
            return
        rec["upc"] = rec["upc"] or p.upc  # original UPC preserved, never altered
        rec["weight"] = clean_text(weight)
        if p.brand and rec["store_brand"] == "no":
            rec["store_brand"] = "yes" if is_private_label(p.brand, rec["product_title"], self.s.private_label_brands) else "no"
        self.ck.update_item(item_id, rec, enriched=1)
        self._sync_checkpoint()


def run_location(settings: Settings, location_key: str, **kw) -> dict:
    loc = settings.location(location_key)
    return asyncio.run(Run(settings, loc, **kw).execute())
