# R5: Chinese Paper Email Preview — No Send

This independent workflow uses the persisted R4-2 CCF **preliminary** paper state, never arXiv/bioRxiv/medRxiv as candidate discovery. It exports a bounded set of up to four DOI/official links per venue, enriches real OpenAlex abstracts, calls the unchanged upstream Zotero `LocalReranker`, and selects up to three with the previously reviewed soft A-NRC keyword slot. No freshness bonus, date ladder or age multiplier is applied.

It then builds `email_preview.html`, `email_preview.json`, and `summary_audit.json`. The public artifact contains paper metadata and **does not contain Zotero corpus abstracts**, email addresses, or API keys. The selected papers remain `PRELIMINARY` pending publisher-by-publisher verification.

When an official DeepSeek key is already configured in GitHub Secrets as `DEEPSEEK_API_KEY`, or `OPENAI_API_KEY` is configured with `OPENAI_API_BASE` pointing to `api.deepseek.com`, the workflow requests `deepseek-chat` for a short Chinese summary grounded strictly in the original abstract. Otherwise, it marks the summary `DEEPSEEK_NOT_CONFIGURED` and presents a truthful English abstract excerpt. It never fabricates a Chinese summary or labels another LLM as DeepSeek.

**Safety**: This workflow has `contents: read`, no SMTP step, no `send_email()` call, no schedule and no modifications to `data/ccf_sent_history.json`. The original daily mail workflow stays disabled. A green R5 result confirms HTML draft generation, not production readiness, fully verified CCF papers or delivery.
