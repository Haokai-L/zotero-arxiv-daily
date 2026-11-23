# R3-4a: Auditable Unified CCF Candidate Pool (Preview)

**Scope: bounded previews, NOT a complete 2024–2026 database.**

This program combines the prior successful R3-2 and R3-3 audit artifacts:

- Journals: GitHub Actions run `45035234003`, artifact `ccf-journal-r32-audit`.
- Conferences: GitHub Actions run `45105461913`, artifact `ccf-conference-r33-audit`.

The input artifacts expire seven days after creation; the workflow uses pinned run IDs for reproducibility, and **is not a production recurring update job**.

## Output contract

- `candidates_preliminary.csv` and `.jsonl`: quality-filtered **candidates**, NOT verified CCF A paper declarations.
- `candidates_review.csv`: sources or records needing human verification.
- `candidates_excluded.csv`: records rejected by source filtering or basic integrity checks.
- `candidates_duplicates.csv`: exact DOI or no-DOI same-venue/year/title duplicates.
- `coverage_audit.json`: record reconciliation, venue breakdown, *incomplete* year coverage, and provenance limitations.

Records retain venue, networking/security field, year and date precision, DOI or official URL, source record ID, evidence URL and prior-stage status. Blank `pdf_url` means **unknown**, not a broken PDF link.

The 16 venues are drawn from `config/ccf_a_venues.yaml`. Journal inputs are restricted to at most the latest 30 records per mapped source, while conference inputs cover **2025 only** (Crossref first 40 search results or official conference technical-session links). Missing entries cannot be interpreted as evidence that the venue published nothing.

## Remaining engineering tasks before daily email

1. Verify each source and candidate paper against publisher/Crossref or official proceedings.
2. Obtain **complete 2024 and 2026 conference records** and paginate journals and conference datasets; audit per-year completeness.
3. Add persistent storage for the candidate pool and sent-history registry; GitHub Actions artifacts are temporary.
4. Enrich author, abstract and PDF metadata when truly available.
5. Apply Zotero A-NRC semantic ranking and send a **maximum of 5 papers per day**, only after an explicit production enablement decision.

**No part of this workflow reads or changes Zotero, DeepSeek, email settings, GitHub Secrets or the `main` branch.**
