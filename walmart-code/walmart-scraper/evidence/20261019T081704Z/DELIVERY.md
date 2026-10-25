# Delivery evidence – Walmart location scraper

* Version **1.0.0** · source_sha256 `4c52cef0d790a67ca505200b691719e885d757dab3b09fbfbb7cf52a217a4689` (same value in every report and log)
* Location `walmart-100-bentonville` · store #100 · ZIP 72712 · 406 S Walton Blvd · fulfillment pickup
* Live run `20261019T081808Z-78d378`: 1269 unique records · runtime 1471.3 s · 1000 provider requests (0 retries, 0 challenges) · validation ok: False · published: False
* Store verified: Bentonville S Walton Blvd Supercenter #100, 406 S Walton Blvd, Bentonville, AR 72712 (2026-10-19T08:18:20+00:00)

| Requirement | Evidence |
|---|---|
| Versioned source | `0-source/*-src.zip`, `0-source/SHA256SUMS.txt` |
| Unit / simulated tests (not retailer data) | `A-unit-and-simulated/` |
| Real dataset ≥ 500 products, exact 22-field schema | `B-live-walmart/04-dataset.json`, `13-schema-and-field-examples.json` |
| Store #100 + pickup context in source responses | `B-live-walmart/01-store-verification.log`, `07-raw-source-responses/index.json` (store_context per response) |
| Logs | `B-live-walmart/02…`, `03…`, `06-structured-log.jsonl` |
| Hard kill + resume | `B-live-walmart/02-run-part1-hard-killed.log` → `03-run-resumed.log`, `08-resume-proof.json` |
| Per-category completeness, thin detection | `B-live-walmart/09-category-completeness.csv`, `10-listing-coverage.csv` |
| Failed / thin runs cannot replace output | `B-live-walmart/11-yield-drop-blocks-publication.log`, `12-published-manifest.json`; simulated cases in `A-…/verification-board.png` |
| PPM, UPC, offer terms as scraped | `B-live-walmart/13-schema-and-field-examples.json`, raw responses in `07-…` |
| Azure scheduled publishing | (pending) |
| Deployment, schedule, operations, cost | source ZIP → `docs/OPERATIONS.md`, `docs/COST.md`, `deploy/azure/` |

## File checksums

