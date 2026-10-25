# Oxylabs usage, quota and operating cost – Mariano's (v1.1.0)

Only Mariano's is covered here; Walmart is reported in its own package. Both scrapers were developed against ONE
Oxylabs trial key, so the trial quota was shared between them.

## 1. Actual requests made for Mariano's (all on 2026-10-21 unless noted)

"Successful" = a page Oxylabs delivered (billable). Provider faults (HTTP 500 "we don't charge you for faulted
scrapes" per Oxylabs' own response) and HTTP 429 quota rejections were not delivered.

| Test / run | Successful | Faulted (not charged) | 429 quota | Source of the number |
|---|---|---|---|---|
| Development probes (page format, store pinning, paging, coupons) | ≈ 29 (4 with JS rendering) | ≈ 22 | 0 | session scripts – approximate (±5) |
| verify-store (live) | 1 | 0 | 0 | CLI output |
| Run 03b8dc (demo, 7 rows, limit 150) | 89 | 7 | 0 | report.json fetch_stats (106 attempts incl. 16 retries) |
| Run fa0c1b session 1 (entry #69) | ≈ 85 | 14 | 0 | run log (74 search pages + ≈ 11 store/canary/department/coupon pages) |
| Run fa0c1b continuation (entry #69) | 114 | 4 | 0 | report.json fetch_stats (131 attempts incl. 16 retries) |
| Run cf40b8 (query expansion) | ≈ 93 | 4 | 249 | run log (85 search + ≈ 8 setup pages); quota hit 04:50 |
| Run cf40b8 resumed 2026-10-23 06:53 | 0 | 0 | 13 | checkpoint fetch_stats |
| Quota check 2026-10-24 | 0 | 0 | 1 | this delivery |
| **Total Mariano's** | **≈ 411** | **≈ 51** | **263** | |

Exact credits: the Oxylabs dashboard (Usage → Web Scraper API, by day) is the authoritative figure; please attach
its export – it also contains the Walmart share of the same trial.

## 2. Why the Mariano's run stopped

Run cf40b8 was 85 requests into its first query-expansion wave when Oxylabs began answering every request with
`HTTP 429 QUOTA_EXCEEDED – You have reached your plan's quota` (2026-10-21 04:50 UTC). The trial quota was shared
with the Walmart runs on the same key. The run's checkpoint is intact (85 requests done, 950 rows, 488 requests
pending); it resumes when quota exists. Nothing has been purchased since.

## 3. Quota still needed to complete the open items (before any purchase)

| Step | Requests (estimate) | Basis |
|---|---|---|
| `mscraper probe` – paging / JS paging / brand filter, with evidence | 10 – 15 | 3 paging requests + one brand slice per brand on page 1 |
| Fresh full-CSV run (all 28 rows), incl. brand slices, expansion, coupons; killed once and resumed (live recovery) | 15,000 – 30,000 | ≈ 235 shelves × (≈ 3 seed + ≈ 25 expansion + ≈ 60–90 brand-slice requests); the range narrows after the probe and the first category |
| Failed-publication proof (scoped run forced to fail, latest/ unchanged) | ≈ 50 | small scope |
| Azure: 2 unattended scheduled executions (collection + repeat) | 2 × the full-run figure, or 1 full + 1 scoped repeat | the first Azure execution can be the fresh run itself |
| **Total to finish** | **≈ 30,000 – 60,000** | buy in two steps: probe + one category first (≈ 1,500), then the remainder |

## 4. Realistic twice-weekly usage per store

The first complete run's `ledger.json` gives the exact request count per category; until then, planning figures:

* full discovery every run: 15k – 30k requests × 8.7 runs/month ≈ 130k – 260k requests / month / store
* to reduce this, later runs can re-read only the request set that the previous complete run proved sufficient
  (complete brand slices + seeds); this is NOT implemented in 1.1.0 and is offered as an option after the first
  measured run.

Cost = requests × your Oxylabs price per 1,000 (depends on plan; JS-rendered requests are only used for the Coupons
page and the probe). Azure: Container Apps Job ≈ $0–10, Storage ≈ $1–2, Key Vault < $1, Log Analytics $0–3 per month.
