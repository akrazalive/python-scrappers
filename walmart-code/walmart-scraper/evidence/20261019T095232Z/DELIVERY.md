# Delivery evidence – Walmart location scraper

* Version **1.0.0** · source_sha256 `b2e9302824626631cb3699d049433cfc323c1851be1ec6e2a32de4b1976b6196` (same value in every report and log)
* Location `walmart-100-bentonville` · store #100 · ZIP 72712 · 406 S Walton Blvd · fulfillment pickup
* Live run `20261019T095339Z-b55042`: 917 unique records · runtime 1325.8 s · 935 provider requests (0 retries, 0 challenges) · validation ok: True · published: True
* Store verified: Bentonville S Walton Blvd Supercenter #100, 406 S Walton Blvd, Bentonville, AR 72712 (2026-10-19T09:53:45+00:00)

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
| 0-source/package_source.log | `48575bec390fd4a134e365eb60f575673f50237526f537749e4137d03d16005c` |
| 0-source/SHA256SUMS.txt | `84a8444ab082aa265030bd84b94ea5ea9d0e361818823dfcb6c3b9ff30fb661b` |
| 0-source/walmart-scraper-1.0.0-src.zip | `6cad4d2869343e4405ad1c66192c006e3dfcb5e8dadf1f67b998f6e9a2b79025` |
| A-unit-and-simulated/README.md | `cfd076b8757f7fce1fcd140a1e1691841bb347b41301af5fecfc1eaf5e18bed5` |
| A-unit-and-simulated/test-results.txt | `9f32e7316339803a4e5827058e1d7ef66a166953ae514a1109e91c69503bc700` |
| A-unit-and-simulated/verification-board.png | `2c447ef590656444a97200ed42d535542559928cc874185763e2c637c974f4bf` |
| A-unit-and-simulated/verification-evidence.json | `3a99d798a3c0443a451852275147320881b31dae24e788db589cc98cad029df7` |
| A-unit-and-simulated/verification_board.log | `2d3d60d8fba061577d84eef9359a21c4605fb4ed13ba8004c8f9a9750dc04242` |
| B-live-walmart/01-store-verification.log | `b3e331de3f0161906c358d4034fad78c8e6abe761938d6a25101e169b5239847` |
| B-live-walmart/02-run-part1-hard-killed.log | `13bfd97aead5bc27d089876cc571a9997f03a2b29d89c1f864d2070474fd97f9` |
| B-live-walmart/03-run-resumed.log | `bd98aa24b25e535a2457417b942fdac740b6a2b8926b8f7e68f24bc67d39ef22` |
| B-live-walmart/04-dataset.json | `529e67bea27851209eb3758de3087a90dfd35f8ec646dedfa3946fdb81021fb1` |
| B-live-walmart/05-run-report.json | `586efa62d5c04c76f60b6f807315fd37766289984d26ce64ae98bf1f512654c2` |
| B-live-walmart/06-structured-log.jsonl | `0cd84ebc4f5d10b25067e58e116051bd7a1f8e49b2e88334a3325fb09bcdc1b4` |
| B-live-walmart/07-raw-source-responses/category-01.html.gz | `aebe52e1294a35baffebe65a9a1d80836d67faa1d0b29a4442a5c2252cab82f8` |
| B-live-walmart/07-raw-source-responses/category-02.html.gz | `15be16b2d5e9d73b0fdfdb9e8998b216fddb126b9639c00021fb1987a2d7c784` |
| B-live-walmart/07-raw-source-responses/category-03.html.gz | `3405f217686294137326b1375277cb631ec2b77a68b753c07e996ba36699bd4c` |
| B-live-walmart/07-raw-source-responses/category-04.html.gz | `2f4d553307f18a08ab0723e92df699fdbaee5593a0a44d539b9ed92ca1880d2e` |
| B-live-walmart/07-raw-source-responses/category-05.html.gz | `3dfeabdd26666a5fd419eb2da8ab30cebe3f275a00e8672c26e97550e55c4848` |
| B-live-walmart/07-raw-source-responses/index.json | `ec40ff4461e9fc64a70274dc2dd04894b136403371e6405a42e7e714189698bb` |
| B-live-walmart/07-raw-source-responses/listing-01.html.gz | `a1a49166e22cfa56744534d8fa56d2eea198e8775c0c53ed934445d472c021eb` |
| B-live-walmart/07-raw-source-responses/listing-02.html.gz | `e0d0ca43cb739f191a1ec3706b15b131631c782a98dde20976c15a90d7da2145` |
| B-live-walmart/07-raw-source-responses/listing-03.html.gz | `d3546d55c0b23de4e274f784413f0baeaa1ca972bed4147e9ad9a89f97247663` |
| B-live-walmart/07-raw-source-responses/listing-04.html.gz | `b3ec677f550b01c54bca2710b6031f10e7b4551d580984362e2ba66f7097b319` |
| B-live-walmart/07-raw-source-responses/listing-05.html.gz | `50834b920292084e188c68353e569d918448c3df9abb4665dcb0134c06672dad` |
| B-live-walmart/07-raw-source-responses/product-01.html.gz | `bacf3dccffe01c047a90b9a9db96daa26a43e861cdd6a43a463867f35f345f3e` |
| B-live-walmart/07-raw-source-responses/product-02.html.gz | `ca8a8cc3719214bd61cfcec6a20b62548ad89fae6f64a84baca4a4b81ea2aeef` |
| B-live-walmart/07-raw-source-responses/product-03.html.gz | `dde1e459843e06de2f2cd371d9f675374f6e7d575151e907b7b748313cfade32` |
| B-live-walmart/07-raw-source-responses/product-04.html.gz | `fe9e8b0062ff6778bee2b770bd99f2ba7fd97b49ef7b423bd29ab1f441f23e09` |
| B-live-walmart/07-raw-source-responses/product-05.html.gz | `cade3dd28d6afb28dd60582340bffbe0eb153683987dd2d87f99ac1d22f8e92c` |
| B-live-walmart/07-raw-source-responses/store-01.html.gz | `4eee2bf4737909949a7c12ca4a85e1fb29bd33e6ec672644772fdc1582e92ed9` |
| B-live-walmart/08-resume-proof.json | `947c1b30740c21353a83b277cbc08097f14ab0f2072fc620dc35b5a823fec29d` |
| B-live-walmart/09-category-completeness.csv | `e9cfc57ae2ba8e80e4a03e54666b1af141e6b8fbac8d2dd9234a0c7dd4fa8399` |
| B-live-walmart/10-listing-coverage.csv | `bcf7724d5a6c79ccce582b49e316426e24d9f773261d704623111d12693a2218` |
| B-live-walmart/11-simulated-previous-good-report.json | `7e39e8a2e74a2032f573f263ed32fa352781dbd3e692fab1a5395c042e9769a2` |
| B-live-walmart/11-yield-drop-blocks-publication.log | `bed9767154b152fb5855687891c45b7be770aa68fbc0e71f2f78286ed44446e7` |
| B-live-walmart/12-published-manifest.json | `6098640165bfbccf5b88a31c662eaa0a0c400b3b7c3af111aba52a92e56d61bf` |
| B-live-walmart/13-schema-and-field-examples.json | `c2f39fdeaf6b8a8dffeb04d7c3c16741a990097567aa8b048765461f9cc4f8a8` |
| B-live-walmart/14-results-board.log | `5f60825f487df378b8dc2983edb7dc94df32df49af0f669a216d77bd1b9de5cd` |
| B-live-walmart/14-results-board.png | `8f18483ebdae54d8f716ef8d46668f275002a7593f8a3236eeb0441b1e27fc82` |
| live-summary.json | `f62c6d843413579e49d4ff8d52f203d44604c382964585de351334509aca18ae` |
