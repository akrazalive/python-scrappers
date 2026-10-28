"""Parsing of Walmart pages via the embedded __NEXT_DATA__ JSON.

Walmart renders listing, product and store pages with Next.js and embeds the full page
state as JSON. Reading that JSON is far more reliable than CSS selectors. Every parser
validates the response shape and raises ShapeError instead of silently returning nothing,
so a changed or blocked page can never be mistaken for an empty category.
"""
from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterator
from urllib.parse import urljoin

from .text import clean_text, format_price

BASE = "https://www.walmart.com"
WALMART_SELLER_IDS = {"F55CDC31AB754BB68FE0B39041159D63"}
WALMART_SELLER_NAMES = {"walmart.com", "walmart", "walmart inc", "walmart inc."}

_NEXT_RE = re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
def product_url(url: str) -> str:
    """Clean product URL: Walmart appends listing filters / tracking (?filters=...&classType=...) to canonical links."""
    return (url or "").split("#")[0].split("?")[0] if "/ip/" in (url or "") else (url or "")


_CHALLENGE_MARKERS = ("Robot or human", "px-captcha", "/blocked?url=", "Access Denied", "verify you are a human")
_STORE_KEYS = {"storeId", "assortmentStoreId", "preferredStoreId", "pickupStoreId", "intentStoreId", "accessPointStoreId"}


class ShapeError(Exception):
    """The response did not have the expected structure (layout change, partial page, etc.)."""


class ChallengeError(Exception):
    """The response is a bot challenge / block page."""


# ----------------------------------------------------------------------------- helpers
def detect_challenge(html: str, final_url: str = "") -> bool:
    head = html[:20000]
    return "/blocked" in final_url or any(m in head for m in _CHALLENGE_MARKERS)


def next_data(html: str, final_url: str = "") -> dict:
    if detect_challenge(html, final_url):
        raise ChallengeError(f"bot challenge served for {final_url or 'page'}")
    m = _NEXT_RE.search(html)
    if not m:
        raise ShapeError("__NEXT_DATA__ not found")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise ShapeError(f"__NEXT_DATA__ is not valid JSON: {exc}") from exc


def walk(node: Any) -> Iterator[Any]:
    """Breadth-first walk that preserves document order."""
    queue = deque([node])
    while queue:
        cur = queue.popleft()
        yield cur
        if isinstance(cur, dict):
            queue.extend(cur.values())
        elif isinstance(cur, list):
            queue.extend(cur)


def dig(node: Any, *path, default=None):
    for p in path:
        if isinstance(node, dict) and p in node:
            node = node[p]
        elif isinstance(node, list) and isinstance(p, int) and -len(node) <= p < len(node):
            node = node[p]
        else:
            return default
    return node


def _price_string(v) -> str:
    if isinstance(v, dict):
        return v.get("priceString") or v.get("priceDisplay") or (str(v["price"]) if v.get("price") is not None else "")
    return v or ""


def store_ids_in(data: Any) -> set[str]:
    """All store identifiers present in the page's location/fulfillment context."""
    found: set[str] = set()
    for node in walk(data):
        if isinstance(node, dict):
            for k in _STORE_KEYS:
                v = node.get(k)
                if isinstance(v, (str, int)) and str(v).isdigit():
                    found.add(str(v))
            ids = node.get("storeIds")
            if isinstance(ids, list):
                found.update(str(x) for x in ids if str(x).isdigit())
    return found


_CONTEXT_KEYS = _STORE_KEYS | {"storeIds", "intent", "fulfillmentIntent", "postalCode", "zipCode", "fulfillment",
                               "fulfillmentType", "accessPointId", "storeName", "displayName"}


def store_context_excerpt(data: Any, limit: int = 40) -> list[dict]:
    """JSON paths + values of every store / pickup / postal-code field in a page (evidence of context)."""
    out: list[dict] = []
    queue = deque([("$", data)])
    while queue and len(out) < limit:
        path, node = queue.popleft()
        if isinstance(node, dict):
            for k, v in node.items():
                p = f"{path}.{k}"
                if k in _CONTEXT_KEYS and isinstance(v, (str, int, list)) and v not in ("", [], None):
                    out.append({"path": p, "value": v if not isinstance(v, list) else v[:10]})
                if isinstance(v, (dict, list)):
                    queue.append((p, v))
        elif isinstance(node, list):
            for i, v in enumerate(node[:200]):
                if isinstance(v, (dict, list)):
                    queue.append((f"{path}[{i}]", v))
    return out


