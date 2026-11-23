# CCF A-tier daily recommendation — consolidated development status

## Rules (unchanged)
- Restrict paper candidates to the 16 CCF 2026 A-tier journal/conference venues in networking and network/information security; never use preprint-only sources.
- Verify publisher/main-proceedings identity *per paper* before selection, and obtain authenticated metadata-matched abstracts.
- Reuse original upstream Zotero LocalReranker cosine-weighted scores, without publication-date boosts.
- Select up to 3 papers; prefer one A-NRC-related paper only when sufficiently well ranked; no guaranteed quota.
- Use verified DeepSeek for Chinese abstract summaries when configured.
- **Do not send email, schedule mail, or modify sent-history/production ledger until explicit separate approval.**

## What runs now
One integrated read-only developer preview workflow, .github/workflows/ccf-daily-preview.yml:
1. Offline regression tests and immutable data checksums.
2. Independently verify a bounded sample of 2025–2026 papers (up to five per venue) using R6 publisher/official identity checks.
3. Enrich actual abstracts using OpenAlex, call unchanged upstream Zotero scoring, and filter by the independent proof gate.
4. Produce no-send Chinese HTML/JSON, simulate an interrupted send with a *temporary in-memory ledger* and assert auto-retry is blocked.
5. Publish a seven-day preview artifact.

The historical candidate state is maintained separately; this workflow neither polls nor modifies it. Current 2026-only incremental source configuration needs yearly maintenance and does not cover all three years completely. Past historical workflows and test-only probes are preserved in backup/pre-consolidation-20261123.

## Before sending emails
The integrated no-send preview is not a scheduled production recommender. Still required:
- Wire reliable incremental discovery into the deployable default-branch job and ensure per-final-paper verification.
- Connect the GitHub remote CAS state store to the real SMTP transaction with safe uncertain-outcome handling.
- Obtain user approval for one real TEST email; later obtain independent approval for automated daily mail.

Do not store unverified "sent" markers or claim mailbox delivery from SMTP acceptance alone.

## Consolidation and cleanup completed on 2026-11-23

The active feature branch retains only **two CCF Actions**:
`ccf-daily-preview.yml` (read-only, manual no-email acceptance)
and `ccf-safety-ci.yml` (offline regression). Nine obsolete stage-specific
workflows and seven repetitive stage documents were removed, along with
four no-longer-used scripts/test files and one synthetic GitHub probe JSON.
The full pre-cleanup snapshot is preserved as
`backup/pre-consolidation-20261123`.

Important: This cleanup does **not** implement scheduled discovery or SMTP
sending. `ccf_incremental.py` remains as a reusable acquisition module;
the consolidated read-only preview currently reads the durable candidate
snapshot and independently verifies sampled final candidates.

## Data minimization (2026-11-23)

Temporary CSV/JSON verification audits remain only on the ephemeral GitHub Actions
runner and are **not uploaded** by the consolidated preview. Only the HTML
preview is retained as a GitHub Actions artifact, with a 1-day retention
period. Previously uploaded artifacts have their own existing expiry times.
The operational candidate snapshot, sent-history keys and delivery ledger
must be preserved for incremental discovery, deduplication and crash safety.
No production email sending or daily schedule is enabled by this change.
