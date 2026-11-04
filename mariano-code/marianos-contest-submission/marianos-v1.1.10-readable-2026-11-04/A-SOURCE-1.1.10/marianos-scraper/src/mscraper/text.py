"""Small, tested helpers: price formatting, approximate-weight rules, store-brand matching."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_NUM_RE = re.compile(r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)")


def format_price(value) -> str:
    """'USD 4.99' / '$4.99' / 4.99 -> '4.99'. Returns '' when no price can be read; never invents one."""
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float, Decimal)):
        num = Decimal(str(value))
    else:
        m = _NUM_RE.search(str(value).replace("$", ""))
        if not m:
            return ""
        try:
            num = Decimal(m.group(1).replace(",", ""))
        except InvalidOperation:
            return ""
    if num < 0:
        return ""
    return f"{num.quantize(Decimal('0.01'))}"


# Approximate / variable-weight wording: "approx", "approximately", "about $9.71 each", "avg wt", "~1.5 lb", ...
_APPROX_RE = re.compile(
    r"\bapprox(?:\.|imately|imate)?\b|\babout\b|\bavg\.?\s*(?:wt|weight)?\b|\baverage\s+weight\b|"
    r"\best(?:\.|imated)?\s*(?:wt|weight)\b|~\s*\d|\bweight\s+varies\b|\brandom\s+weight\b",
    re.IGNORECASE,
)


def is_approximate(*texts: str) -> bool:
    return any(t and _APPROX_RE.search(t) for t in texts)


def clean_text(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def is_store_brand(brand: str, title: str, brands: tuple[str, ...]) -> bool:
    b = clean_text(brand).lower().replace("’", "'")
    t = clean_text(title).lower().replace("’", "'").replace("®", "")
    for pl in brands:
        if b == pl or t.startswith(pl + " ") or t.startswith(pl + "®"):
            return True
    return False