def page_location(data: Any) -> dict:
    """The page's SELECTED location (explicit path, not 'a store id anywhere in the response')."""
    initial = dig(data, "props", "pageProps", "initialData") or {}
    for path in (("pageMetadata", "location"), ("contentLayout", "pageMetadata", "location"),
                 ("searchResult", "pageMetadata", "location"), ("data", "contentLayout", "pageMetadata", "location")):
        loc = dig(initial, *path)
        if isinstance(loc, dict) and loc.get("storeId"):
            return {"storeId": str(loc.get("storeId")), "intent": clean_text(loc.get("intent")),
                    "postalCode": clean_text(loc.get("postalCode")), "path": "initialData." + ".".join(path)}
    return {}


# ----------------------------------------------------------------------------- listing
@dataclass
class ListingItem:
    item_id: str
    title: str
    url: str
    image_url: str
    brand: str
    current_price: str
    was_price: str
    ppm: str
    seller_name: str
    seller_id: str
    sponsored: bool
    fulfillment_texts: list[str]
    promo_texts: list[str]
    upc: str = ""
    raw: dict = field(default_factory=dict, repr=False)
    pickup_store_ids: set = field(default_factory=set)   # stores offering PICKUP / IN_STORE for this item
    secondary_stack: bool = False                         # Walmart's "not at this store, ships instead" group
    approx_weight: bool = False                           # sold by average / variable weight
    fulfillment_type: str = ""                            # STORE | FC | MARKETPLACE
    availability_value: str = ""                          # Walmart availabilityStatusV2.value, e.g. OUT_OF_STOCK
    store_ids_any: set = field(default_factory=set)       # every store id in the item's fulfillment summary

    def availability(self, store_id: str) -> str:
        """Availability at the configured store, for the availability log (never used to drop a product)."""
        if self.is_store_item(store_id):
            if self.availability_value and self.availability_value != "IN_STOCK":
                return "out_of_stock"
            return "available" if store_id in self.pickup_store_ids else "unavailable_for_pickup"
        return "shipping_only_not_sold_at_store"

    def is_store_item(self, store_id: str) -> bool:
        """The selected store's own offer (store assortment, store price), checked explicitly on THIS item:
        Walmart fulfillmentType STORE and, when the item carries a fulfillment summary, an entry for this store.
        A temporarily out-of-stock store item has no summary but stays a store offer."""
        if self.fulfillment_type.upper() != "STORE" or self.is_marketplace:
            return False
        if self.store_ids_any:
            return store_id in self.store_ids_any
        return True

    @property
    def is_marketplace(self) -> bool:
        if self.seller_id and self.seller_id.upper() in WALMART_SELLER_IDS:
            return False
        if self.seller_name and self.seller_name.lower() in WALMART_SELLER_NAMES:
            return False
        return bool(self.seller_id or self.seller_name)

    @property
    def has_local_fulfillment(self) -> bool:
        if self.secondary_stack:
            return False
        if self.pickup_store_ids:
            return True
        text = " ".join(self.fulfillment_texts).lower()
        return any(k in text for k in ("pickup", "in-store", "in store", "aisle"))

    def local_at(self, store_id: str) -> bool:
        """Item offered for pickup / in-store at the given store (per-item store verification)."""
        if self.pickup_store_ids:
            return store_id in self.pickup_store_ids and not self.secondary_stack
        return self.has_local_fulfillment


@dataclass
class ListingPage:
    items: list[ListingItem]
    max_page: int
    total_count: int
    store_ids: set[str]
    subcategory_links: list[tuple[str, str]]  # (name, absolute url)
    children: list[tuple[str, str]] = field(default_factory=list)  # Departments facet: (name, category id)
    location: dict = field(default_factory=dict)                    # the page's selected store context


def _texts(node: Any) -> list[str]:
    out = []
    for n in walk(node):
        if isinstance(n, dict):
            for key in ("text", "slaText", "label", "message", "displayText", "description"):
                v = n.get(key)
                if isinstance(v, str) and v.strip():
                    out.append(clean_text(v))
            content = n.get("content")
            if isinstance(content, list):  # Walmart badge members: [{type: TEXT, value: ...}]
                t = " ".join(c.get("value") or "" for c in content if isinstance(c, dict) and c.get("type") == "TEXT")
                if t.strip():
                    out.append(clean_text(t))
    return out


