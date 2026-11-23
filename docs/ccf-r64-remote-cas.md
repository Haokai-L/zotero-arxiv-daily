# R6-4: GitHub remote persistence safety test (NO EMAIL)

R6-4 proves that the GitHub Contents API can be used to durably persist the
R6-3 batch-state model on the feature branch, with optimistic file-version
checks and read-after-write verification.

## Restriction and purpose
The transport **only accepts** writes to
data/r64_probes/<github-run-id>-<attempt>.json on
feature/ccf-a-daily. All data are explicitly synthetic:
synthetic:r64:<run-id>:1,2,3. There are no real paper reservations, recipient
addresses, API-key values or emails, and no SMTP/import or scheduled trigger.
The production files data/ccf_delivery_ledger.json and
data/ccf_sent_history.json remain byte-identical.

## Actual remote GitHub probe
Each run uses a unique test-only file. Distinct GitHub Actions steps (distinct
Python processes) create the file, write PREPARED, then ATTEMPTING with the
expected blob SHA and reread each committed version. An intentionally stale
PREPARED write must be rejected by GitHub with 409/422, and the newer
ATTEMPTING state must remain intact. A later process simulates a crash by
converting ATTEMPTING to UNCERTAIN, persists that version, then another fresh
process checks that auto-retry and new batch creation are blocked.

The workflow uses GitHub Actions concurrency to serialize R6-4 probe runs.
Each probe belongs to one run_id + run_attempt so replay does not reset a
previous uncertain state. Multiple runs can leave distinct synthetic probe
files for audit; none are production sent-history entries.

## Limits — no production activation
A successful probe verifies remote API persistence and stale-write rejection
for a single test-file sequence. It does NOT prove concurrent production
writers under simultaneous races, exactly-once SMTP delivery, live mailbox
receipt, or end-to-end transactional orchestration.
A production sender must explicitly reread durable ATTEMPTING and obtain a
verified commit before making any network handoff; if remote writes cannot be
confirmed it must stop. The default-branch cron remains untouched.
Actual test emails and production scheduling require separate user approval.
