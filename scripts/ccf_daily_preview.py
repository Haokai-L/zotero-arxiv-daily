"""One consolidated end-to-end CCF preview entrypoint.

Reads a newly publisher-verified bounded sample and genuine OpenAlex abstracts,
uses the unchanged upstream Zotero reranker and the existing R6-3 final gate,
creates a DeepSeek HTML preview, then rehearses crash recovery in memory only.
No SMTP, no cron, no GitHub write, no persistent history/ledger mutations.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path

import yaml
from ccf_recommend_preview import original_rerank, read_corpus
from ccf_r63_delivery import (
    SafetyError, begin_attempt, check_ledger, empty_ledger,
    history_keys, prepare_batch, recover_after_crash, select_sendable,
)
from ccf_r5_mail import build as make_mail

ROOT = Path(__file__).resolve().parents[1]


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def assemble(verified_path, enriched_path, history_path, ledger_path,
             whitelist_path, mail_config_path, output_dir, *, corpus=None, env=None):
    """Explicitly require independently verified evidence before personalized ranking."""
    history_path, ledger_path = Path(history_path), Path(ledger_path)
    history_before, ledger_before = history_path.read_bytes(), ledger_path.read_bytes()
    history, ledger = json.loads(history_before), json.loads(ledger_before)
    history_keys(history)
    check_ledger(ledger)
    whitelist = yaml.safe_load(Path(whitelist_path).read_text(encoding="utf-8"))["venues"]
    verified_rows = read_csv(verified_path)
    independently_verified = {
        r["paper_key"]: r for r in verified_rows
        if r.get("publisher_verification") in ("VERIFIED_PUBLISHER", "VERIFIED_OFFICIAL")
    }
    if not independently_verified:
        raise SafetyError("Zero independently publisher-verified candidates")
    enriched = [
        r for r in read_csv(enriched_path)
        if r.get("paper_key") in independently_verified
        and r.get("abstract_status") == "ABSTRACT_VERIFIED_METADATA"
    ]
    if not enriched:
        raise SafetyError("No publisher-verified records with genuine abstracts")
    corpus = corpus if corpus is not None else read_corpus()
    corpus = sorted(corpus, key=lambda p:p.added_date, reverse=True)[:150]
    if len(corpus) < 2:
        raise SafetyError("Insufficient real Zotero corpus")
    scored = original_rerank(enriched, corpus)
    selected_result = select_sendable(
        scored, verified_rows, whitelist, history, ledger
    )
    # Retain proof with each selected paper for accurate human-facing labeling.
    for item in selected_result["selected"]:
        proof = independently_verified[item["paper_key"]]
        item["publisher_verification"] = proof["publisher_verification"]
        item["verification_evidence"] = proof["verification_evidence"]
        item["verification_reason"] = proof.get("verification_reason", "")
    config = yaml.safe_load(Path(mail_config_path).read_text(encoding="utf-8"))
    if config.get("send_enabled") is not False or config.get("preview_only") is not True:
        raise SafetyError("Preview configuration has unsafe send settings")
    output_dir = Path(output_dir)
    result = make_mail(selected_result, config, whitelist, output_dir, env=env)
    rendered = (output_dir / "email_preview.html").read_bytes()
    # No persisted state is written: exercise crash semantics in an isolated ledger.
    simulated = empty_ledger()
    day = result["date"]
    task_id = prepare_batch(simulated, history, selected_result["selected"], day, rendered)
    begin_attempt(simulated, task_id)
    if recover_after_crash(simulated) != 1:
        raise SafetyError("In-flight crash should become UNCERTAIN")
    if simulated["batches"][task_id]["state"] != "UNCERTAIN":
        raise SafetyError("Crash recovery did not stop subsequent mail attempts")
    try:
        select_sendable(scored, verified_rows, whitelist, history, simulated)
    except SafetyError:
        retry_blocked = True
    else:
        retry_blocked = False
    if not retry_blocked:
        raise SafetyError("CRITICAL: unknown delivery attempt was retryable")
    if history_path.read_bytes() != history_before or ledger_path.read_bytes() != ledger_before:
        raise SafetyError("Persistent state was unexpectedly modified")
    audit = {
        "stage": "CONSOLIDATED_CCF_PREVIEW",
        "source_verified_input": len(independently_verified),
        "authentic_abstracts": len(enriched),
        "zotero_corpus_count_used": len(corpus),
        "eligible_scored_count": selected_result["source_verified_count"],
        "selected_count": len(selected_result["selected"]),
        "deepseek_generated": result["deepseek_generated"],
        "publisher_verification": "REQUIRED_BEFORE_SELECTION",
        "anrc_soft_slot": True,
        "publication_date_score_bonus": False,
        "source_skips": selected_result["skipped"],
        "simulated_crash_recovered_state": "UNCERTAIN",
        "simulated_auto_retry_blocked": retry_blocked,
        "history_unchanged": True,
        "delivery_ledger_unchanged": True,
        "history_sha256": hashlib.sha256(history_before).hexdigest(),
        "delivery_ledger_sha256": hashlib.sha256(ledger_before).hexdigest(),
        "preview_only": True,
        "email_sent": False,
        "production_ready": False,
        "limitations": [
            "Source audit is a bounded per-venue sample, not the entire candidate catalog.",
            "GitHub remote CAS and SMTP are not connected to a production sender.",
            "No schedule or actual email was configured or triggered."
        ],
    }
    (output_dir / "consolidated_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("CCF_CONSOLIDATED_PREVIEW " + json.dumps(audit, ensure_ascii=False), flush=True)
    return audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verified", type=Path, required=True)
    parser.add_argument("--enriched", type=Path, required=True)
    parser.add_argument("--history", type=Path, default=ROOT / "data/ccf_sent_history.json")
    parser.add_argument("--ledger", type=Path, default=ROOT / "data/ccf_delivery_ledger.json")
    parser.add_argument("--whitelist", type=Path, default=ROOT / "config/ccf_a_venues.yaml")
    parser.add_argument("--mail-config", type=Path, default=ROOT / "config/ccf_r5_mail.yaml")
    parser.add_argument("--out-dir", type=Path, default=Path("ccf-daily-preview"))
    args = parser.parse_args()
    assemble(args.verified, args.enriched, args.history, args.ledger,
             args.whitelist, args.mail_config, args.out_dir)


if __name__ == "__main__":
    main()
