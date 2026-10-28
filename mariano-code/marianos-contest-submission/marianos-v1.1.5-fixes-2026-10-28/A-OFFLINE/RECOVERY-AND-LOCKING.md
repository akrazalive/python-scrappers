# Recovery, locking and request budgets (v1.1.5)

Answers the client review of 27 Oct, points 1-5. Everything here is covered by offline tests in
`tests/test_v115_safety.py`. No live run has used this design yet.

## 1. Stop rule (bounded tests)

`bounded-test` runs its steps in order and stops at the first step that does not succeed:

* a non-zero exit (e.g. store verification failed: exit 2), or
* a terminal fetch error: `auth` (provider 401/403), `compat` (provider 400/404/422), `store`, `budget`, `lock`, or
* a `LockError`, `BudgetError` or `CheckpointError`.

Later steps are not started. Terminal errors are also never retried inside a step (`fetch.TERMINAL_KINDS`); only
429 / 5xx / timeouts / blocked responses are retried.
Tests: `test_failed_first_store_check_stops_bounded_test_before_any_other_step` (1 request, steps 2-3 never
started), `test_terminal_provider_errors_are_not_retried_and_stop_the_test`.

## 2. Exclusive ownership: one requester at a time

`lock.live_lock(storage)` is one Blob lease (`_live/.run.lock` in the `marianos-scraper` container; a lock file
locally). Every command that can send provider requests runs inside it: `bounded-test`, `verify-store`, `probe`,
`run`, `run-all`. It is one lock for all tests and both locations. A second, overlapping execution exits with code 3
before sending anything. The real provider adapters refuse to start without it.

The persistent budget (`budget.TotalBudget`) can only be opened and used while the live lock is held. It has no
cached counter: every `take()` re-checks the lock and re-reads and validates the state file from disk. Order per
request: ledger line appended and fsynced, then the state file replaced atomically, then the request is sent. If a
crash happens between the first two, the request is counted as used on the next open. Any other inconsistency
fails closed and no request is sent:
* the state file is missing while the ledger exists
* the state file is unreadable or invalid
* the ledger has fewer lines than `used`, or more than one extra line
* `used` is greater than `total`
* the total differs from the one requested

The existing Azure budget `test1` (used 0 of 19, created 2026-10-27T04:09:54Z) opens unchanged. It is never reset
or renamed.
Tests: `test_overlapping_execution_is_refused_and_sends_nothing`, `test_budget_needs_the_live_lock_and_survives_restart`,
`test_existing_test1_identity_from_azure_is_kept_with_19_remaining`, `test_budget_state_is_never_cached_between_two_holders`,
`test_inconsistent_budget_fails_closed[...]`, `test_crash_between_ledger_and_state_counts_the_request_as_used`.

## 3. Lease loss stops everything

The lease is renewed every 20 s. If a renewal fails, the lock is marked LOST, and `lock.check_active()` raises
`LockLost`. It is called:
* before every provider request (`Fetcher.get` → FetchError kind `lock`)
* before every checkpoint commit (the transaction is rolled back) and before every snapshot is written
* before each publication step, including the manifest write (the commit point)

Test: `test_lease_loss_stops_requests_checkpoint_writes_and_publication`. A lease whose renewal fails causes no
request, no checkpoint write and nothing published.

## 4. Checkpoints: SQLite on local disk, consistent snapshots on the share

The 27-Oct failure was `database is locked`: SQLite's byte-range locks do not work on the Azure Files (SMB) share.
Locks are **not** disabled (no `nobrl`). Instead (`MSCRAPER_CHECKPOINT_MODE=snapshot`, set in the job):

| Step | What happens |
|---|---|
| Work | SQLite runs on a local file (`/tmp/mscraper-work/...`). It is never trusted after a restart and is always rebuilt from the share. |
| Flush | After a committed transaction (at most every 5 s), always at the end of a run, and before publication: SQLite online backup, then `PRAGMA integrity_check`, then `checkpoint.snap-<seq>.sqlite` written under a temp name and renamed, then `checkpoint.manifest.json` (`seq`, file, SHA-256, bytes, integrity) written under a temp name and renamed. **This rename is the commit point.** Then the previous snapshot is deleted. |
| Crash at any step | The previous manifest still points at the previous snapshot, which still exists. |
| Restore (every open) | The manifest must parse, its snapshot must exist, match the SHA-256 and pass `integrity_check`. Then it is copied to local disk. Any mismatch raises `CheckpointError`: the run is refused, not silently restarted. |
| Lost work | At most the pages committed in the last ~5 s before a crash are fetched again. A page and its listing pointer are one transaction, so a re-fetched page is never stored twice. Those requests count against the budget like any other. |

Test: `test_snapshot_checkpoint_survives_hard_kill_and_resumes_without_loss_or_duplicates`. A separate process is
killed with `os._exit(137)` on its 6th provider response, with no `finally` and no flush. A new "container" with
an empty local directory restores from the share and finishes. The published records are identical to an
uninterrupted reference run, with no duplicates, and fewer requests than the reference. Also covered:
`test_corrupt_or_inconsistent_snapshot_fails_closed` (damaged bytes, missing snapshot, unreadable manifest, a newer
uncommitted snapshot ignored) and `test_snapshot_mode_refuses_an_unmanifested_direct_database`.

## 5. Hashes

`SOURCE_FINGERPRINT.txt` and every report record:
* `code_sha256` (src/mscraper/*.py, unchanged meaning)
* `release_sha256`: src + config + deploy + requirements + Dockerfile, line endings normalised
* `deploy_sha256`: deploy/ only
* the SHA-256 of `main.bicep`

`run_test.sh collect` writes `timestamps.json`, which keeps Azure's own execution start/end separate from this
controller's start and collection times.
