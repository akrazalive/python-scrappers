# Walmart scraper – Azure update 1.1.6 (Walmart only; Mariano's is a separate package)

walmart-scraper 1.1.6 · source_sha256 `8763a21283731c9d315251d338e4e210d3e94f6e188dc8563ee1f672534715d4` · 2026-10-26
**Azure deployment update only, and no new live data.** It supplements wm-delivery-v1.1.5-recheck.zip and
wm-walmart-response-2026-10-25.zip, which remain the live evidence (run 20261024T043517Z-fa478c on 1.1.5,
`75d76e0e…`). Nothing has been deployed, run or spent. Publication stays blocked.

## Files

| File | What it is |
|---|---|
| 01-INFRASTRUCTURE-FIRST-sequence-and-handover.md | why 1.1.6, confirmation that the infrastructure step needs no Oxylabs credential, the ids and commands you receive, sequence, relative timing, what waits on whom |
| 02-diff-1.1.5-to-1.1.6.patch | every changed line between the 1.1.5 and 1.1.6 source ZIPs (line endings ignored) |
| 03-offline-tests-1.1.6.txt | 47 offline tests, all passed (43 existing + 4 new for the Azure deployment; no live requests) |
| walmart-scraper-1.1.6-src.zip | complete source; docs/CHANGES.md lists the changes, docs/OPERATIONS.md the commands |
| MESSAGE-TO-CLIENT.txt | the covering message |
| SHA256SUMS.txt | checksums of the files above |
