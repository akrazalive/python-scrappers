"""Loads settings, locations, categories and private-label brands from config files.

Nothing retailer- or location-specific lives in source code; everything here is read
from the config directory so new stores and categories need no code changes.
"""
from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Category:
    name: str
    url: str
    scope: str
    excluded_subcategories: tuple[str, ...]

    @property
    def category_id(self) -> str:
        """Walmart category id path, e.g. '976759' or '5427_486190'."""
        path = self.url.split("?")[0].rstrip("/")
        return path.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class Location:
    key: str
    store_id: str
    zipcode: str
    fulfillment: str = "pickup"
    canary_items: tuple[str, ...] = ()
    enabled: bool = True
    categories: tuple[str, ...] = ()          # optional scope: category names from the CSV (empty = all)
    only_subcategories: tuple[str, ...] = ()  # optional scope: leaf subcategory names (empty = all)
    expected_address: str = ""                # optional: store page address must contain this text
    crawl: tuple = ()                         # optional per-location overrides of settings "crawl.*" (key, value) pairs


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

    def categories_for(self, loc: "Location") -> list[Category]:
        if not loc.categories:
            return list(self.categories)
        wanted = {c.lower() for c in loc.categories}
        cats = [c for c in self.categories if c.name.lower() in wanted]
        missing = wanted - {c.name.lower() for c in cats}
        if missing:
            raise KeyError(f"location '{loc.key}' references unknown categories: {sorted(missing)}")
        return cats

    def location(self, key: str) -> Location:
        for loc in self.locations:
            if loc.key == key:
                return loc
        raise KeyError(f"Unknown location '{key}'. Configured: {[l.key for l in self.locations]}")


_EXCLUDE_RE = re.compile(r"'([^']+)'")


def _load_categories(path: Path) -> list[Category]:
    cats = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if (row.get("Retailer") or "").strip().lower() != "walmart":
                continue
            notes = row.get("Notes") or ""
            excluded = tuple(m.strip() for m in _EXCLUDE_RE.findall(notes)) if "exclude" in notes.lower() else ()
            cats.append(
                Category(
                    name=row["Category (Auto)"].strip(),
                    url=row["URL"].strip(),
                    scope=(row.get("Scope") or "").strip(),
                    excluded_subcategories=excluded,
                )
            )
    return cats


def _load_locations(path: Path) -> list[Location]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for item in data.get("locations", []):
        out.append(
            Location(
                key=str(item["key"]),
                store_id=str(item["store_id"]),
                zipcode=str(item.get("zipcode", "")),
                fulfillment=str(item.get("fulfillment", "pickup")),
                canary_items=tuple(str(x) for x in item.get("canary_items") or ()),
                enabled=bool(item.get("enabled", True)),
                categories=tuple(str(x) for x in item.get("categories") or ()),
                only_subcategories=tuple(str(x) for x in item.get("only_subcategories") or ()),
                expected_address=str(item.get("expected_address", "")),
                crawl=tuple((item.get("crawl") or {}).items()),
            )
        )
    return out


def _load_brands(path: Path) -> tuple[str, ...]:
    if not path.exists():
        return ()
    lines = (l.strip() for l in path.read_text(encoding="utf-8").splitlines())
    return tuple(sorted({l.lower() for l in lines if l and not l.startswith("#")}))


def load_settings(config_path: str | os.PathLike | None = None) -> Settings:
    cfg_path = Path(config_path) if config_path else ROOT / "config" / "settings.yaml"
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    base = cfg_path.parent.parent if cfg_path.parent.name == "config" else ROOT

    def rel(key: str) -> Path:
        p = Path(raw[key])
        return p if p.is_absolute() else base / p

    s = Settings(raw=raw)
    s.categories = _load_categories(rel("categories_file"))
    s.locations = _load_locations(rel("locations_file"))
    s.private_label_brands = _load_brands(rel("private_label_file"))
    s.raw["_base_dir"] = str(base)
    return s
