# LIVE evidence – 2026-10-21 (all of it; nothing newer exists)

Collected through the Oxylabs Web API (Kroger endpoint, `store_id` pinned) on 2026-10-21 with v1.0.0-dev / v1.0.0
code (see the run table in CHANGELOG.md inside the source ZIP). Kept unchanged. Not a full-coverage run.

| Item | What it is |
|---|---|
| entry69-run-fa0c1b-data/01-records-store53100544.json | the 1,027 delivered rows (sha256 0e1b7260…1051), Crystal Lake 53100544 |
| entry69-run-fa0c1b-data/02-run-report.json · 03-run-report-as-collected.json | report re-validated on 1.0.0 · report as written at collection |
| entry69-run-fa0c1b-data/04-coupons.json | 24 coupons read from the Coupons page |
| run-logs/ | original logs of runs 03b8dc, fa0c1b (session 1 + checkpoint continuation – not a crash recovery) and cf40b8 (quota stop, 23-Oct resume attempt) |
| coverage-reconciliation-v1.0.0-runs.json | what those runs covered and did not cover (not full coverage) |
| raw-responses-2026-10-21/ | raw marianos.com responses saved from the same provider on 21 Oct (development probes, not pages of run fa0c1b) |
| store-fulfillment-evidence-2026-10-21.json | extracted from those raw responses by `tools/store_evidence.py` (in the source ZIP) |

## Store / fulfillment evidence

| Response | Selected store | ZIP | Modality | Request pinned to | Price source of products | IN_STORE available at store |
|---|---|---|---|---|---|---|
| search milk | 53100544 Marianos Crystal Lake, 105 Northwest Hwy | 60014 | IN_STORE | 53100544 | 24 / 24 = 53100544 | 24 / 24 |
| search beef | 53100544 | 60014 | IN_STORE | 53100544 | 24 / 24 = 53100544 | 24 / 24 |
| search cereal, coupons filter | 53100544 | 60014 | IN_STORE | 53100544 | 24 / 24 = 53100544 | 24 / 24 |
| department meat · coupons page | 53100544 | 60014 | IN_STORE | – | – (no product grid) | – |
| control: search milk, store 53100539 | 53100539 (Bronzeville) | 60653 | PICKUP | 53100539 | 24 / 24 = 53100539 | 24 / 24 |

The control response shows that the store pin changes the store, the price source and the modality, which is why
v1.1.x checks all three.

Run fa0c1b itself (02-run-report.json): store verification passed (location id, request pin, ZIP 60014, address,
prices from 53100544); 192 pages store-verified, 0 mismatches; canary passed at start and end. Limits, stated
plainly: v1.0.0 did not yet check the fulfillment modality during the run and did not save each page's response –
the per-page ledger with response SHA-256 and price-bearing excerpts exists from v1.1.0 and will be in the first
new live run.
