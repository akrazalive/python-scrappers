# Delivery evidence - Walmart #100 location scraper (authoritative version)

* Version **1.0.0** · source_sha256 `29492665b7663a59f471e2766ae74e8abec4e7ca05fe56bc9020033ddf26a4bb` - the same value is in the source ZIP, every live log/report and the Azure logs.
* Store: Walmart #100, Bentonville S Walton Blvd Supercenter, 406 S Walton Blvd, Bentonville, AR 72712 (store_id 100, ZIP 72712).
* Live run `20261020T110652Z-e8ccea`: 1273 records = 695 fresh + 578 carried forward; validation ok, published; 713 provider requests, 0 retries, 0 bot challenges.
* Real repeat run `20261020T113321Z-48ec5f`: 1307 records, validation ok, published (real yield comparison against the previous published run).

| Requirement | Evidence | Type |
|---|---|---|
| Runnable source, one version | `0-source/walmart-scraper-1.0.0-src.zip`, `SHA256SUMS.txt`, `SOURCE_FINGERPRINT.txt` inside | source |
| Offline unit / simulated tests | `A-unit-and-simulated/` (31 tests, verification board) - **not retailer data** | offline |
| Dataset >= 500 genuine products, 22 fields in order | `B-live-walmart/04-dataset.json`, `13-schema-and-field-examples.json` | LIVE |
| Store / fulfillment from source responses | `B-live-walmart/01-store-verification.log`, `07-raw-source-responses/index.json` (store_context per response) | LIVE |
| Machine-readable logs | `B-live-walmart/02-*.log`, `03-*.log`, `06-structured-log.jsonl` (JSON lines) | LIVE |
| Hard kill + true resume | `02-run-part1-hard-killed.log` -> `03-run-resumed.log`, `08-resume-proof.json` | LIVE |
| Product identity / variants (charro beans) | `15-product-identity-trace.csv` (request URL -> final URL -> returned id/name/UPC -> output; 0 mismatches) | LIVE |
| Availability (keep unavailable, carry forward) | `B-live-walmart` run report `availability`, `17-availability-log.jsonl`; `F-availability-transition-example/` | LIVE |
| Offers displayed by Walmart | `16-offer-census.json` (every label, classified) | LIVE |
| Per-category completeness | `09-category-completeness.csv`, `10-listing-coverage.csv` | LIVE |
| Real repeat collection | `B2-live-repeat-run/` (`05-run1-vs-repeat-by-category.csv`) | LIVE |
| Failed run cannot replace output | `D-live-failed-run-not-published/` (manifest BEFORE == AFTER) | LIVE |
| Simulated yield-drop baseline | `B-live-walmart/11-SIMULATED-*` - explicitly simulated | SIMULATED |
| Production traversal beyond 25 pages | `E-production-traversal/` (live partition plan and findings; full crawl stopped, see README) | LIVE (partial) |
| Unattended Azure execution + publishing | `C-azure-deployed/` (schedule, executions, Log Analytics events, published blobs) | AZURE |

## File checksums

