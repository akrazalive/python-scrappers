"""Parsing of Mariano's pages.

Mariano's (Kroger platform) server-renders every page with its full application state in
`window.__INITIAL_STATE__ = JSON.parse('...')`. Products, store prices, price-per-measure,
offers, UPCs and the selected store are read from that state – not from fragile CSS.
"""
from __future__ import annotations

import html as htmllib
import json
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlparse

from . import deals
from .text import clean_text, format_price, is_approximate, is_store_brand


class PageError(Exception):
    """A response that is not a usable Mariano's page (challenge, block, malformed, server-side failure)."""

    def __init__(self, message: str, kind: str = "malformed"):
        super().__init__(message)
        self.kind = kind  # challenge | malformed | upstream


_SIMPLE = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "0": "\0"}
_ESC_RE = re.compile(r"\\(?:u([0-9a-fA-F]{4})|x([0-9a-fA-F]{2})|(.))", re.S)
_CHALLENGE_RE = re.compile(r"Access Denied|Reference #\d|/_Incapsula_|captcha|px-captcha|Pardon Our Interruption|"
                           r"Request unsuccessful|errors\.edgesuite\.net", re.I)


def _js_unescape(m: re.Match) -> str:
    if m.group(1):
        return chr(int(m.group(1), 16))
    if m.group(2):
        return chr(int(m.group(2), 16))
    return _SIMPLE.get(m.group(3), m.group(3))


def extract_state(html: str) -> dict:
    if _CHALLENGE_RE.search(html[:20000]) and "__INITIAL_STATE__" not in html:
        raise PageError("bot challenge / access denied page", "challenge")
    i = html.find("__INITIAL_STATE__")
    if i < 0:
        raise PageError("no application state in page (blocked or malformed response)", "malformed")
    start = html.find("JSON.parse('", i)
    if start < 0:
        raise PageError("application state not in expected format", "malformed")
    start += len("JSON.parse('")
    end = start
    while True:
        end = html.find("')", end)
        if end < 0:
            raise PageError("unterminated application state", "malformed")
        if html[end - 1] != "\\":
            break
        end += 1
    text = _ESC_RE.sub(_js_unescape, html[start:end])
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError as exc:
        raise PageError(f"application state is not valid JSON: {exc}", "malformed") from exc


# ----------------------------------------------------------------------------- store
@dataclass
class StoreInfo:
    location_id: str = ""
    name: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    zipcode: str = ""
    banner: str = ""

    @property
    def full_address(self) -> str:
        return ", ".join(x for x in (self.address, self.city, f"{self.state} {self.zipcode}".strip()) if x)


def store_info(state: dict) -> StoreInfo:
    mp = ((state.get("calypso") or {}).get("domains") or {}).get("modalityPreferences") or {}
    active = ""
    for m in mp.get("modalities") or []:
        active = ((m.get("destination") or {}).get("locationId")) or active
    for d in mp.get("storeDetails") or []:
        if not active or d.get("locationId") == active:
            a = (d.get("address") or {}).get("address") or {}
            return StoreInfo(location_id=str(d.get("locationId") or ""), name=clean_text(d.get("vanityName") or a.get("name")),
                             address=", ".join(a.get("addressLines") or []), city=a.get("cityTown", ""),
                             state=a.get("stateProvince", ""), zipcode=a.get("postalCode", ""), banner=d.get("banner", ""))
    return StoreInfo(location_id=active)


_LOGO_RE = re.compile(r'<img[^>]+src="([^"]+)"[^>]+alt="marianos logo"', re.I)


def store_logo(html: str, base_url: str) -> str:
    m = _LOGO_RE.search(html)
    if not m:
        return ""
    src = htmllib.unescape(m.group(1))
    return src if src.startswith("http") else base_url.rstrip("/") + src


# ----------------------------------------------------------------------------- department navigation
@dataclass
class Shelf:
    name: str
    url: str          # original Mariano's link (kept for the report)
    query: str        # search query used to read the shelf
    taxonomy: str     # taxonomy prefix products must match ('' = department filter)
    curated: bool = False

    def queries(self) -> list[str]:
        """Search terms that together cover the shelf: its name, the parts of a compound name
        ("Milk & Milk Substitutes" -> "Milk", "Milk Substitutes") and the words of its URL slug."""
        out: list[str] = []
        parts = [self.query] + re.split(r"\s*(?:&|,|\band\b|/)\s*", self.name)
        m = re.match(r"/pl/([^/]+)/", urlparse(self.url).path)
        if m:
            parts.append(re.sub(r"[-_]+", " ", unquote(m.group(1))))
        for q in parts:
            q = clean_text(q)
            if len(q) > 2 and q.lower() not in {x.lower() for x in out}:
                out.append(q)
        return out[:5]


