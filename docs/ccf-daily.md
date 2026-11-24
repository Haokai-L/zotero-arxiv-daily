# CCF A daily recommendation

Production: main branch, Actions > CCF Daily Papers. Scheduled at 22:00 UTC
(06:00 next day Asia/Taipei). GitHub may delay scheduled starts. Manual
dispatch on main uses the same daily path, not an extra email. A date already
recorded in the ledger, including the accepted TEST on 2026-11-24, is skipped.
No arXiv workflow, separate TEST workflow or daily audit artifact is needed.

16 configured CCF A networking/security venues; formal publications only.
Incremental discovery is bounded, not an exhaustive archive. Candidate dates
are restricted to the current and preceding two calendar years. Rank available
titles against A-NRC-Research and descendants using the upstream Zotero
reranker, enrich up to 80 candidates with authentic abstracts, rerank and
verify publisher/proceedings identity. Select up to three with an optional
near-top A-NRC paper, then produce Chinese summaries through DeepSeek.
There is no publication-date bonus. Annual conference mappings need verified
updates; without a new mapping the last verified edition remains polled.

Only two persistent data files: rolling candidate metadata and the delivery
ledger. Accepted and expired candidates are pruned on subsequent refreshes;
accepted paper IDs remain reserved in the ledger. Remote candidate checkpoint
is non-force; remote PREPARED and ATTEMPTING must be confirmed before SMTP.
An unresolved send blocks new submission: check inbox and reconcile before
retrying. The original TEST ledger is preserved. Temporary reports and HTML
are not uploaded. CI is for relevant pull requests or manual maintenance,
not daily mail. Old workflow run history is GitHub-managed separately.

For upstream changes, merge deliberately into a development branch based on
current main and review conflicts; do not discard customization or reset the
production ledger. Keep backup branches intact. Do not commit credentials,
private Zotero abstracts, recipient details, or mail bodies.
