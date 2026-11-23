# R6-3: publisher-verified final gate and no-send delivery safety

No SMTP calls, no e-mail, no cron, no Secrets edits, no modifications to main,
backup, sent history or the production delivery ledger. Job has read-only
permissions and runs only on feature/ccf-a-daily.

## Eligibility gate
A candidate must appear in an independent R6 Crossref/official-source
verification result and have the *same* DOI/key, title, venue, publication year,
field, official paper link, evidence URL and an authentic metadata-verified
abstract. The upstream Zotero score must be finite. A mere venue whitelist
label or PRELIMINARY status cannot bypass this gate. The original scoring
formula, A-NRC soft slot and at-most-three policy remain unchanged.
The demo uses the bounded, previously verified R6 artifact; it does not claim
that all 3418 candidates have been independently verified.

## Delivery state model
The canonical append-only-in-use delivery ledger holds each day's batch ID,
paper keys, finalized HTML digest, attempt count and one of:
PREPARED, ATTEMPTING, SMTP_ACCEPTED, FAILED_BEFORE_HANDOFF, UNCERTAIN.

- Persist PREPARED before attempting delivery.
- Persist ATTEMPTING **before** any SMTP/network handoff.
- Only an explicit mail-server acceptance can mark SMTP_ACCEPTED.
- If mail handoff may have happened but acknowledgement is missing, mark
  UNCERTAIN and stop automatic attempts pending human reconciliation.
- FAILED_BEFORE_HANDOFF is retryable only with proof that no message could
  have reached the server. A crash in ATTEMPTING becomes UNCERTAIN.
- All keys in every registered batch remain reserved, even if not accepted.
  The legacy ccf_sent_history.json is also checked and unioned.
- Local state writes are fsync+atomic-rename, with strong schema checks.
  GitHub-side CAS, concurrency control and sender integration are **not yet
  implemented**; a green result is not production SMTP transaction proof.

## Verification
Offline adversarial tests check forgery, domain filtering, duplicate keys,
lost acknowledgement, crash recovery, manual evidence, impossible state
transitions, atomic persistence and legacy history compatibility.

Real dry-run restores the earlier verified R6 sample, re-enriches authentic
abstracts, uses the original upstream Zotero reranker, selects only papers
through the publisher gate, then simulates an in-progress crash in an isolated
temporary ledger. Both production state files must remain byte-identical.

### Remaining authorization gates
Real SMTP test requires explicit user approval; activating a daily schedule
requires a separate explicit final approval. Both are still disabled.