def department_shelves(state: dict, slug: str) -> list[Shelf]:
    """Sub-categories of the department /d/<slug>: the site menu tree (complete, with taxonomy ids)
    plus the department page's own tiles (adds curated shelves). Links to other departments are ignored."""
    out: list[Shelf] = []
    seen: set[str] = set()

    def add(name, url):
        name = clean_text(name)
        path = urlparse(url).path
        if not url or not name or path.startswith("/d/") or name.lower().startswith("shop all"):
            return
        sh = shelf_from_url(name, url)
        key = sh.taxonomy or sh.query.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(sh)

    for name, url in menu_links(state, slug):
        add(name, url)
    pages = {k: v for k, v in (state.get("dynamicdata") or {}).items() if k.startswith(f"page/1-0-0/department/{slug}/")}
    for page in pages.values():
        for block in ((page.get("assetData") or {}).get("data") or {}).get("content") or []:
            for nav in (block.get("data") or {}).get("navItems") or []:
                add(nav.get("altText") or nav.get("subText") or nav.get("omnitureTag"), nav.get("url") or "")
    return out


def menu_links(state: dict, slug: str) -> list[tuple[str, str]]:
    """(title, url) of every product-list link under the site-menu node whose 'Shop All' points to /d/<slug>."""
    menus = [v for k, v in (state.get("dynamicdata") or {}).items() if "site-menu" in k]
    if not menus:
        return []
    root = ((menus[0].get("assetData") or {}).get("data") or {}).get("menu") or {}

    def links(n):
        for ch in n.get("children") or []:
            if ch.get("url"):
                yield ch.get("title") or ch.get("name") or "", ch["url"]
            yield from links(ch)

    def owns(n):
        return any(urlparse(u).path.rstrip("/") == f"/d/{slug}" for _, u in links(n))

    best = None
    def walk(n):
        nonlocal best
        for ch in n.get("children") or []:
            if owns(ch):
                if sum(1 for _, u in links(ch) if urlparse(u).path.startswith("/pl/")) >= 2:
                    best = ch      # deepest node that owns the department link and still lists its sub-categories
                walk(ch)
    walk(root)
    if not best:
        return []
    return [(t, u) for t, u in links(best) if urlparse(u).path.startswith("/pl/")]


def shelf_from_url(name: str, url: str) -> Shelf:
    p = urlparse(url)
    q = parse_qs(p.query)
    m = re.match(r"/pl/[^/]+/(\d+)", p.path)
    if m:  # product list: read through search, keep only products of this taxonomy
        return Shelf(name, url, (q.get("query") or [name])[0], m.group(1), curated=False)
    query = (q.get("query") or q.get("keyword") or [name])[0]
    return Shelf(name, url, query, "", curated=True)


def department_code(shelves: list[Shelf]) -> str:
    """Two-digit department code most of the department's product lists share (e.g. '05' for Meat)."""
    from collections import Counter

    codes = Counter(s.taxonomy[:2] for s in shelves if s.taxonomy)
    return codes.most_common(1)[0][0] if codes else ""


# ----------------------------------------------------------------------------- search results
@dataclass
class SearchPage:
    upcs: list[str]
    products: dict          # upc -> product domain object
    codes: dict             # upc -> list of sub-commodity codes
    total: int = 0
    available: int = 0
    request_location: str = ""
    store: StoreInfo = field(default_factory=StoreInfo)


def search_page(state: dict) -> SearchPage:
    sa = (state.get("search") or {}).get("searchAll") or {}
    if sa.get("hasError"):
        raise PageError(f"search returned an error: {str(sa.get('error'))[:200]}", "upstream")
    resp = sa.get("response") or {}
    upcs = [u for u in resp.get("upcs") or []]
    codes = {p.get("upc"): p.get("subCommodityCode") or [] for p in resp.get("products") or []}
    prods = ((state.get("calypso") or {}).get("domains") or {}).get("products") or {}
    info = resp.get("productsInfo") or {}
    missing = [u for u in upcs if u not in prods or "data" not in prods[u]]
    if upcs and len(missing) == len(upcs):
        # the page listed products but Mariano's own product service did not answer (seen: "outbound timeout exceeded")
        raise PageError("product details missing for every listed UPC (upstream product service failed)", "upstream")
    return SearchPage(upcs=upcs, products=prods, codes=codes, total=int(info.get("totalCount") or 0),
                      available=int(info.get("availableCount") or 0),
                      request_location=str((sa.get("requestVars") or {}).get("locationId") or ""), store=store_info(state))


