"""v1.1.2: enforced TOTAL request caps for the bounded live tests (offline – fixture provider, no network)."""
import asyncio
import json

import pytest
from conftest import FIX, PAGES, ROOT

from mscraper import cli
from mscraper.budget import TotalBudget, parse_spec
from mscraper.fetch import FetchError, FixtureFetcher


def test_total_budget_persists_refuses_and_cannot_be_raised(tmp_path, live):
    b = TotalBudget(tmp_path, "test1", 3, command="x")
    for _ in range(2):
        b.take("u1")
    again = TotalBudget(tmp_path, "test1", 3)            # a new process / resume reads the same file
    assert again.used == 2
    again.take("u2")
    with pytest.raises(FetchError) as e:
        again.take("u3")
    assert e.value.kind == "budget"
    with pytest.raises(ValueError):
        TotalBudget(tmp_path, "test1", 30)               # a cap is never raised under the same name
    lines = (tmp_path / "test1.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["n"] for x in lines] == [1, 2, 3]
    assert parse_spec("test2:300") == ("test2", 300)


def test_retries_and_resumed_processes_count_against_the_same_total(settings, location, tmp_path, live):
    def fetcher():
        f = FixtureFetcher(settings, location, fixtures=dict(PAGES), root=str(FIX))
        f.total_budget = TotalBudget(tmp_path, "test2", 5)
        return f

    f1 = fetcher()
    f1.fail_once = {"query=milk"}                         # 1 failure + 1 retry = 2 counted requests
    asyncio.run(f1.get("https://www.marianos.com/search?query=milk"))
    asyncio.run(f1.get("https://www.marianos.com/search?query=beef"))
    assert f1.total_budget.used == 3
    f2 = fetcher()                                        # "resume": new process, same budget file
    asyncio.run(f2.get("https://www.marianos.com/search?query=beef"))
    asyncio.run(f2.get("https://www.marianos.com/search?query=beef"))
    with pytest.raises(FetchError) as e:
        asyncio.run(f2.get("https://www.marianos.com/search?query=beef"))
    assert e.value.kind == "budget" and f2.total_budget.used == 5


def test_bounded_test1_never_exceeds_19_requests_even_when_repeated(tmp_path, monkeypatch, capsys):
    # every request fails (fixture provider without pages -> HTTP 404), so every step retries up to its own cap –
    # the worst case for request count
    monkeypatch.setenv("MSCRAPER_FETCH_PROVIDER", "fixture")
    monkeypatch.setenv("MSCRAPER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr("mscraper.fetch.Fetcher._pace", lambda self: asyncio.sleep(0))
    monkeypatch.setattr("mscraper.fetch.random.uniform", lambda a, b: 0)
    cfg = str(ROOT / "config" / "settings.yaml")
    import mscraper.fetch as fetch_mod
    orig = fetch_mod.Fetcher.__init__

    def fast_init(self, settings, location):
        orig(self, settings, location)
        self.backoff = 0
    monkeypatch.setattr(fetch_mod.Fetcher, "__init__", fast_init)

    cli.main(["--config", cfg, "bounded-test", "test1"])
    st = json.loads((tmp_path / "state" / "_budgets" / "test1.json").read_text(encoding="utf-8"))
    assert st["total"] == 19 and 0 < st["used"] <= 19
    first = st["used"]
    rc = cli.main(["--config", cfg, "bounded-test", "test1"])     # repeating the test cannot add requests past 19
    st = json.loads((tmp_path / "state" / "_budgets" / "test1.json").read_text(encoding="utf-8"))
    assert st["used"] <= 19 and st["used"] >= first and rc != 0
    ledger = (tmp_path / "state" / "_budgets" / "test1.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(ledger) == st["used"]
    assert {json.loads(x)["store"] for x in ledger} <= {"53100544", "53100502"}


def test_bounded_test_plans_match_the_proposal():
    assert cli.BOUNDED_TESTS["test1"]["total"] == 19
    caps = [int(s[s.index("--max-requests") + 1]) for s in cli.BOUNDED_TESTS["test1"]["steps"]]
    assert sum(caps) == 19
    t2 = cli.BOUNDED_TESTS["test2"]
    assert t2["total"] == 300 and "--no-publish" in t2["steps"][0]


def test_crawl_queue_starts_new_requests_without_waiting_for_slow_ones(settings, location, storage, fetcher, tmp_path):
    """No wave barrier: a request queued by a fast listing starts while a slow listing is still running."""
    from mscraper.runner import Runner

    r = Runner(settings, location, storage, tmp_path / "state", fetcher=fetcher)
    for name in ("slow", "fast"):
        r.ck.add_listing("Meat", name, f"https://x/{name}", name, "", False)
    order = []

    async def fake(l):
        order.append(("start", l["url"]))
        if l["url"].endswith("slow"):
            await asyncio.sleep(0.3)
        elif l["url"].endswith("fast"):
            r.ck.add_listing("Meat", "queued", "https://x/queued", "queued", "", False)
        order.append(("end", l["url"]))
        r.ck.finish_listing(l["category"], l["url"], "done")

    r.crawl_listing = fake
    asyncio.run(r.crawl_pending())
    assert order.index(("start", "https://x/queued")) < order.index(("end", "https://x/slow"))
    assert not r.ck.pending()


def test_crawl_queue_starts_each_request_once_per_session(settings, location, storage, fetcher, tmp_path):
    from mscraper.runner import Runner

    r = Runner(settings, location, storage, tmp_path / "state", fetcher=fetcher)
    r.ck.add_listing("Meat", "stuck", "https://x/stuck", "stuck", "", False)
    calls = []

    async def leaves_pending(l):
        calls.append(l["url"])

    r.crawl_listing = leaves_pending
    asyncio.run(r.crawl_pending())          # returns; the listing stays pending for the next resume
    assert calls == ["https://x/stuck"] and len(r.ck.pending()) == 1
