"""Small, well-tested text helpers: price formatting, weight, approximate-weight rules."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_PRICE_RE = re.compile(r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)")
_CENTS_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*¢\s*$")


def format_price(value) -> str:
    """Normalise a displayed price to a plain two-decimal string ('$1,299.5' -> '1299.50').

    Returns '' when no price can be read. Never invents a value.
    """
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float, Decimal)):
        num = Decimal(str(value))
    else:
        text = str(value).strip()
        cents = _CENTS_RE.match(text)
        if cents:
            num = Decimal(cents.group(1)) / 100
        else:
            m = _PRICE_RE.search(text.replace("$", ""))
            if not m:
                return ""
            try:
                num = Decimal(m.group(1).replace(",", ""))
            except InvalidOperation:
                return ""
    if num < 0:
        return ""
    return f"{num.quantize(Decimal('0.01'))}"


# A listing price field must be ONE whole price token ("$1,299.50", "4.98", 4.98, "27 ¢") - never a number found
# inside other wording ("Only 2 left", "Save $2", "2 for $5", "$3.48 - $5.00").
_WHOLE_PRICE_RE = re.compile(r"^\s*\$?\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?\s*$")


def listing_price(value) -> str:
    """Typed / whole-token validation of a listing price field BEFORE normalisation. '' when it is not a price."""
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, (int, float, Decimal)):
        try:
            num = Decimal(str(value))
        except InvalidOperation:
            return ""
        return format_price(num) if num.is_finite() and num > 0 else ""
    text = str(value)
    if not (_WHOLE_PRICE_RE.match(text) or _CENTS_RE.match(text)):
        return ""
    out = format_price(text)
    return out if out and Decimal(out) > 0 else ""


# Approximate / variable-weight wording. Matches "approx", "approximately", "avg wt",
# "average weight", "est. weight", "~1.5 lb", "weight varies", "sold by weight".
_APPROX_RE = re.compile(
    r"\bapprox(?:\.|imately|imate)?\b|\bavg\.?\s*(?:wt|weight)\b|\baverage\s+weight\b|"
    r"\best(?:\.|imated)?\s*(?:wt|weight)\b|~\s*\d|\bweight\s+varies\b|\bsold\s+by\s+(?:the\s+)?(?:weight|lb|pound)\b",
    re.IGNORECASE,
)


def is_approximate_weight(*texts: str) -> bool:
    return any(t and _APPROX_RE.search(t) for t in texts)


# Size / net content at the end of many Walmart titles: "…, 16 oz", "… 1 gal", "… 12 ct, 2 Pack".
_SIZE_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:fl\.?\s*oz|oz|lbs?|lb|g|kg|mg|ml|l|liters?|litres?|gal|gallons?|qt|quarts?|pt|pints?|ct|count|pk|pack|sq\.?\s*ft|ft|in|yards?|rolls?|sheets?|pieces?|pcs)\b"
    r"(?:\s*[,x×]\s*\d+(?:\.\d+)?\s*(?:ct|count|pk|pack|rolls?)\b)?)",
    re.IGNORECASE,
)


def extract_weight(*candidates: str) -> str:
    """Return the displayed size/net content as written. Checks candidates in order."""
    for text in candidates:
        if not text:
            continue
        matches = _SIZE_RE.findall(text)
        if matches:
            return matches[-1].strip()
    return ""


def clean_text(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def is_private_label(brand: str, title: str, brands: tuple[str, ...]) -> bool:
    b = clean_text(brand).lower()
    t = clean_text(title).lower()
    for pl in brands:
        if b == pl or b.startswith(pl + " ") or t.startswith(pl + " ") or t.startswith(pl + ","):
            return True
    return False