def product_codes(prod: dict, listed: list[str] | None = None) -> list[str]:
    """Taxonomy codes of a product: from the search summary, else from the product's own taxonomy
    (department + commodity + sub-commodity, the same scheme as /pl/<slug>/<id> ids, e.g. 05 001 00004)."""
    codes = list(listed or [])
    item = ((prod or {}).get("data") or {}).get("item") or {}
    for t in item.get("taxonomies") or []:
        d, c, sc = ((t.get(k) or {}).get("code", "") for k in ("department", "commodity", "subCommodity"))
        if d:
            codes.append(f"{d}{c}{sc}")
    return codes


def expansion_terms(prod: dict, prefix: str, shelf_name: str) -> list[str]:
    """New search terms from a product of the shelf: its sub-commodity / commodity names inside the shelf's
    taxonomy and '<brand> <shelf noun>' (e.g. 'Duracell Batteries')."""
    item = ((prod or {}).get("data") or {}).get("item") or {}
    out = []
    for t in item.get("taxonomies") or []:
        d, c, sc = ((t.get(k) or {}).get("code", "") for k in ("department", "commodity", "subCommodity"))
        if prefix and not f"{d}{c}{sc}".startswith(prefix):
            continue
        for k in ("subCommodity", "commodity"):
            name = clean_text((t.get(k) or {}).get("name"))
            if name and len(name) > 2:
                out.append(name.title() if name.isupper() else name)
    brand = clean_text((item.get("brand") or {}).get("name"))
    noun = clean_text(re.split(r"\s*(?:&|,|/)\s*", shelf_name)[0])
    if brand and noun:
        out.append(brand if noun.lower() in brand.lower() else f"{brand} {noun}")
    return out


def matches(codes: list[str], prefix: str) -> bool:
    return not prefix or any(str(c).startswith(prefix) for c in codes)


# ----------------------------------------------------------------------------- product -> record
@dataclass
class Mapped:
    record: dict | None
    reason: str              # kept | approximate_weight | store_mismatch | no_identity
    source_location: str = ""
    offer_labels: list = field(default_factory=list)
    identity: str = ""       # dedup key: the UPC, or "product:<Mariano's product id>" when no UPC is given
    identity_source: str = ""   # item.upc | data.id
    source_product_id: str = ""
    availability: str = ""   # priced | no_store_price
    sell_by: str = ""
    offers: list = field(default_factory=list)   # structured offers with kind + terms
    trigger: tuple = ()      # (field, text) that caused an approximate-weight exclusion
    modalities: dict = field(default_factory=dict)


def _usd(node: dict | None, key: str = "price") -> str:
    return format_price((node or {}).get(key))


def _image(item: dict) -> str:
    imgs = item.get("images") or []
    for persp in ("front",):
        for size in ("medium", "large", "xlarge"):
            for im in imgs:
                if im.get("perspective") == persp and im.get("size") == size and im.get("url"):
                    return im["url"]
    return imgs[0]["url"] if imgs and imgs[0].get("url") else ""


def _ts(node: dict | None) -> str:
    """Source timestamp {'value': '2026-10-28T03:59:59.999Z'} -> '2026-10-28T03:59:59Z'; open-ended (year 9999) -> ''."""
    v = (node or {}).get("value") if isinstance(node, dict) else node
    if not v or str(v).startswith("9999"):
        return ""
    return re.sub(r"\.\d+Z$", "Z", str(v))


def approximate_weight_trigger(item: dict, price: dict, ctx: dict) -> tuple:
    """(field, text) when Mariano's own wording says the weight is approximate / estimated, else ().

    Checked: the displayed size and the displayed regular / sale price wording (e.g. "about $10.39 each",
    which Mariano's shows when the package price is estimated from an average weight). Not checked: titles
    (a title such as "(About 3 Steaks per Pack)" describes a count) and sellBy alone (a product sold by
    weight with an exact displayed price is kept)."""
    sp = price.get("storePrices") or {}
    fields = [("customerFacingSize", item.get("customerFacingSize"))]
    if ctx.get("approx_price_wording", True):
        for k in ("regular", "promo"):
            fields.append((f"storePrices.{k}.defaultDescription", (sp.get(k) or {}).get("defaultDescription")))
    for name, text in fields:
        if text and is_approximate(str(text)):
            return (name, clean_text(text))
    return ()


