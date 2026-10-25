"""Loads settings, locations, categories and store brands from the config directory.

Nothing retailer- or location-specific lives in source code: new stores and categories
are configuration changes only.
"""
from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Category:
    name: str
    url: str
    scope: str

    @property
    def kind(self) -> str:
        """department (/d/...), list (/pl/<slug>/<taxonomy>), coupons (/savings/cl/coupons/)"""
        path = urlparse(self.url).path
        if path.startswith("/d/"):
            return "department"
        if path.startswith("/pl/"):
            return "list"
        if "coupon" in path:
            return "coupons"
        return "other"

    @property
    def taxonomy_id(self) -> str:
        """Taxonomy id of a /pl/<slug>/<id> URL, e.g. '26003' for batteries."""
        m = re.match(r"/pl/[^/]+/(\d+)", urlparse(self.url).path)
        return m.group(1) if m else ""

    @property
    def slug(self) -> str:
        parts = [p for p in urlparse(self.url).path.split("/") if p]
        return parts[1] if len(parts) > 1 else ""


@dataclass(frozen=True)
class Location:
    key: str
    store_id: str
    zipcode: str = ""
    expected_address: str = ""
    canary_query: str = ""
    canary_upcs: tuple[str, ...] = ()
    enabled: bool = True
    categories: tuple[str, ...] = ()
    limit_per_category: int = 0


@dataclass
class Settings:
    raw: dict
    categories: list[Category] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)
    private_label_brands: tuple[str, ...] = ()

    def get(self, dotted: str, default=None):
        node = self.raw
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def categories_for(self, loc: Location, only: list[str] | None = None) -> list[Category]:
        wanted = [c.lower() for c in (only or loc.categories)]
        if not wanted:
            return list(self.categories)
        cats = [c for c in self.categories if c.name.lower() in wanted]
        missing = set(wanted) - {c.name.lower() for c in cats}
        if missing:
            raise KeyError(f"unknown categories {sorted(missing)}; configured: {[c.name for c in self.categories]}")
        return cats

    def location(self, key: str) -> Location:
        for loc in self.locations:
            if loc.key == key:
                return loc
        raise KeyError(f"Unknown location '{key}'. Configured: {[l.key for l in self.locations]}")


def _load_categories(path: Path, retailer: str) -> list[Category]:
    cats = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("Retailer") or "").strip().lower().replace("’", "'")
            if not name.startswith(retailer[:6]):  # "mariano's"
                continue
            cats.append(Category(name=row["Category (Auto)"].strip(), url=row["URL"].strip(),
                                 scope=(row.get("Scope") or "").strip()))
    return cats


def _load_locations(path: Path) -> list[Location]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for item in data.get("locations", []):
        canary = item.get("canary") or {}
        out.append(Location(
            key=str(item["key"]), store_id=str(item["store_id"]), zipcode=str(item.get("zipcode") or ""),
            expected_address=str(item.get("expected_address") or ""),
            canary_query=str(canary.get("query") or ""), canary_upcs=tuple(str(x) for x in canary.get("upcs") or ()),
            enabled=bool(item.get("enabled", True)), categories=tuple(str(x) for x in item.get("categories") or ()),
            limit_per_category=int(item.get("limit_per_category") or 0)))
    return out


def _load_brands(path: Path) -> tuple[str, ...]:
    if not path.exists():
        return ()
    lines = (l.strip() for l in path.read_text(encoding="utf-8").splitlines())
    return tuple(sorted({l.lower().replace("’", "'") for l in lines if l and not l.startswith("#")}))


def load_settings(config_path: str | os.PathLike | None = None) -> Settings:
    cfg_path = Path(config_path) if config_path else ROOT / "config" / "settings.yaml"
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    base = cfg_path.parent.parent if cfg_path.parent.name == "config" else ROOT

    def rel(key: str) -> Path:
        p = Path(raw[key])
        return p if p.is_absolute() else base / p

    s = Settings(raw=raw)
    s.categories = _load_categories(rel("categories_file"), raw.get("retailer", "marianos"))
    s.locations = _load_locations(rel("locations_file"))
    s.private_label_brands = _load_brands(rel("private_label_file"))
    s.raw["_base_dir"] = str(base)
    return s
