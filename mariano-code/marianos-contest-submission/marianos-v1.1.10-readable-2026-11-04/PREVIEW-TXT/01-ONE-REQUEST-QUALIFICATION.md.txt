# Mariano's - proposed one-request Vernon Hills pickup qualification

**Status: PROPOSED. Nothing is approved and nothing has been sent.** The `kroger_search` body below is the body
v1.1.10 builds. It is not a verified, supported account contract. The request itself is what would test that.

## Proposed milestone (CST = UTC-6)

- **Wednesday 2026-11-04, 10:00 CST (16:00 UTC).** This happens only if you approve this exact request in writing
  by **09:00 CST on 2026-11-04**. The approval needs to say which budget it uses (see below).
- If approval arrives later on 2026-11-04, I will confirm a new exact time before sending anything. The latest
  start on that day is 18:00 CST.
- If there is no approval, nothing is sent, and the milestone lapses without any request.
- The redacted receipt goes to you within 1 hour after the request. The earliest is 11:00 CST if it runs at 10:00 CST.

## Exact command (one request at most)

Run locally from the unpacked v1.1.10 source (`A-SOURCE-1.1.10/marianos-scraper`). No Azure redeployment or job
change is involved. Credentials are `OXYLABS_USERNAME` / `OXYLABS_PASSWORD` from `.env` and are never logged.

```
MSCRAPER_FETCH_PROVIDER=oxylabs_realtime \
python -m mscraper --budget vernon-qual:1 verify-store --location marianos-502-vernon-hills --max-requests 1
```

Three independent limits hold it to one request:
- `--max-requests 1` sets the per-command cap.
- That also sets the fetcher's retries to 0 (`max(0, 1 - 1)`).
- `--budget vernon-qual:1` is a persistent total of 1. The ledger line is written before the request is sent, and
  any second attempt is refused as `budget`.

The command runs inside the live lock, so no other execution can overlap with it.

The budget choice is yours:
- **(a)** `vernon-qual:1` is a separate one-request cap, and Test 1 stays **0/19**.
- **(b)** `--budget test1:19` draws the request from Test 1, which would then read **1/19**.

I propose (a). Either way it is one request, and it needs your approval.

## Chosen query, URL and request body

- Query: **`milk`**. This is the configured canary query for this location, and a broad staple likely to return
  store-priced items.
- Target URL: `https://www.marianos.com/search?query=milk&searchType=default_search`
- Endpoint: `POST https://realtime.oxylabs.io/v1/queries` (Basic auth, redacted)
- Body, as built offline by `realtime_payload` (fetch.py line 280). This was computed with 0 requests:

```
{"source":"kroger_search","query":"milk","store_id":"53100502","fulfillment_type":"pickup"}
```

## Deadline

- Per request: an HTTP client timeout of 180 s, and a hard stop at 210 s (`timeout_seconds` 120 + 90).
- After the hard stop it ends as `timeout` with no retry. The single slot counts as used.

## Pass rule (all 8 checks come from the returned response, never from the request)

- `location_id_matches` (53100502)
- `search_request_pinned_to_store`
- `zipcode_matches` (60061)
- `address_matches` ("1720 N Milwaukee")
- `banner_matches` ("mariano")
- `fulfillment_modality_matches` (PICKUP)
- `prices_from_store`: at least one finite positive price whose source is 53100502
- `price_source_locations_match`: every price source equals {53100502}

If any check fails, Vernon Hills does **not** qualify. Test 1, Test 2 and any collection stay stopped, and I report
the result as a failure.

## Expected redacted receipt (template; values in <> come from the response)

```
request:  POST https://realtime.oxylabs.io/v1/queries   auth: Basic <REDACTED>
body:     {"source":"kroger_search","query":"milk","store_id":"53100502","fulfillment_type":"pickup"}
started:  2026-11-04T16:00:<ss>Z (10:00 CST)     provider HTTP: <status>     elapsed: <s>
ledger:   {"ts":"<utc>","n":1,"command":"verify-store marianos-502-vernon-hills","store":"53100502",
           "url":"https://www.marianos.com/search?query=milk&searchType=default_search"}
budget:   {"name":"vernon-qual","total":1,"used":1,"remaining":0}
result:   {"verified":<true|false>,
           "checks":{"fulfillment_modality_matches":<>,"location_id_matches":<>,"search_request_pinned_to_store":<>,
                     "zipcode_matches":<>,"address_matches":<>,"banner_matches":<>,"prices_from_store":<>,
                     "price_source_locations_match":<>},
           "configured_store_id":"53100502","selected_store_id":"<>","store_name":"<>","store_location":"<>",
           "zipcode":"<>","banner":"<>","fulfillment_modality":"<>","store_logo":"<>","verified_at":"<utc>",
           "evidence_query":"milk","evidence_response_sha256":"<sha256>"}
exit:     0 = verified, 2 = not verified, otherwise the terminal error kind (auth / compat / timeout / budget)
evidence: state/_verify/marianos-502-vernon-hills/runs/<run_id>/evidence/pages/<sha256>.json.gz (+ raw/<sha256>.html.gz)
```

Redaction covers credentials and the account name only. Store, price, modality and hash values are reported as returned.

**Known limitation in v1.1.10.** If the response cannot be parsed as a Mariano's search page, v1.1.10 records the
ledger line and the error, but it does not archive the raw body. If you want the raw body kept in that case too,
I can add that offline first, as a separate small version for your review, before any request.

## Offline work that can proceed without approval (kept separate)

- Answering your source-review findings on v1.1.10 once you can read it here.
- Mariano's complete offer terms. These stay a separate requirement and are not covered by this qualification.
- The optional raw-body archiving above.

## Needs your decision (none approved here)

- This one request, and the budget choice (a) or (b).
- Test 1 (0/19) and Test 2 (300).
- Redeployment and any full traversal.
