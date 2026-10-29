import asyncio
import json

import pytest

from conftest import STORE
from wmscraper.fetch import FetchError, FetchResult, provider_error
from wmscraper.fetch.base import Fetcher
from wmscraper.fetch.base import FixtureFetcher
from wmscraper import lock
from wmscraper.cli import main
from wmscraper.config import load_settings
from wmscraper.runner import Run


def test_lease_lost_after_pacing_does_not_send(monkeypatch, site):
    settings = __import__("wmscraper.config", fromlist=["load_settings"]).load_settings(str(site))
    location = settings.location("test-store")
    calls = []

    class Fake(Fetcher):
        async def _fetch_once(self, url):
            calls.append(url)
            return FetchResult(url, url, 200, "x" * 3000, 0)

    checks = {"n": 0}
    def check():
        checks["n"] += 1
        if checks["n"] == 2:
            raise lock.LockLost("lease lost")
    monkeypatch.setattr(lock, "check_active", check)
    fetcher = Fake(settings, location)
    monkeypatch.setattr(fetcher, "_pace", lambda: asyncio.sleep(0))
    with pytest.raises(FetchError) as exc:
        asyncio.run(fetcher.get(f"https://www.walmart.com/store/{STORE}"))
    assert exc.value.kind == "lock"
    assert calls == []


def test_provider_and_target_statuses_keep_distinct_kinds():
    assert provider_error(401, "").kind == "auth"
    assert FetchError("target refused", "refused").kind == "refused"
    assert provider_error(503, "").kind == "http"


def test_target_refusal_is_archived_and_verify_store_fails(site, monkeypatch):
    calls = []

    async def refused(self, url):
        calls.append(url)
        return FetchResult(url, url, 403, "<html>denied</html>", 0.01)

    monkeypatch.setattr(FixtureFetcher, "_fetch_once", refused)
    rc = main(["--config", str(site), "verify-store", "--location", "test-store", "--max-requests", "1"])
    assert rc != 0 and len(calls) == 1
    calls.clear()
    run = Run(load_settings(str(site)), load_settings(str(site)).location("test-store"), run_id="refusal-test")
    try:
        with pytest.raises(FetchError):
            asyncio.run(run.fetcher.get("https://www.walmart.com/store/1234"))
        index_path = run.storage.local_path(f"{run.prefix}/raw/index.json")
        index = json.loads(index_path.read_text(encoding="utf-8"))
    finally:
        run.ck.close()
    assert index[0]["kind"] == "refused"
    assert (index_path.parent / index[0]["file"]).exists()
