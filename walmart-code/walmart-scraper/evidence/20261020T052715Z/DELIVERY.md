# Delivery evidence – Walmart location scraper

* Version **1.0.0** · source_sha256 `32ff7120bc16128978f903a0b93324fd07605ad6eee4b3f6528d6f8c60c53ef0` (same value in every report and log)
* Location `walmart-100-bentonville` · store #100 · ZIP 72712 · 406 S Walton Blvd · fulfillment pickup
* Live run `20261020T052832Z-7675e9`: 1202 unique records · runtime 6921.9 s · 1600 provider requests (460 retries, 0 challenges) · validation ok: False · published: False
* Store verified: Bentonville S Walton Blvd Supercenter #100, 406 S Walton Blvd, Bentonville, AR 72712 (2026-10-20T05:29:14+00:00)

| Requirement | Evidence |
|---|---|
| Versioned source | `0-source/*-src.zip`, `0-source/SHA256SUMS.txt` |
| Unit / simulated tests (not retailer data) | `A-unit-and-simulated/` |
| Real dataset ≥ 500 products, exact 22-field schema | `B-live-walmart/04-dataset.json`, `13-schema-and-field-examples.json` |
| Store #100 + pickup context in source responses | `B-live-walmart/01-store-verification.log`, `07-raw-source-responses/index.json` (store_context per response) |
| Logs | `B-live-walmart/02…`, `03…`, `06-structured-log.jsonl` |
| Hard kill + resume | `B-live-walmart/02-run-part1-hard-killed.log` → `03-run-resumed.log`, `08-resume-proof.json` |
| Per-category completeness, thin detection | `B-live-walmart/09-category-completeness.csv`, `10-listing-coverage.csv` |
| Failed / thin runs cannot replace output | LIVE: `D-live-failed-run-not-published/` (if present) · SIMULATED baseline: `B-live-walmart/11-SIMULATED-*` · offline: `A-…/verification-board.png` |
| Real repeat collection | `B2-live-repeat-run/` (second fresh run, validated against the first published run) |
| Production traversal beyond 25 pages | `E-production-traversal/05-listing-exhaustion.csv` (exhaustion + price partitioning) |
| Product identity / variants | `B-live-walmart/15-product-identity-trace.csv` (request → response id/name/UPC → output) |
| Offers displayed by Walmart | `B-live-walmart/16-offer-census.json` (every label, classified) |
| PPM, UPC, offer terms as scraped | `B-live-walmart/13-schema-and-field-examples.json`, raw responses in `07-…` |
| Azure scheduled publishing | (pending) |
| Deployment, schedule, operations, cost | source ZIP → `docs/OPERATIONS.md`, `docs/COST.md`, `deploy/azure/` |

## File checksums

