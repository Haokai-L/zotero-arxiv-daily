# R6: independent CCF source checks and three-day delivery replay

This workflow deliberately does **not** send email, configure cron, modify main,
change Secrets, or write persisted candidate state and sent history.

## R6-1 publisher/official identity checks
Run fresh Crossref DOI lookups for journal articles (ISSN, DOI series, title,
publication year, type, publisher) and for main-conference proceedings
(official conference-specific container, publisher, type, date and DOI; Springer
book volume whitelist). For USENIX and NDSS papers without DOI, require exact
accepted/technical-session listing URL and title.
Ambiguous records stay REVIEW. Network exceptions are API_ERROR.
This is a bounded deterministic 5-per-venue 2025-2026 audit only, not complete
verification of the 3418 candidate pool or fulltext review.
The original candidate state remains PRELIMINARY.

## R6-2 existing scorer + virtual success/failure/retry
Only independently verified records with genuine metadata-matched abstracts are
eligible. Score using upstream Zotero LocalReranker without changing its
formula or giving publication-date bonuses. Keep the reviewed maximum-three
and optional A-NRC soft slot.
Day 1 simulated success marks selected IDs as delivered in memory only.
Day 2 simulated mail failure does not mark them.
Day 3 retries the same selection. Assert no overlap after success, identical
retry on failure, and no persisted state mutation. This is not proof of real
SMTP delivery or durable atomic send history.

All audit files are downloadable from the Actions artifact for seven days.
Real email and production activation require explicit user approval later.