def _price_lines(d: dict) -> dict[str, str]:
    """Walmart priceInfo.priceDetails.priceLines -> CURRENT_PRICE, DISCOUNTED_PRICE, WAS_PRICE, UNIT_PRICE."""
    out: dict[str, str] = {}
    for pl in dig(d, "priceInfo", "priceDetails", "priceLines") or []:
        if not isinstance(pl, dict):
            continue
        vals = {v.get("key"): v.get("value") for v in pl.get("values") or [] if isinstance(v, dict)}
        lt = pl.get("lineType")
        if lt in ("CURRENT_PRICE", "DISCOUNTED_PRICE") and vals.get("PRICE"):
            out[lt] = str(vals["PRICE"])
        elif lt == "COMPARISON" and vals.get("WAS_PRICE"):
            out["WAS_PRICE"] = str(vals["WAS_PRICE"])
        elif lt == "UNIT_PRICE" and vals.get("UNIT_PRICE"):
            out["UNIT_PRICE"] = str(vals["UNIT_PRICE"])
    return out


def _item_from(d: dict) -> ListingItem | None:
    item_id = str(d.get("usItemId") or d.get("id") or "")
    title = clean_text(d.get("name"))
    if not item_id or not title:
        return None
    pi = d.get("priceInfo") or {}
    lines = _price_lines(d)
    current = (lines.get("DISCOUNTED_PRICE") or lines.get("CURRENT_PRICE")
               or _price_string(pi.get("linePrice") or pi.get("currentPrice") or pi.get("itemPrice") or d.get("price")))
    was = lines.get("WAS_PRICE") or _price_string(pi.get("wasPrice"))
    ppm = lines.get("UNIT_PRICE") or _price_string(pi.get("unitPrice"))
    image = dig(d, "imageInfo", "thumbnailUrl") or d.get("image") or ""
    if isinstance(image, dict):
        image = image.get("url", "")
    promo = []
    promo += _texts(d.get("badges") or {})
    for key in ("promoDiscount", "promoData", "groupMetaData", "eaPricingText", "volumePricing", "offerText", "couponInfo"):
        if d.get(key):
            promo += _texts(d.get(key)) if not isinstance(d[key], str) else [clean_text(d[key])]
    fulfil = _texts(d.get("fulfillmentBadgeGroups") or []) + _texts(d.get("fulfillmentBadges") or [])
    if isinstance(d.get("fulfillmentBadge"), str):
        fulfil.append(clean_text(d["fulfillmentBadge"]))
    pickup_stores = set()
    for fs in d.get("fulfillmentSummary") or []:
        if not isinstance(fs, dict):
            continue
        kind = str(fs.get("fulfillment", "")).upper()
        if kind:
            fulfil.append(kind)
        if kind in ("PICKUP", "IN_STORE", "INSTORE") and fs.get("storeId"):
            pickup_stores.add(str(fs["storeId"]))
    badge_texts = _texts((d.get("badges") or {}).get("groupsV2") or [])
    fulfil += [t for t in badge_texts if any(k in t.lower() for k in ("pickup", "shipping", "delivery", "in store", "in-store"))]
    if isinstance(d.get("discountsRaw"), dict):
        promo += _texts(d["discountsRaw"].get("discountMetaData") or [])
    return ListingItem(
        item_id=item_id,
        title=title,
        url=product_url(urljoin(BASE, d.get("canonicalUrl") or d.get("productPageUrl") or f"/ip/{item_id}")),
        image_url=str(image or ""),
        brand=clean_text(d.get("brand")),
        current_price=current,
        was_price=was,
        ppm=clean_text(ppm),
        seller_name=clean_text(d.get("sellerName")),
        seller_id=clean_text(d.get("sellerId")),
        sponsored=bool(d.get("isSponsoredFlag") or d.get("sponsoredProduct") or d.get("isSponsored")),
        fulfillment_texts=fulfil,
        promo_texts=promo,
        upc=clean_text(d.get("upc")),
        raw=d,
        pickup_store_ids=pickup_stores,
        approx_weight=d.get("averageWeight") not in (None, "", 0) or str(d.get("salesUnit", "")).upper() == "WEIGHT",
        fulfillment_type=clean_text(d.get("fulfillmentType")),
        availability_value=clean_text((d.get("availabilityStatusV2") or {}).get("value") or d.get("availabilityStatus")),
        store_ids_any={str(fs["storeId"]) for fs in d.get("fulfillmentSummary") or []
                       if isinstance(fs, dict) and fs.get("storeId") and str(fs["storeId"]) != "0"},
    )


