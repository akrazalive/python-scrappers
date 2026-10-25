"""Output record with the contractually required field order.

Every field is a string; missing values are "" (never None). gupc and unit_price are
always "" at the scraper stage – they are owned by the downstream pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, fields

FIELD_ORDER: tuple[str, ...] = (
    "zipcode",
    "store_name",
    "store_location",
    "store_logo",
    "store_brand",
    "category",
    "sub_category",
    "product_title",
    "weight",
    "regular_price",
    "sale_price",
    "volume_deals_description",
    "volume_deals_price",
    "digital_deals_description",
    "digital_deals_price",
    "image_url",
    "url",
    "upc",
    "gupc",
    "ppm",
    "unit_price",
    "crawl_date",
)

PIPELINE_OWNED = ("gupc", "unit_price")  # never populated by the scraper


@dataclass
class Record:
    zipcode: str = ""
    store_name: str = ""
    store_location: str = ""
    store_logo: str = ""
    store_brand: str = "no"
    category: str = ""
    sub_category: str = ""
    product_title: str = ""
    weight: str = ""
    regular_price: str = ""
    sale_price: str = ""
    volume_deals_description: str = ""
    volume_deals_price: str = ""
    digital_deals_description: str = ""
    digital_deals_price: str = ""
    image_url: str = ""
    url: str = ""
    upc: str = ""
    gupc: str = ""
    ppm: str = ""
    unit_price: str = ""
    crawl_date: str = ""

    def to_ordered_dict(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for name in FIELD_ORDER:
            value = getattr(self, name)
            out[name] = "" if value is None else str(value)
        for name in PIPELINE_OWNED:
            out[name] = ""
        return out


assert tuple(f.name for f in fields(Record)) == FIELD_ORDER, "Record fields must match FIELD_ORDER"
