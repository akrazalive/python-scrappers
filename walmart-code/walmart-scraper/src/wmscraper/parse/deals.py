"""Separates Walmart's displayed promotions into volume deals and digital deals.

Rules (from the contest specification):
* Volume deal  = no clipping/activation needed (2 for $5, BOGO, Mix & Match, "must buy 4").
* Digital deal = requires clip / activate / save / add an offer.
* Wording is preserved exactly. A price is stored ONLY when Walmart displays it;
  nothing is calculated (no BOGO price, no "save $1" -> final price).
* Walmart Cash, cash back, rebates and manufacturer mail-in offers are NOT treated as
  immediate digital price reductions; they are logged and excluded.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .text import clean_text, format_price

_REWARD_RE = re.compile(r"walmart\s*cash|cash\s*back|cashback|rebate|mail[-\s]?in|manufacturer\s+offer", re.I)
_DIGITAL_RE = re.compile(r"\bclip\b|clipped|\bcoupon\b|digital|\bactivate\b|add\s+(?:the\s+)?offer|save\s+(?:the\s+)?offer|\bload\b.*\boffer\b", re.I)
_VOLUME_RE = re.compile(
    r"\b\d+\s*for\s*\$\s*\d|\bbuy\s+\d+\b|\bget\s+\d+\s+(?:free|for)|\bbogo\b|mix\s*(?:&|and|or)\s*match|"
    r"must\s+buy\s+\d+|when\s+you\s+buy\s+\d+|\b\d+\s*/\s*\$\s*\d",
    re.I,
)
# Price explicitly displayed as the promotional price.
_N_FOR_PRICE_RE = re.compile(r"\b(\d+)\s*(?:for|/)\s*\$\s*(\d+(?:\.\d{1,2})?)", re.I)
_EACH_PRICE_RE = re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)\s*(?:each|ea\.?)\b", re.I)
_MUST_BUY_RE = re.compile(r"must\s+buy\s+\d+\s*[:@]?\s*(?:at\s*)?\$\s*(\d+(?:\.\d{1,2})?)", re.I)
_DIGITAL_FINAL_RE = re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)\s*(?:each\s*)?(?:with|w/)\s*(?:a\s+)?(?:digital\s+)?(?:clipped\s+)?coupon", re.I)


@dataclass
class DealResult:
    volume_description: str = ""
    volume_price: str = ""
    digital_description: str = ""
    digital_price: str = ""
    ignored_rewards: tuple[str, ...] = ()


def classify(texts: list[str]) -> DealResult:
    """Classify a list of promotion strings displayed for one product."""
    volume, digital, rewards = [], [], []
    seen = set()
    for raw in texts:
        t = clean_text(raw)
        if not t or t.lower() in seen:
            continue
        seen.add(t.lower())
        if _REWARD_RE.search(t):
            rewards.append(t)
        elif _DIGITAL_RE.search(t):
            digital.append(t)
        elif _VOLUME_RE.search(t):
            volume.append(t)

    res = DealResult(ignored_rewards=tuple(rewards))
    if volume:
        res.volume_description = " | ".join(volume)
        res.volume_price = _volume_price(volume[0])
    if digital:
        res.digital_description = " | ".join(digital)
        res.digital_price = _digital_price(digital[0])
    return res


def _volume_price(text: str) -> str:
    for rx in (_MUST_BUY_RE, _EACH_PRICE_RE):
        m = rx.search(text)
        if m:
            return format_price(m.group(1))
    m = _N_FOR_PRICE_RE.search(text)
    if m:
        return format_price(m.group(2))  # displayed price for the bundle, e.g. "2 for $5" -> 5.00
    return ""  # e.g. BOGO with no displayed price – never calculated


def _digital_price(text: str) -> str:
    m = _DIGITAL_FINAL_RE.search(text)
    return format_price(m.group(1)) if m else ""  # "Save $2" alone -> no price
