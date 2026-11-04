"""Separates Mariano's displayed promotions into volume deals and digital deals.

Rules (contest specification):
* Volume deal  = no clipping/activation needed (2 for $5, BOGO, Mix & Match, "Save $1 each when you buy 5").
  A loyalty card may be required without changing the classification.
* Digital deal = requires clip / activate / save / add a digital coupon.
* Wording is preserved exactly. A price is stored ONLY when Mariano's displays it;
  nothing is calculated (no BOGO price, no "Save $1" -> final price, no percentage maths).
* Fuel points / reward points are not price reductions; they are counted and excluded.
* Product sizes / pack labels ("Family Pack", "Value Pack", "12 ct") are never promotions: only Mariano's
  price and offer objects are classified, never titles or sizes.
* Complete terms: validity dates, modalities and limits from the same source object are appended in
  parentheses, e.g. "Save $1 each when you buy 5 or more (valid 2026-10-07 to 2026-10-27; applies to: in-store)".
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .text import clean_text, format_price

_REWARD_RE = re.compile(r"\bfuel\s+points?\b|\b\d+x\s+points\b|\bpoints\b(?!.*\$)", re.I)
_DIGITAL_RE = re.compile(r"\bclip(?:ped)?\b|\bdigital\b|\bcoupon\b|\bactivate\b|\bload(?:ed)?\s+to\s+card\b|"
                         r"add\s+(?:the\s+)?offer|save\s+(?:the\s+)?offer", re.I)
_VOLUME_RE = re.compile(
    r"\b\d+\s*for\s*\$\s*\d|\bbuy\s+\d+\b|\bget\s+\d+\s+(?:free|for)|\bbogo\b|mix\s*(?:&|and|or)\s*match|"
    r"must\s+buy\s+\d+|when\s+you\s+buy\s+\d+|\b\d+\s*/\s*\$\s*\d|\bbuy\s+one\b", re.I)
# digital-coupon templates seen in Kroger price/offer data
DIGITAL_TEMPLATES = {"DIGITAL", "DIGITAL_COUPON", "COUPON", "CLIP", "LOADABLE", "ECOUPON"}

_N_FOR_PRICE_RE = re.compile(r"\b(\d+)\s*(?:for|/)\s*\$\s*(\d+(?:\.\d{1,2})?)", re.I)
_MUST_BUY_RE = re.compile(r"must\s+buy\s+\d+\s*[:@]?\s*(?:at\s*)?\$\s*(\d+(?:\.\d{1,2})?)", re.I)
_EACH_PRICE_RE = re.compile(r"^\s*\$\s*(\d+(?:\.\d{1,2})?)\s*(?:each|ea\.?)\b", re.I)
_DIGITAL_FINAL_RE = re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)\s*(?:each\s*)?(?:with|w/)\s*(?:a\s+)?(?:digital\s+)?(?:clipped\s+)?coupon", re.I)


@dataclass
class Offer:
    text: str
    template: str = ""     # Kroger displayTemplate, e.g. MEGA_EVENT
    price: str = ""        # a promotional price Mariano's displays for this offer (already formatted)
    valid_from: str = ""   # source start / effective timestamp, as given
    valid_to: str = ""     # source end / expiration timestamp, as given ("" = open-ended)
    modalities: tuple = () # source modalities the offer applies to, e.g. ("IN_STORE",)
    limit: str = ""        # source purchase limit when given
    source: str = ""       # where in Mariano's data the offer came from

    @property
    def terms(self) -> str:
        """Validity / eligibility terms from the same source object, appended to the retailer wording."""
        parts = []
        if self.valid_from and self.valid_to:
            parts.append(f"valid {self.valid_from} to {self.valid_to}")
        elif self.valid_to:
            parts.append(f"valid until {self.valid_to}")
        if self.modalities:
            parts.append("applies to: " + ", ".join(m.replace("_", "-").lower() for m in self.modalities))
        if self.limit:
            parts.append(f"limit {self.limit}")
        return "; ".join(parts)

    @property
    def full_text(self) -> str:
        return f"{self.text} ({self.terms})" if self.terms else self.text

    def as_dict(self, kind: str) -> dict:
        return {"kind": kind, "text": self.text, "template": self.template, "displayed_price": self.price,
                "valid_from": self.valid_from, "valid_to": self.valid_to, "modalities": list(self.modalities),
                "limit": self.limit, "source": self.source}


@dataclass
class DealResult:
    volume_description: str = ""
    volume_price: str = ""
    digital_description: str = ""
    digital_price: str = ""
    ignored: tuple[str, ...] = ()
    details: tuple = ()    # every offer with its kind and structured terms (sidecar evidence)


def kind_of(text: str, template: str = "") -> str:
    t = clean_text(text)
    if (template or "").upper() in DIGITAL_TEMPLATES or _DIGITAL_RE.search(t):
        return "digital"
    if _REWARD_RE.search(t) and not _VOLUME_RE.search(t):
        return "reward"
    if _VOLUME_RE.search(t) or (template or "").upper() == "MEGA_EVENT":
        return "volume"
    return "other"


def classify(offers: list[Offer]) -> DealResult:
    volume: list[Offer] = []
    digital: list[Offer] = []
    ignored: list[str] = []
    details: list[dict] = []
    seen = set()
    for o in offers:
        text = clean_text(o.text)
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        k = kind_of(text, o.template)
        o.text = text
        details.append(o.as_dict(k))
        if k == "volume":
            volume.append(o)
        elif k == "digital":
            digital.append(o)
        else:
            ignored.append(text)
    res = DealResult(ignored=tuple(ignored), details=tuple(details))
    if volume:
        res.volume_description = " | ".join(o.full_text for o in volume)
        res.volume_price = volume[0].price or volume_price(volume[0].text)
    if digital:
        res.digital_description = " | ".join(o.full_text for o in digital)
        res.digital_price = digital[0].price or digital_price(digital[0].text)
    return res


def volume_price(text: str) -> str:
    """Only a price that is written in the deal text: 'Must buy 4 at $1.99 each' -> 1.99, '2 for $5' -> 5.00."""
    for rx in (_MUST_BUY_RE, _EACH_PRICE_RE):
        m = rx.search(text)
        if m:
            return format_price(m.group(1))
    m = _N_FOR_PRICE_RE.search(text)
    return format_price(m.group(2)) if m else ""   # BOGO / "Save $1 each when you buy 5" -> no price


def digital_price(text: str) -> str:
    m = _DIGITAL_FINAL_RE.search(text)
    return format_price(m.group(1)) if m else ""   # "Save $2" alone -> no price
