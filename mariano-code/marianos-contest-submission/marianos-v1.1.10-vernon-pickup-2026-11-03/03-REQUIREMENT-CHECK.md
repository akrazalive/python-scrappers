# Requirement check

- Enabled Vernon Hills acceptance location and response-derived labels: complete.
- Crystal Lake disabled and labelled diagnostic-only: complete.
- Verification checks returned ID, Mariano's banner, address, ZIP, modality, and
  positive prices from the configured store: complete.
- Realtime search payload derives `store_id` and fulfillment mode from location:
  complete (`PICKUP` -> `pickup`).
- Test 1 remains capped at 19 requests with stop-on-first-failure; Test 2 uses
  Vernon Hills: complete.
- Added `tests/test_v1110_scope.py`: complete.
- Version, Azure `releaseBlob`, changelog, source package and hashes: complete.
- Existing pytest: 92 passed.
