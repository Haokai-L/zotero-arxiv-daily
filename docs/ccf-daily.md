# CCF A daily recommendation

The 16 CCF A networking/security venues are configured. Use only formal
journal/main proceedings records. The existing Zotero scorer reads only
A-NRC-Research and its children. All eligible available titles within the
current and preceding two calendar years are scored without a date bonus;
the top 80 are enriched with authentic abstracts and reranked using the
original abstract similarity formula. Final publisher/official verification
is mandatory; select up to three, with one optional near-top A-NRC paper.
The title shortlist is a cost limit, not exhaustive abstract ranking.
Discovery is bounded, not a complete three-year archive. Journal IDs remain
verified on every scan; add a verified annual conference map for new editions.
If the new year's map is absent, poll the most recent verified edition and
report the gap rather than failing solely on the calendar change.

## Development acceptance

Pushes to the feature branch run preview only. To send exactly one TEST batch,
select Actions > Test > Run workflow > feature/ccf-a-daily (not main).
Only this manually dispatched branch workflow may call SMTP. A successful
server acceptance is not proof of inbox delivery; inspect the inbox.
A batch on the same local day is not repeated. Uncertain delivery blocks
automatic retransmission. No schedule or production deployment is enabled.

## Data and maintenance

The candidate checkpoint is compact JSON, removes expired/accepted records,
and uses a checked non-force push to the development branch. The ledger stores
only identifiers, day, digest and state; it is the authoritative sent-key
source. The empty legacy sent-history file remains for compatibility with
retained collectors. Never commit private Zotero data, credentials, raw
mail content or temporary audit reports. The preview HTML expires in one day.
Temporary CSV/JSON output stays on the runner. Offline CI is separate from
daily execution. The old upstream arXiv workflow is untouched on main.