def parse_listing(html: str, final_url: str = "") -> ListingPage:
    data = next_data(html, final_url)
    initial = dig(data, "props", "pageProps", "initialData") or {}
    sr = initial.get("searchResult") or dig(initial, "contentLayout", "searchResult")
    if not isinstance(sr, dict):
        raise ShapeError("searchResult missing from listing page")
    stacks = sr.get("itemStacks")
    if not isinstance(stacks, list):
        raise ShapeError("itemStacks missing from searchResult")
    items = []
    for stack in stacks:
        secondary = _is_secondary_stack(stack)
        for raw in stack.get("items") or []:
            if isinstance(raw, dict) and raw.get("__typename", "Product") == "Product":
                it = _item_from(raw)
                if it:
                    it.secondary_stack = secondary
                    items.append(it)
    pag = sr.get("paginationV2") or sr.get("pagination") or {}
    max_page = int(pag.get("maxPage") or pag.get("totalPages") or 1)
    total = int(sr.get("aggregatedCount") or sr.get("count") or len(items))
    return ListingPage(items=items, max_page=max_page, total_count=total,
                       store_ids=store_ids_in(data), subcategory_links=discover_links(data, html),
                       children=department_children(data), location=page_location(data))


def _is_secondary_stack(stack: dict) -> bool:
    """Walmart appends a secondary stack (sub_type puShipFul: not available at this store, ships instead)."""
    meta = stack.get("meta") or {}
    if str(meta.get("fulfillmentIntent", "")).lower() == "shipping":
        return True
    try:
        interp = (json.loads(meta.get("beacon") or "{}").get("interpretations") or [{}])[0]
    except (ValueError, TypeError, AttributeError):
        return False
    return interp.get("type") == "secondary_stack"


def department_children(data: Any) -> list[tuple[str, str]]:
    """(name, category id) pairs from the listing's Departments navigation facet."""
    out, seen = [], set()
    for n in walk(data):
        if isinstance(n, dict) and n.get("name") == "Departments" and isinstance(n.get("values"), list):
            for v in n["values"]:
                if isinstance(v, dict) and v.get("id") and v.get("name") and v["id"] not in seen:
                    seen.add(v["id"])
                    out.append((clean_text(v["name"]), str(v["id"])))
    return out


# ----------------------------------------------------------------------------- navigation
_BROWSE_HREF = re.compile(r'href="(/browse/[^"?#]+/(\d+(?:_\d+)+))[^"]*"[^>]*>(.*?)</a>', re.S)


def discover_links(data: Any, html: str = "") -> list[tuple[str, str]]:
    """Collect (name, url) pairs for /browse/ category links on a category or listing page."""
    seen, out = set(), []
    for node in walk(data):
        if not isinstance(node, dict):
            continue
        url = node.get("url")
        if not isinstance(url, str) and isinstance(node.get("clickThrough"), dict):
            url = node["clickThrough"].get("value")
        name =node.get("name") or node.get("title") or node.get("text") or node.get("displayName")
        if isinstance(url, str) and "/browse/" in url and isinstance(name, str):
            path = url.split("?")[0]
            if path not in seen:
                seen.add(path)
                out.append((clean_text(name), urljoin(BASE, path)))
    for href, _id, label in _BROWSE_HREF.findall(html or ""):
        if href not in seen:
            seen.add(href)
            out.append((clean_text(re.sub("<[^>]+>", " ", label)), urljoin(BASE, href)))
    return out


def category_id_of(url: str) -> str:
    return url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]


def children_of(links: list[tuple[str, str]], parent_id: str) -> list[tuple[str, str]]:
    """Direct and indirect child categories: Walmart ids are hierarchical ('976759_9176907')."""
    out = []
    for name, url in links:
        cid = category_id_of(url)
        if cid.startswith(parent_id + "_") and name:
            out.append((name, url))
    return out


# ----------------------------------------------------------------------------- product
@dataclass
class ProductDetail:
    item_id: str
    name: str
    upc: str
    brand: str
    size: str
    current_price: str
    was_price: str
    ppm: str
    seller_name: str
    seller_id: str
    store_ids: set[str]
    fulfillment_texts: list[str]
    promo_texts: list[str]
    image_url: str
    location: dict = field(default_factory=dict)   # product's selected pickup location (explicit)
    fulfillment_type: str = ""
    fulfillment_options: list = field(default_factory=list)   # [(fulfillment, storeId)] from fulfillmentSummary
    price_value: float | None = None                            # priceInfo.currentPrice.price (number)
    availability: str = ""


