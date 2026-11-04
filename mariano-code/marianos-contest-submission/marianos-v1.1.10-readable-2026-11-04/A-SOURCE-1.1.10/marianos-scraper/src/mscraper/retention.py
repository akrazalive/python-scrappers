"""Retention: products are never dropped because one run did not see them or saw them without a price.

* Products without a current store price (`no_store_price`) are output with empty price fields.
* Products without a UPC are output with an empty `upc`; their identity is Mariano's product id, kept in
  observations.json (`source_product_id`, `identity_source: data.id`) – never in the UPC field.
* A product published before but not returned by this run is CARRIED: its last observed record is output unchanged,
  including its original `crawl_date` (the date it was last actually observed). observations.json marks it
  `status: carried` with `last_observed`, `last_observed_run` and `carried_since`, so fresh and carried observations are
  never mixed. Carried products are kept indefinitely.
"""
from __future__ import annotations


def carry_forward(fresh: dict[str, dict], fresh_obs: dict[str, dict], prev_records: dict[str, dict],
                  prev_obs: dict[str, dict], run_id: str, crawl_date: str) -> tuple[dict, dict]:
    records = dict(fresh)
    obs = {k: {**v, "status": "fresh", "last_observed": crawl_date, "last_observed_run": run_id} for k, v in fresh_obs.items()}
    for ident, rec in prev_records.items():
        if ident in records:
            if ident in prev_obs and prev_obs[ident].get("first_observed"):
                obs[ident]["first_observed"] = prev_obs[ident]["first_observed"]
            continue
        p = prev_obs.get(ident, {})
        records[ident] = rec
        obs[ident] = {**p, "status": "carried",
                      "last_observed": p.get("last_observed") or rec.get("crawl_date", ""),
                      "last_observed_run": p.get("last_observed_run", ""),
                      "carried_since": p.get("carried_since") or crawl_date}
    for ident, o in obs.items():
        o.setdefault("first_observed", o.get("last_observed", crawl_date))
    return records, obs