def map_product(prod: dict, ctx: dict) -> Mapped:
    data = prod.get("data") or {}
    item = data.get("item") or {}
    price = data.get("price") or {}
    sp = price.get("storePrices") or {}
    regular, promo = sp.get("regular") or {}, sp.get("promo") or {}
    src = str(sp.get("sourceLocationId") or "")
    if src and src != ctx["store_id"]:
        return Mapped(None, "store_mismatch", src)

    # identity: the UPC only ever comes from item.upc; Mariano's product id (data.id) is kept separately
    upc = clean_text(item.get("upc"))
    pid = clean_text(data.get("id"))
    if upc:
        identity, id_src = upc, "item.upc"
    elif pid:
        identity, id_src = f"product:{pid}", "data.id"
    else:
        return Mapped(None, "no_identity", src)

    modal = {}
    for loc in data.get("sourceLocations") or []:
        if str(loc.get("id")) == ctx["store_id"]:
            modal = {m.get("modalityType"): m.get("availability") for m in loc.get("modalityAvailabilities") or []}
    trig = approximate_weight_trigger(item, price, ctx)
    if trig:
        return Mapped(None, "approximate_weight", src, identity=identity, identity_source=id_src,
                      source_product_id=pid, sell_by=str(price.get("sellBy", "")), trigger=trig)

    size = clean_text(item.get("customerFacingSize"))
    availability = "priced" if regular else "no_store_price"   # unavailable products are kept, prices left empty
    regular_price = (_usd(regular, "unitPrice") or _usd(regular)) if regular else ""
    sale_price, offers = "", []
    ppm = regular.get("equivalizedUnitPriceString") or ""
    if int(regular.get("nfor") or 1) > 1:  # the shelf price itself is a multi-buy ("2 for $5.00")
        offers.append(deals.Offer(regular.get("defaultDescription", ""), "REGULAR_NFOR", _usd(regular, "nforPrice"),
                                  valid_to=_ts(regular.get("expirationDate")), source="price.storePrices.regular"))
    if promo:
        if int(promo.get("nfor") or 1) > 1:
            offers.append(deals.Offer(promo.get("defaultDescription", ""), "PROMO_NFOR", _usd(promo, "nforPrice"),
                                      valid_to=_ts(promo.get("expirationDate")), source="price.storePrices.promo"))
        else:
            p = _usd(promo, "unitPrice") or _usd(promo)
            if p and p != regular_price:
                sale_price = p
                ppm = promo.get("equivalizedUnitPriceString") or ppm  # the card shows the PPM of the price it shows
    for o in data.get("offers") or []:
        offers.append(deals.Offer(o.get("defaultDescription") or o.get("description") or "", o.get("displayTemplate") or "",
                                  valid_from=_ts(o.get("startDate")) or clean_text(o.get("start")),
                                  valid_to=_ts(o.get("endDate")) or clean_text(o.get("end")),
                                  modalities=tuple(o.get("modalities") or ()),
                                  limit=clean_text(o.get("limit") or o.get("maxQuantity") or ""), source="data.offers"))
    d = deals.classify(offers)

    brand = (item.get("brand") or {}).get("name", "")
    title = clean_text(item.get("description"))
    rec = {
        "zipcode": ctx["zipcode"], "store_name": ctx["store_name"], "store_location": ctx["store_location"],
        "store_logo": ctx["store_logo"],
        "store_brand": "yes" if is_store_brand(brand, title, ctx["brands"]) else "no",
        "category": ctx["category"], "sub_category": ctx["sub_category"],
        "product_title": title, "weight": size,
        "regular_price": regular_price, "sale_price": sale_price,
        "volume_deals_description": d.volume_description, "volume_deals_price": d.volume_price,
        "digital_deals_description": d.digital_description, "digital_deals_price": d.digital_price,
        "image_url": _image(item),
        "url": item.get("shareLink") or (f"{ctx['base_url']}/p/{item.get('seoDescription', '')}/{pid or upc}"
                                         if (pid or upc) else ""),
        "upc": upc, "gupc": "", "ppm": clean_text(ppm), "unit_price": "", "crawl_date": ctx["crawl_date"],
    }
    labels = [(o.text, o.template) for o in offers if o.text]
    return Mapped(rec, "kept", src, labels, identity=identity, identity_source=id_src, source_product_id=pid,
                  availability=availability, sell_by=str(price.get("sellBy", "")), offers=list(d.details),
                  modalities=modal)


# ----------------------------------------------------------------------------- coupons page
_COUPON_RE = re.compile(r'aria-label="Shop All Items for coupon: (.+?) coupon" data-testid="ShopAllItems-primary-(\d+)"', re.S)


def coupons(html: str) -> list[dict]:
    """Digital coupons displayed on /savings/cl/coupons/ (wording, id, expiry) exactly as shown."""
    out, seen = [], set()
    for m in _COUPON_RE.finditer(html):
        text, cid = clean_text(htmllib.unescape(m.group(1))), m.group(2)
        if cid in seen:
            continue
        seen.add(cid)
        exp = re.search(rf'data-testid="CouponExpiryDate-{cid}"[^>]*>([^<]+)<', html)
        out.append({"coupon_id": cid, "description": text, "expires": clean_text(exp.group(1)) if exp else "",
                    "classified_as": deals.kind_of(text) if deals.kind_of(text) != "other" else "digital"})
    return out
