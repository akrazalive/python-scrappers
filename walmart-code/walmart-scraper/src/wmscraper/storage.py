"""Output storage with safe publication.

Layout (same on local disk and in Azure Blob Storage):

  <location>/runs/<run_id>/records.json     every run, valid or not (for audit)
  <location>/runs/<run_id>/report.json
  <location>/runs/<run_id>/run.log
  <location>/latest/records.json             ONLY replaced after a run passes validation
  <location>/latest/report.json
  <location>/latest/manifest.json            run id, counts, checksum, published_at

Publication writes the new files under temporary names first and swaps them in last,
so readers never see a half-written latest/ and a failed run can never replace it.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


class Storage:
    def put_bytes(self, key: str, data: bytes) -> None: ...
    def get_bytes(self, key: str) -> bytes | None: ...
    def copy(self, src: str, dst: str) -> None: ...
    def local_path(self, key: str) -> Path | None:
        return None

    def put_json(self, key: str, obj) -> None:
        self.put_bytes(key, json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"))

    def get_json(self, key: str, default=None):
        raw = self.get_bytes(key)
        return json.loads(raw) if raw else default

    # ------------------------------------------------------------------ publication
    def publish(self, location: str, run_id: str, records: list[dict], report: dict) -> dict:
        body = json.dumps(records, ensure_ascii=False, indent=2).encode("utf-8")
        manifest = {
            "run_id": run_id,
            "location": location,
            "record_count": len(records),
            "sha256": hashlib.sha256(body).hexdigest(),
            "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        base = f"{location}/latest"
        # 1) stage
        self.put_bytes(f"{base}/.staging-records.json", body)
        self.put_json(f"{base}/.staging-report.json", report)
        # 2) previous good copy kept for one-step rollback
        if self.get_bytes(f"{base}/records.json"):
            self.copy(f"{base}/records.json", f"{base}/previous-records.json")
            self.copy(f"{base}/manifest.json", f"{base}/previous-manifest.json")
        # 3) swap in; manifest written last = commit point
        self.copy(f"{base}/.staging-records.json", f"{base}/records.json")
        self.copy(f"{base}/.staging-report.json", f"{base}/report.json")
        self.put_json(f"{base}/manifest.json", manifest)
        return manifest

    def last_good(self, location: str) -> dict | None:
        return self.get_json(f"{location}/latest/manifest.json")


class LocalStorage(Storage):
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root)

    def _p(self, key: str) -> Path:
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def put_bytes(self, key, data):
        p = self._p(key)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)  # atomic on the same volume

    def get_bytes(self, key):
        p = self.root / key
        return p.read_bytes() if p.exists() else None

    def copy(self, src, dst):
        d = self._p(dst)
        tmp = d.with_name(d.name + ".tmp")
        shutil.copyfile(self.root / src, tmp)
        os.replace(tmp, d)

    def local_path(self, key):
        return self._p(key)


class BlobStorage(Storage):
    def __init__(self, container: str):
        from azure.storage.blob import BlobServiceClient

        conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if conn:
            svc = BlobServiceClient.from_connection_string(conn)
        else:
            from azure.identity import DefaultAzureCredential

            url = os.environ["AZURE_STORAGE_ACCOUNT_URL"]
            svc = BlobServiceClient(account_url=url, credential=DefaultAzureCredential())
        self.cc = svc.get_container_client(container)
        if not self.cc.exists():
            self.cc.create_container()

    def put_bytes(self, key, data):
        self.cc.upload_blob(key, data, overwrite=True)

    def get_bytes(self, key):
        b = self.cc.get_blob_client(key)
        return b.download_blob().readall() if b.exists() else None

    def copy(self, src, dst):
        self.put_bytes(dst, self.get_bytes(src) or b"")


def build_storage(settings) -> Storage:
    backend = os.getenv("WMSCRAPER_OUTPUT_BACKEND") or settings.get("output.backend", "local")
    if backend == "azure_blob":
        return BlobStorage(settings.get("output.blob_container", "walmart-scraper"))
    root = Path(settings.get("output.local_dir", "output"))
    if not root.is_absolute():
        root = Path(settings.get("_base_dir")) / root
    return LocalStorage(root)