| file | sha256 |
|---|---|
| 0-source/package_source.log | `5235e12d031499f4ab8bdb1b69c49100b30fcc49ef3fc0ca5517c20dc854a5a4` |
| 0-source/SHA256SUMS.txt | `440f8830b86d9cf109a7127af65eb40187eb184f82ff3181b99f4beaaa3027a6` |
| 0-source/walmart-scraper-1.0.0-src.zip | `839a8b9e356aca839d5848cda6b96eeec1db2734a9c721bf83a57873bdda611f` |
| A-unit-and-simulated/README.md | `cfd076b8757f7fce1fcd140a1e1691841bb347b41301af5fecfc1eaf5e18bed5` |
| A-unit-and-simulated/test-results.txt | `39fc61b1f33e5234559b06b29515b32039eb4ae2486c86c9c9bef46932cd532d` |
| A-unit-and-simulated/verification-board.png | `871687350c24cec26b9ecaa10d961cf77159f61a468f2d43f6bce622dfb0075b` |
| A-unit-and-simulated/verification-evidence.json | `b2cba82dcc0fb48606bb561a166974a921761ef2ba050b356bc8e1af16e3b135` |
| A-unit-and-simulated/verification_board.log | `e70440eca4dad530b66e5cc2b31d18233cbd1d893e949126934c46ef35da14d0` |
| B-live-walmart/01-store-verification.log | `fb82e94431146e27413ad7699ed43fe49a2f0cc2e3f7d962e9765e3ef603f249` |
| B-live-walmart/02-run-part1-hard-killed.log | `f81d77eff02591327551d4ed94284bfb66c95cc66acfd4033c8dcde7568b998d` |
| B-live-walmart/03-run-resumed.log | `6e95e6bec0ab0dcae2c927df08bb7a71024bc759b0ace5e0bc35feaf66b31349` |
| B-live-walmart/04-dataset.json | `e4979efe737baa373fd9a54e3e70201c546d31a95e3de475bb96e2382b71ae7e` |
| B-live-walmart/05-run-report.json | `187d757c31cbbc2b00fcefa16b74c7fc6faad2a7193607aeca13a793c054f135` |
| B-live-walmart/06-structured-log.jsonl | `425702e0abe62c5f82c77ed7e9bc378531ae60606a9f69da9e81a4facfb4fbd4` |
| B-live-walmart/07-raw-source-responses/category-01.html.gz | `5746811f7ee1a8f0636a72557e8bc3f598da89416ab9088ef0d1b120d637bf44` |
| B-live-walmart/07-raw-source-responses/category-02.html.gz | `0ea36832a951a53933ca07e3b2c3b25066a6ba68d016865c89f2eb70a4848d7b` |
| B-live-walmart/07-raw-source-responses/category-03.html.gz | `21fecddc199b0f0ad625359975c51cdd2a9c3583376f00ebb1c03676cc9b7f29` |
| B-live-walmart/07-raw-source-responses/category-04.html.gz | `1dd2f4662d886417b56e6beb931a918418c72eae885c27660173151dadeb6e99` |
| B-live-walmart/07-raw-source-responses/category-05.html.gz | `33cea7abb461960990fc1f8261271715eb24151c407f2015086315266d9086da` |
| B-live-walmart/07-raw-source-responses/index.json | `5d2b43bda45e8b3c216af5839f051d354ffc66c3c6d621717c6106bc51bd0b3a` |
| B-live-walmart/07-raw-source-responses/listing-01.html.gz | `aa65c5e842312571da60decc9e2ca275ea2a082de573a937c46919088414253f` |
| B-live-walmart/07-raw-source-responses/listing-02.html.gz | `c864cf37a47b2598982d95c8fa92925faa0d3d566e0c2c642de10ac8e8cb122a` |
| B-live-walmart/07-raw-source-responses/listing-03.html.gz | `96ebcf13edcd30d65b6721ecce2a4813e6f4f546a8c1215a22857c97fe6629b6` |
| B-live-walmart/07-raw-source-responses/listing-04.html.gz | `f8ffb2aa49038378791b53d52f78dbc8f68da435a7315b037b51893630cc0445` |
| B-live-walmart/07-raw-source-responses/listing-05.html.gz | `4bb6e2534549450dd9b8973434ce164d1d25a269c66888b8db24c97f7f9aee78` |
| B-live-walmart/07-raw-source-responses/product-01.html.gz | `1bf72159f3442ed797609c6dbd020aa75a12669b17afb84cdd96963331510e2b` |
| B-live-walmart/07-raw-source-responses/product-02.html.gz | `667b3b58fb5878a7eed2ee21409112666c5a9e63d69acd9a1f416a0a93189a3f` |
| B-live-walmart/07-raw-source-responses/product-03.html.gz | `634264bb9303eea2afdb3da35be8d74d428db8e0cf346a00f0ee2e7254a8dab8` |
| B-live-walmart/07-raw-source-responses/product-04.html.gz | `d1592a7a38509a70d012a276453cff4aa4cde42d74c6c23c718dfdc58d6a1073` |
| B-live-walmart/07-raw-source-responses/product-05.html.gz | `79b546e13d5d347affe9012cee28d3d85f03dfb475f1dd5d3ca592f74f941e8c` |
| B-live-walmart/07-raw-source-responses/store-01.html.gz | `58073a165c40470ebe33d2cf8a283abb70e6d1eae5333c45a4326a906cd4f05c` |
| B-live-walmart/08-resume-proof.json | `cb56a8def9090532f539ea71838d7f90c6edb97b881dac1594466d1a56798b70` |
| B-live-walmart/09-category-completeness.csv | `ace609162f59c479de4371804368253ba454e0c9c81525e571784351c9f61c17` |
| B-live-walmart/10-listing-coverage.csv | `266ec965bc120051464924d96ae07724a9989128979bfc40d09747d6ee878de3` |
| B-live-walmart/11-SIMULATED-baseline-report.json | `57e10fa0e2e385df1a33a72d49a9e0fb2c9fe7d1cad0e07009fbec35c10dfcae` |
| B-live-walmart/11-SIMULATED-yield-drop-check.log | `6ca26d835e6f1a97027fd1c7d5543e14df89628238b94a73a31086c405e00044` |
| B-live-walmart/12-published-manifest.json | `6d74f005860544fa74d2016046e23171b8d8ed53e3c79d8eed741f761aa165d6` |
| B-live-walmart/13-schema-and-field-examples.json | `a6e78b020ba7ea49c8b1dbe9f160d00e0a7d27e1348ae15735bccc99687dbcf3` |
| B-live-walmart/14-results-board.log | `168b252fa6116633de284e9683348f7a141aeebd4bc1f23ac858160fa2f73590` |
| B-live-walmart/14-results-board.png | `795d64237962f104f5f942ca8754a4a8cdba4e9eb4fb90243c246a10725c00b0` |
| B-live-walmart/15-product-identity-trace.csv | `494b603ddb81403ecdaed085c68f1b818679412b38908a49e40f6670e584f20c` |
| B-live-walmart/16-offer-census.json | `f7f6163177f7f3efc5caa883e2b13c6562a057d37675423efbbeaf651f51f12d` |
| B-live-walmart/17-availability-log.jsonl | `c8fd676deaeaa2a72658b4ec529b288282f3556803f30aefd8b52c486027f4be` |
| B2-live-repeat-run/01-repeat-run.log | `db64600d65572c687fdeff6098e291aa79e864171729764666cbed39913336a3` |
| B2-live-repeat-run/02-repeat-dataset.json | `0e9179e5b21d28e8f7ceb5fb352658ebc0cb30d622fa16b6644fefa52a661bd3` |
| B2-live-repeat-run/03-repeat-run-report.json | `21a79e2769ffaae4447a48b052c09f8ab1983ad135717d337b59f8e84b016a0c` |
| B2-live-repeat-run/04-repeat-structured-log.jsonl | `a23cdfcead83a2eeaa23987392e062d744b723a1fd66ac0e49cfca9a84869ed0` |
| B2-live-repeat-run/05-run1-vs-repeat-by-category.csv | `2a34a6702a7201d2e04c7f541c92f2416afa3d7ed2f05d14e10ab1cd077ba8e3` |
| B2-live-repeat-run/06-repeat-summary.json | `fa4b09c648124b33b487ab500ab1a44cd2eac4d80922499d8340c4008f4a8364` |
| C-azure-deployed/01-job-schedule.json | `310dfd7dc94d948de58d186b6280ee7d8bff70d4e81b40d2326dcdc3d9b2a8d3` |
| C-azure-deployed/02-executions.json | `a51dd6159d7b31e1970dcdda9e289a583b8f70a5ba6f4375fd86f7d1e315b60a` |
| C-azure-deployed/03-log-analytics-events.json | `1458028e09a0fa2dc57001be93628e0d8508e9b9a9ac76344c5e773804d6079a` |
| C-azure-deployed/04-published-availability.json | `6d98165a4a61a2101d9db037ea582be19ce4a5133d7628f7559cd024eb4af357` |
| C-azure-deployed/04-published-manifest.json | `aa1c29fd22694a7b63d63678ab75954cf160b2c464a270b1a3bf3ecc2eb670de` |
| C-azure-deployed/04-published-records.json | `0a6b981c90b807d7604e59fe81c4444e525144b053f569b564ecbe828bb8a01d` |
| C-azure-deployed/04-published-report.json | `1ee8eb4d8d6c6e3bd659a5fc4d19276a5d83d8de0443e69e92c33dcfa9b80bf4` |
| C-azure-deployed/05-blob-listing.json | `1b43d46a048a160898de711184f9a26dca52f4effad9de4c03e46070d3a36f77` |
| C-azure-deployed/README.md | `51449e21020b18f575d6eded5a9e7ca2bc8b95ea373f36f36f01640f0dc07218` |
| D-live-failed-run-not-published/01-latest-manifest-BEFORE.json | `ef8c6c93d4a7f66a25de3ab667bb11ac1247021198d65cb0015560bbf29aeeba` |
| D-live-failed-run-not-published/02-blocked-run.log | `092db5e53ac21398ea14a03372416effc75d7179018e5f7912008c4422471a81` |
| D-live-failed-run-not-published/03-latest-manifest-AFTER.json | `ef8c6c93d4a7f66a25de3ab667bb11ac1247021198d65cb0015560bbf29aeeba` |
| D-live-failed-run-not-published/04-blocked-run-report.json | `6ec65f05488fa63bf3f688a091342e4ebc545c41f3587116d0a5b35ea656d908` |
| D-live-failed-run-not-published/05-summary.json | `504d24af54ee0e67f25027a49bf03746073eaa1a73c9796830d2cbeefbb4d3ca` |
| D-live-failed-run-not-published/README.md | `91af8873c888a072a4803fc975c9ec132e4da1e81ae4133076af6630020f31ce` |
| E-production-traversal/01-traversal-run.log | `122b632d7d1db80725d2f97b761039bd6363a8588978e16f85af51d4b4516320` |
| E-production-traversal/02-partition-plan-from-live-probes.csv | `b507b1fe2c2dce6fd5bef1b3e0c0c6af546e0e6b4b284f9c548bfe6664cd0994` |
| E-production-traversal/03-traversal-findings.json | `d8e6e3ef23431848dcfec6fba4bb06d1dfd053175b740d5fb8bf9e21a2c6223c` |
| E-production-traversal/README.md | `ac7f2f857a3e463ddd64fb6f4accf6acc8f676335ec241200f289d0134c1ba3f` |
| F-availability-transition-example/source-response-2026-10-19.html.gz | `f0684701c7b928904c1818453d6a0d556c7e9c30818677e9294e562426a90ed0` |
| F-availability-transition-example/source-response-2026-10-20.html.gz | `8780ab8382998585be312608b84ccf2d32ffa23c9941b80286c53ab34770c237` |
| F-availability-transition-example/transition.json | `668139bf39b3a74d8517cf623897428495dc17e89e320c832106fcd6849baf9d` |