| file | sha256 |
|---|---|
| 0-source/package_source.log | `af2ae5a0bce16ca2d2abfa06c83bb48b864fe5eb37ce52171ef24bc3e2e7dab0` |
| 0-source/SHA256SUMS.txt | `29c7f73db4407136633efc5c5035262a7b41d453760b70ca79223c406fdfd6b5` |
| 0-source/walmart-scraper-1.0.0-src.zip | `9d69b876cff09c2dcf2b78373b03644bfb9c2bbe69a8425f99db98ec757f7b7a` |
| A-unit-and-simulated/README.md | `cfd076b8757f7fce1fcd140a1e1691841bb347b41301af5fecfc1eaf5e18bed5` |
| A-unit-and-simulated/test-results.txt | `b7c594f327ad4c1f7d8d60a5c6378c585f979b82b2641a632c362c1bf81922f2` |
| A-unit-and-simulated/verification-board.png | `d76d228bf9e191cc600f257a1aa0888c2fdcb62f560420a3c8b1e3c1a0ad4128` |
| A-unit-and-simulated/verification-evidence.json | `b364cfd0800cd7904215ca03120682dff0362adc690e9d2ad5174a00fcdd6d6c` |
| A-unit-and-simulated/verification_board.log | `13011bb08ab9a8d806511f8d4f9b7e44fdc1b746c6d762964732fd420ed575b6` |
| B-live-walmart/01-store-verification.log | `313f2843db400eb7c97e015eb714439a6415261909837dd2ed428416b87d7cd2` |
| B-live-walmart/02-run-part1-hard-killed.log | `e61424aab560d5a9569712419630ae883c50abe4c68fdcad654d1858c2daba05` |
| B-live-walmart/03-run-resumed.log | `eb2231dda742aa6d1b7ef14ea1c36c187e68b830153b11cd832e6aef00564af0` |
| B-live-walmart/04-dataset.json | `f2747a60d750d9f36b4f8d72c003fd57ec79358142ed95db7714458d169bb12a` |
| B-live-walmart/05-run-report.json | `48ce84a0097f5fdb2ed8c4036bb667e41d1dd66595b128b7fdcfba4ac95aeede` |
| B-live-walmart/06-structured-log.jsonl | `c1586f3bf9f5a5301e75068e0b57791df7026bceafbe214ddb92ebb3193fd508` |
| B-live-walmart/07-raw-source-responses/index.json | `43c4aff081f82e9cd362ed99ff63a4a7c45a73351a9911080c49dbe281885ffd` |
| B-live-walmart/07-raw-source-responses/listing-01.html.gz | `fa653072137b2e9da0176f95b914b4ab052947a74766fa295d60ef22c2639c4c` |
| B-live-walmart/07-raw-source-responses/listing-02.html.gz | `b1f642c4e4a2ef1be8fcc143b1d081dda4d6087ae8d0c9edc9ac6f196062a1af` |
| B-live-walmart/07-raw-source-responses/listing-03.html.gz | `a28d3279708a8b5dc50881d09d02c48c631b6fbd491a46865cebf11b24b83b24` |
| B-live-walmart/07-raw-source-responses/listing-04.html.gz | `15a2bc968f2fc8d694d66137b7c48b30ff2269192cbd303e3f7ef7ccc2da6210` |
| B-live-walmart/07-raw-source-responses/listing-05.html.gz | `40feb7aaf39238955d6e639e872abee289f4737685421c13e173c6e0c9f82574` |
| B-live-walmart/07-raw-source-responses/product-01.html.gz | `903235565ace9c87ea10c81d760a29aed12082de831bdf785a260c522379fb81` |
| B-live-walmart/07-raw-source-responses/product-02.html.gz | `34bf291eec0b21dfdc886f2cd0b374f1ba111e5a1c1857831c1e879aa9a97b02` |
| B-live-walmart/07-raw-source-responses/product-03.html.gz | `6062cfeacbf9cf9b85f71e5bf6b41868ac19f88ccd5d5113c8180e270635092a` |
| B-live-walmart/07-raw-source-responses/product-04.html.gz | `b12905abbc83546f25d9955f3887c791f3bd16428faa1c41ab28816c56f71a75` |
| B-live-walmart/07-raw-source-responses/product-05.html.gz | `91628cf32adde200102d6e4d2f92caa62a6e8b9cc0e5c55fb2d592f4fe0f0e7a` |
| B-live-walmart/07-raw-source-responses/store-01.html.gz | `f246a3a30c56a57862c1b9e57094b771c0ed81b669bbe02b454cf052ea673623` |
| B-live-walmart/08-resume-proof.json | `230bc6a776908e5f3dc53017ad98d57b565513fd53d6c49dcedf9e3850cdd1ba` |
| B-live-walmart/09-category-completeness.csv | `a6b8775798e66b1855509d20f9d4fac4e7a24bc9d0d3cb446a9d77cc83bdeba8` |
| B-live-walmart/10-listing-coverage.csv | `dac6790adf055632cbcb03324350e2ad85c72b69cabdc2125c0fc8cbb1f17d27` |
| B-live-walmart/11-simulated-previous-good-report.json | `47efc585260cdeb4fc4a246151bfcb6b3416c89f80cf9a059aa810a02d33a24b` |
| B-live-walmart/11-yield-drop-blocks-publication.log | `835f26c4c74c0d756b278ba5df40938f27cdc395f560d168db414f01f285f50d` |
| B-live-walmart/12-published-manifest.json | `74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b` |
| B-live-walmart/13-schema-and-field-examples.json | `773dc0b7e345a06f6f15b523b912b3ac1d10f8e348e76f75a1d4221ff3401bfd` |
| B-live-walmart/14-results-board.log | `7462b9a2649c8a36630d4388818a6f21c599433b82c43a1e0eb229787b966ede` |
| B-live-walmart/14-results-board.png | `498048e166bc6dd441a81ce8264e714265ab92b274d2a1020c12f50b4e4a01eb` |
| live-summary.json | `c1d4e833d1607d5b99d84d434ad9bf8fa30544e8a02bc62d148c485f688f5b92` |