def parse_product(html: str, final_url: str = "") -> ProductDetail:
    data = next_data(html, final_url)
    product = dig(data, "props", "pageProps", "initialData", "data", "product")
    if not isinstance(product, dict) or not product.get("usItemId"):
        raise ShapeError("product object missing from product page")
    pi = product.get("priceInfo") or {}
    specs = dig(data, "props", "pageProps", "initialData", "data", "idml", "specifications") or []
    size = ""
    ranked = {"net content": 0, "net weight": 1, "size": 2, "capacity": 3, "count per pack": 4, "count": 5}
    best = 99
    for spec in specs if isinstance(specs, list) else []:
        name = clean_text(spec.get("name")).lower() if isinstance(spec, dict) else ""
        rank = 0 if "net content" in name else ranked.get(name, 99)
        if rank < best and clean_text(spec.get("value")):
            best, size = rank, clean_text(spec.get("value"))
    images = dig(product, "imageInfo", "allImages") or []
    image = (images[0].get("url") if images and isinstance(images[0], dict) else "") or dig(product, "imageInfo", "thumbnailUrl") or ""
    fulfil = _texts(product.get("fulfillmentOptions") or []) + _texts(product.get("fulfillmentSummary") or [])
    for opt in product.get("fulfillmentSummary") or []:
        if isinstance(opt, dict) and opt.get("fulfillment"):
            fulfil.append(str(opt["fulfillment"]))
    promo = (_texts(product.get("badges") or {}) + _texts(product.get("promoDiscount") or {})
             + _texts(product.get("offerPromotions") or []) + _texts(product.get("discounts") or {}))
    if isinstance(product.get("topPromoText"), str):
        promo.append(clean_text(product["topPromoText"]))
    return ProductDetail(
        item_id=str(product.get("usItemId")),
        name=clean_text(product.get("name")),
        upc=clean_text(product.get("upc")),
        brand=clean_text(product.get("brand")),
        size=size,
        current_price=_price_string(pi.get("currentPrice")),
        was_price=_price_string(pi.get("wasPrice")),
        ppm=clean_text(_price_string(pi.get("unitPrice"))),
        seller_name=clean_text(product.get("sellerName")),
        seller_id=clean_text(product.get("sellerId")),
        store_ids=store_ids_in(data),
        fulfillment_texts=fulfil,
        promo_texts=promo,
        image_url=str(image),
        location={"storeIds": [str(x) for x in dig(product, "location", "storeIds") or []],
                  "pickupStoreId": str(dig(product, "location", "pickupLocation", "storeId") or ""),
                  "intent": clean_text(dig(product, "location", "intent")),
                  "postalCode": clean_text(dig(product, "location", "postalCode"))},
        fulfillment_type=clean_text(product.get("fulfillmentType")),
        fulfillment_options=[(clean_text(o.get("fulfillment")), str(o.get("storeId") or ""))
                             for o in product.get("fulfillmentSummary") or [] if isinstance(o, dict)],
        price_value=(lambda v: float(v) if isinstance(v, (int, float)) else None)((pi.get("currentPrice") or {}).get("price")),
        availability=clean_text(product.get("availabilityStatus")),
    )


# ----------------------------------------------------------------------------- store
@dataclass
class StoreInfo:
    store_id: str
    name: str
    address: str
    zipcode: str


def parse_store(html: str, store_id: str, final_url: str = "") -> StoreInfo:
    data = next_data(html, final_url)
    best = None
    for node in walk(data):
        if isinstance(node, dict) and str(node.get("id") or node.get("storeId") or "") == str(store_id) and isinstance(node.get("address"), dict):
            best = node
            break
    if not best:
        raise ShapeError(f"store {store_id} details not found on store page")
    a = best["address"]
    street = clean_text(a.get("addressLineOne") or a.get("streetAddress") or a.get("address1"))
    city, state = clean_text(a.get("city")), clean_text(a.get("state"))
    postal = clean_text(a.get("postalCode") or a.get("zip"))[:5]
    store_type = best.get("storeType") if isinstance(best.get("storeType"), dict) else {}
    name = clean_text(best.get("displayName") or best.get("name") or store_type.get("name"))
    address = ", ".join(x for x in (street, city, f"{state} {postal}".strip()) if x)
    return StoreInfo(store_id=str(store_id), name=name or "Walmart", address=address, zipcode=postal)


def to_price(value: str) -> str:
    return format_price(value)