| file | sha256 |
|---|---|
| 0-source/package_source.log | `35667a9755ff0315f1aad1babab076b0e58dd2db2a23ded239b3b8bbc609c49d` |
| 0-source/SHA256SUMS.txt | `288ff29675165df1f4c22dd24b4ad5883cafe972f32b69d7f7c46cd5cb42ba7f` |
| 0-source/walmart-scraper-1.0.0-src.zip | `62dc55c7d3547260bb0cd5f92670bf12d516955b10552521257a510a34407690` |
| A-unit-and-simulated/README.md | `cfd076b8757f7fce1fcd140a1e1691841bb347b41301af5fecfc1eaf5e18bed5` |
| A-unit-and-simulated/test-results.txt | `06892eccbb3de8c7ed0749bb3f823a3703de2a89f7ee48e4c223a7d7cb0bc179` |
| A-unit-and-simulated/verification-board.png | `cefbce26961c96886d4664594c3e8955f926a78d6914000b8ae77a9fb246b3e8` |
| A-unit-and-simulated/verification-evidence.json | `9b6471c50fe0f3c41b152d80c6f76f65dffffeca477d6b71f18d758a08cbf88f` |
| A-unit-and-simulated/verification_board.log | `120f5cef38c00fc536131a9f6ef229294761655e3842912d53d2b5052b5827eb` |
| B-live-walmart/01-store-verification.log | `098ead2e056b054b33484cdd84123582aacba0c94724bb2da36db74f670f28e1` |
| B-live-walmart/02-run-part1-hard-killed.log | `f1bb15487f1c5b42fe8c08e5d2d564d84c2278e9c7027701beb8106e2dbfb417` |
| B-live-walmart/03-run-resumed.log | `432f9f580249c262cedf55ad5facbfe015cdfad71bab3e5f53c4d3b9c393f3e0` |
| B-live-walmart/04-dataset.json | `207a2059969cbf4e6758818963ee6864eb2e4de1acf5c91b96e464555df9c9d9` |
| B-live-walmart/05-run-report.json | `e536bef2701d5088eb1b261b9e4bbcc3aa8e4c74e74aae9a3d833957eda566fe` |
| B-live-walmart/06-structured-log.jsonl | `e29dc472278e786b9a351252ae18e540db39d17f93d5b787d2773ea584eb1d8f` |
| B-live-walmart/07-raw-source-responses/category-01.html.gz | `f628fcc9582f148364ecb3ea81b952fbf9870b0aff86a31491c420f701568829` |
| B-live-walmart/07-raw-source-responses/category-02.html.gz | `70e698a1cfa4ccc26fe90651620d960bc6993137aa4893acf448f10ac7316d06` |
| B-live-walmart/07-raw-source-responses/category-03.html.gz | `74f0f86906da1bff1e35e73a6a2d2477c228d778f375e0822788c03e7a0753f4` |
| B-live-walmart/07-raw-source-responses/category-04.html.gz | `87915d554b09bf495fbdc56387e7ec56ac3fa2367019dff246573366ef9ce137` |
| B-live-walmart/07-raw-source-responses/category-05.html.gz | `374066338cde0e824264f99a06bd3910199cb61578cd647246fb3bc29fca1992` |
| B-live-walmart/07-raw-source-responses/index.json | `0fcc45d5318a60d28bf31cad9c317931d531a1eef5fe8fd9ff01e8db30de8757` |
| B-live-walmart/07-raw-source-responses/listing-01.html.gz | `49a2df2b6daa89551c1a9a1f9d1fb651b9d9fe492361969fb7f098749574acd7` |
| B-live-walmart/07-raw-source-responses/listing-02.html.gz | `48cbbb807c2a8b8e69ab462376a07114436e1225d47e8507f7a3414125069e93` |
| B-live-walmart/07-raw-source-responses/listing-03.html.gz | `8a1ebf03ed29623e14bebad1c95d8289f1db06288737205f927bda9a1e52a9d6` |
| B-live-walmart/07-raw-source-responses/listing-04.html.gz | `57be94776893f5d1ce8845f6ccfbb4b66cf0211ae8d2243a0935ec184eb34ad3` |
| B-live-walmart/07-raw-source-responses/listing-05.html.gz | `f907cff7a1794c962baa09207924b84475660cd78da79a012aa5267e4681bb12` |
| B-live-walmart/07-raw-source-responses/product-01.html.gz | `2218333f6fcda2c853a74d31c650db102d3928efd3f5ad8cab806a16060b5a20` |
| B-live-walmart/07-raw-source-responses/product-02.html.gz | `3a584e3d8cdae918e3af54104068745f9d9bfe05f10de1eeeae0a6904f874958` |
| B-live-walmart/07-raw-source-responses/product-03.html.gz | `1b9fc29543917a99b2aead8c9cd7276c66e0e8e665d1499d7057d7e56dc08e53` |
| B-live-walmart/07-raw-source-responses/product-04.html.gz | `3e033503d1c1c982ac5bd3cfacc122b6ccf067530f3d99c13a30a4be3cefa258` |
| B-live-walmart/07-raw-source-responses/product-05.html.gz | `f482a343ec193d5bdde2c0a3ddb231fed84246f49f361a61b09259e8aef9a7d1` |
| B-live-walmart/07-raw-source-responses/store-01.html.gz | `8d64960c3b6d2168660b693594c0b70d660a7be213d50e1fc151c411c4ee091b` |
| B-live-walmart/08-resume-proof.json | `52b644cf7ac320050ac1944465c017ed19208969ab787c7e6c8b59749b9c698b` |
| B-live-walmart/09-category-completeness.csv | `d5b03850f31ac229b6eb86c21bb4f5e6f15aef4d87b2cb38ace4baf73abd1fbf` |
| B-live-walmart/10-listing-coverage.csv | `54bc5f0e18af2cbf28204ca98cd877b76223bccd58c4426313b671205fa359da` |
| B-live-walmart/11-SIMULATED-baseline-report.json | `e01d4af00a6d6453e59e5a201c55b9362fcf5e5c6b139053c1247f575ff7a434` |
| B-live-walmart/11-SIMULATED-yield-drop-check.log | `ed568e5b4c343cc67ebe2942b07562cfd215f80294d752c2d105b6e09e6e2c17` |
| B-live-walmart/12-published-manifest.json | `6098640165bfbccf5b88a31c662eaa0a0c400b3b7c3af111aba52a92e56d61bf` |
| B-live-walmart/13-schema-and-field-examples.json | `cb791009866aa06fd9fc6aa7315eeff71637023fca182a860e47a6be82560a18` |
| B-live-walmart/14-results-board.log | `a2c404f70c4f54d89bc7aaf6a64927b000274b5976d0bf2be88e9cc635a593c7` |
| B-live-walmart/14-results-board.png | `9eef781ed7d85d63585d6b6516d302935ae2d2146fca0cba28ad9880e8d86c73` |
| B-live-walmart/15-product-identity-trace.csv | `7e1e570d0d337b669ac69bd73ece03c37d906eaa9a33ca52f7a19f940ea1bcdc` |
| B-live-walmart/16-offer-census.json | `2adb0c8eece66698b8db85ccc6c8a9aa504d4631c0c21363545b5c4956554dc3` |
| B2-live-repeat-run/01-repeat-run.log | `4c3ee1aa582fef2e58ae499090a8407bb977f85506f65f627337abac59e5761d` |
| B2-live-repeat-run/02-repeat-dataset.json | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| B2-live-repeat-run/03-repeat-run-report.json | `1515a275988a2b34835a185e715a36cab04fcace15f6c7f249e4fa1fd854486b` |
| B2-live-repeat-run/04-repeat-structured-log.jsonl | `b341f6d4e53029e5c7c3dadf6c892465f4acc5f54b42baf23555f544d4e24e96` |
| B2-live-repeat-run/05-run1-vs-repeat-by-category.csv | `7996c6924d742e044cc08af50e6a2c307e9fc5baec82a356a07041088fa65422` |
| B2-live-repeat-run/06-repeat-summary.json | `199021182b4e809aed2f8f49491cfe1e158eaaf99d9af949ce5166b72cb75b37` |
| D-live-failed-run-not-published/01-latest-manifest-BEFORE.json | `6098640165bfbccf5b88a31c662eaa0a0c400b3b7c3af111aba52a92e56d61bf` |
| D-live-failed-run-not-published/02-blocked-run.log | `13157555d3574da18659b91520638e89026873b05a49c209c8879141e6e853cf` |
| D-live-failed-run-not-published/03-latest-manifest-AFTER.json | `6098640165bfbccf5b88a31c662eaa0a0c400b3b7c3af111aba52a92e56d61bf` |
| D-live-failed-run-not-published/04-blocked-run-report.json | `b2e080c96491d82b196d7e831a44ecb2721c6fa9b8e964a31ed3971a4045e7f3` |
| D-live-failed-run-not-published/05-summary.json | `996a49045fca05c8bc7ea29a046d98fa7294a7ccca9ece3641029f0ab9e8e9dd` |
| D-live-failed-run-not-published/README.md | `91af8873c888a072a4803fc975c9ec132e4da1e81ae4133076af6630020f31ce` |
| E-production-traversal/01-traversal-run.log | `377b6fd9e035526c31c7d7483acebe9ef7f2d090fe8aa1fdafc9b5cb70bba56f` |
| E-production-traversal/02-traversal-report.json | `e147c8b38866651cefc324df89debf87311ebc9b0797353bdc005f6d5442a9b2` |
| E-production-traversal/03-traversal-dataset.json | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| E-production-traversal/04-traversal-structured-log.jsonl | `fae9bd717860c44a79c02f238a76e23ea1a80dab37e6705d381d1c0b0764905a` |
| E-production-traversal/05-listing-exhaustion.csv | `09b42e999fff71b8fd58323a9526f6a74c2dfdb199881e072f1b07bccb87a5ca` |
| E-production-traversal/06-traversal-summary.json | `ae8208d77fd23e0a6d972e48adb944fe9927db126546d90446c13362c67c25cc` |
| E-production-traversal/README.md | `5b58e5e3f89e0d761e7a52cfaaaf607f42fd32431fadbbeb09e187d838bfca74` |
| live-summary.json | `6ffa850373427eac1b6e7f4c933496d7df419648f213df12dad6097294a179ba` |
