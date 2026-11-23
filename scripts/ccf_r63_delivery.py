"""R6-3 fail-closed CCF delivery ledger; NO SMTP import or sending.

Every outbound paper batch must have independent source verification,
authentic abstract and genuine upstream Zotero score. This module provides
a local, atomically durable state machine but deliberately cannot send email.
Production deployment must remotely commit ATTEMPTING before network handoff.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from datetime import date
from pathlib import Path

from ccf_recommend_core import choose, normalize_title
from ccf_r6_verify import normdoi, safe_link

VERSION = 1
VERIFIED = {"VERIFIED_PUBLISHER", "VERIFIED_OFFICIAL"}
STATES = {"PREPARED", "ATTEMPTING", "SMTP_ACCEPTED",
          "FAILED_BEFORE_HANDOFF", "UNCERTAIN"}
PENDING = {"PREPARED", "ATTEMPTING", "FAILED_BEFORE_HANDOFF", "UNCERTAIN"}


class SafetyError(ValueError):
    pass


def empty_ledger():
    return {"schema_version": VERSION, "batches": {}}


def check_ledger(ledger):
    if ledger.get("schema_version") != VERSION or not isinstance(ledger.get("batches"), dict):
        raise SafetyError("Unrecognized delivery-ledger schema")
    all_keys = set()
    for task_id, record in ledger["batches"].items():
        if record.get("id") != task_id or record.get("state") not in STATES:
            raise SafetyError("Corrupt batch id or state")
        if not isinstance(record.get("keys"), list) or not 1 <= len(record["keys"]) <= 3:
            raise SafetyError("Invalid batch size")
        if any(not isinstance(k, str) or not k for k in record["keys"]):
            raise SafetyError("Invalid paper identifier")
        if len(set(record["keys"])) != len(record["keys"]):
            raise SafetyError("Duplicate keys inside batch")
        if all_keys.intersection(record["keys"]):
            raise SafetyError("Paper present in multiple batches")
        all_keys.update(record["keys"])
        try:
            date.fromisoformat(record["day"])
        except (KeyError, TypeError, ValueError) as e:
            raise SafetyError("Invalid batch day") from e
        if not isinstance(record.get("attempts"), int) or record["attempts"] < 0:
            raise SafetyError("Invalid attempts")
        if not isinstance(record.get("content_sha256"), str) or len(record["content_sha256"]) != 64:
            raise SafetyError("Invalid content hash")
    return ledger


def load_ledger(path):
    path = Path(path)
    return check_ledger(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else empty_ledger()


def atomic_store(path, ledger):
    """Local crash safety only. Does not replace a remote GitHub commit."""
    check_ledger(ledger)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=".ledger-", suffix=".tmp",
            delete=False
        ) as tmp:
            tmp_path = Path(tmp.name)
            os.chmod(tmp_path, 0o600)
            json.dump(ledger, tmp, ensure_ascii=False, indent=2, sort_keys=True)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
        if hasattr(os, "O_DIRECTORY"):
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def history_keys(history):
    if history.get("schema_version") != 1 or not isinstance(history.get("sent_keys"), list):
        raise SafetyError("Invalid legacy sent history")
    keys = history["sent_keys"]
    if not all(isinstance(k, str) and k for k in keys) or len(keys) != len(set(keys)):
        raise SafetyError("Bad or duplicate legacy sent keys")
    return set(keys)


def accepted_keys(ledger, history):
    check_ledger(ledger)
    return history_keys(history) | {
        key for task in ledger["batches"].values()
        if task["state"] == "SMTP_ACCEPTED" for key in task["keys"]
    }


def reserved_keys(ledger, history):
    """All prepared, uncertain, failed, and accepted paper IDs stay reserved."""
    check_ledger(ledger)
    return history_keys(history) | {
        key for task in ledger["batches"].values() for key in task["keys"]
    }


def source_verified(row, evidence):
    """Exact identity join: cannot merely attach a VERIFIED label to an unrelated paper."""
    if not evidence or evidence.get("publisher_verification") not in VERIFIED:
        return False
    if row.get("candidate_status") != "PRELIMINARY":
        return False
    if row.get("abstract_status") != "ABSTRACT_VERIFIED_METADATA":
        return False
    if len(str(row.get("abstract") or "").strip()) < 90:
        return False
    if not safe_link(row.get("paper_url")):
        return False
    try:
        score = float(row["score"])
    except (KeyError, ValueError, TypeError):
        return False
    if not math.isfinite(score):
        return False
    for key in ("paper_key", "venue", "field", "year"):
        if not row.get(key) or str(row.get(key)) != str(evidence.get(key)):
            return False
    if normalize_title(row.get("title")) != normalize_title(evidence.get("title")):
        return False
    doi = normdoi(row.get("doi"))
    if doi != normdoi(evidence.get("doi")):
        return False
    if str(row.get("paper_url", "")).rstrip("/") != str(evidence.get("paper_url", "")).rstrip("/"):
        return False
    if doi:
        if row["paper_key"] != "doi:" + doi:
            return False
        if evidence["publisher_verification"] != "VERIFIED_PUBLISHER":
            return False
        if not str(evidence.get("verification_evidence") or "").startswith(
            "https://api.crossref.org/works/" + doi
        ):
            return False
    else:
        if evidence["publisher_verification"] != "VERIFIED_OFFICIAL":
            return False
        if row["venue"] not in {"NSDI", "NDSS", "USENIX_SECURITY"}:
            return False
        if row["paper_key"] != "url:" + row["paper_url"].rstrip("/"):
            return False
        if not safe_link(evidence.get("verification_evidence")):
            return False
    return True


def select_sendable(scored, verified_rows, whitelist, history, ledger):
    """Gate BEFORE original choose(); an unverified top rank cannot displace verified work."""
    if len(whitelist) != 16:
        raise SafetyError("Expected 16 trusted formal CCF source labels")
    if any(batch["state"] in PENDING for batch in ledger["batches"].values()):
        raise SafetyError("Pending or uncertain send requires reconciliation before new selection")
    verified = {row.get("paper_key"): row for row in verified_rows
                if row.get("publisher_verification") in VERIFIED}
    skip = {}
    sendable = []
    blocked = reserved_keys(ledger, history)
    for row in scored:
        key = row.get("paper_key")
        if key in blocked:
            skip["RESERVED_OR_SENT"] = skip.get("RESERVED_OR_SENT", 0) + 1
            continue
        venue = row.get("venue")
        if venue not in whitelist or row.get("field") != whitelist[venue]["field"]:
            skip["NOT_CCF_WHITELIST"] = skip.get("NOT_CCF_WHITELIST", 0) + 1
            continue
        if not source_verified(row, verified.get(key)):
            skip["NOT_INDEPENDENTLY_VERIFIED"] = skip.get("NOT_INDEPENDENTLY_VERIFIED", 0) + 1
            continue
        sendable.append(row)
    result = choose(sendable, sent_keys=blocked, limit=3)
    if not result["selected"]:
        raise SafetyError("No eligible publisher-verified paper with real score and abstract")
    result["source_gate"] = "PUBLISHER_VERIFIED_BEFORE_RANKING"
    result["source_verified_count"] = len(sendable)
    result["skipped"] = skip
    result["email_sent"] = False
    return result


def _require_state(ledger, task_id, expected):
    check_ledger(ledger)
    batch = ledger["batches"].get(task_id)
    if batch is None or batch["state"] not in expected:
        raise SafetyError("Invalid delivery state transition")
    return batch


def prepare_batch(ledger, history, selected, day, html_bytes):
    """Immutable task identity + exact finalized message digest, no sending."""
    check_ledger(ledger)
    history_keys(history)
    if not isinstance(html_bytes, bytes) or not html_bytes:
        raise SafetyError("Message HTML bytes must be finalized before prepare")
    if not 1 <= len(selected) <= 3:
        raise SafetyError("Only 1 to 3 papers per day")
    date.fromisoformat(day)
    keys = [str(r.get("paper_key") or "") for r in selected]
    if not all(keys) or len(set(keys)) != len(keys):
        raise SafetyError("Invalid or duplicate selected paper keys")
    if set(keys).intersection(reserved_keys(ledger, history)):
        raise SafetyError("Already reserved or sent paper")
    if any(batch["day"] == day for batch in ledger["batches"].values()):
        raise SafetyError("Another batch already exists for this day")
    if any(batch["state"] in PENDING for batch in ledger["batches"].values()):
        raise SafetyError("A pending/uncertain batch must be resolved first")
    key_material = json.dumps([day, sorted(keys)], ensure_ascii=False, separators=(",", ":"))
    task_id = hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:24]
    if task_id in ledger["batches"]:
        raise SafetyError("Batch id collision")
    batch = {
        "id": task_id, "day": day, "keys": sorted(keys), "attempts": 0,
        "content_sha256": hashlib.sha256(html_bytes).hexdigest(),
        "state": "PREPARED", "last_event": "PREPARED_OFFLINE",
        "smtp_ack": False
    }
    ledger["batches"][task_id] = batch
    check_ledger(ledger)
    return task_id


def begin_attempt(ledger, task_id):
    """MUST be durably committed remotely BEFORE eventual SMTP handoff."""
    batch = _require_state(ledger, task_id, {"PREPARED", "FAILED_BEFORE_HANDOFF"})
    batch["attempts"] += 1
    batch["state"] = "ATTEMPTING"
    batch["last_event"] = "HANDOFF_MAY_HAVE_STARTED"
    return batch


def smtp_accepted(ledger, task_id, explicit_ack):
    """Only after the mail server explicitly accepts submission, not inbox delivery."""
    batch = _require_state(ledger, task_id, {"ATTEMPTING"})
    if explicit_ack is not True:
        raise SafetyError("SMTP acceptance cannot be inferred")
    batch["state"] = "SMTP_ACCEPTED"
    batch["smtp_ack"] = True
    batch["last_event"] = "SERVER_ACCEPTED_SUBMISSION"
    return batch


def definite_failure_before_handoff(ledger, task_id):
    """Caller must prove SMTP DATA/mail handoff could not have happened."""
    batch = _require_state(ledger, task_id, {"ATTEMPTING"})
    batch["state"] = "FAILED_BEFORE_HANDOFF"
    batch["last_event"] = "FAILED_WITH_PROVEN_NO_HANDOFF"
    return batch


def uncertain(ledger, task_id):
    batch = _require_state(ledger, task_id, {"ATTEMPTING"})
    batch["state"] = "UNCERTAIN"
    batch["last_event"] = "UNKNOWN_OUTCOME_MANUAL_RECONCILIATION_REQUIRED"
    return batch


def recover_after_crash(ledger):
    """Any persisted in-flight attempt is UNKNOWN, never auto-resend."""
    check_ledger(ledger)
    changed = 0
    for batch in ledger["batches"].values():
        if batch["state"] == "ATTEMPTING":
            batch["state"] = "UNCERTAIN"
            batch["last_event"] = "RESTART_WITHOUT_ACCEPTANCE_PROOF"
            changed += 1
    return changed


def reconcile_uncertain(ledger, task_id, outcome, evidence):
    """Explicit/manual reconciliation only; never invoked by a timer."""
    batch = _require_state(ledger, task_id, {"UNCERTAIN"})
    if not isinstance(evidence, str) or len(evidence.strip()) < 12:
        raise SafetyError("Evidence note required for manual reconciliation")
    if outcome == "ACCEPTED":
        batch["state"] = "SMTP_ACCEPTED"
        batch["smtp_ack"] = True
    elif outcome == "PROVEN_NOT_HANDED_OFF":
        batch["state"] = "FAILED_BEFORE_HANDOFF"
    else:
        raise SafetyError("Unknown manual outcome")
    batch["last_event"] = "MANUAL_RECONCILIATION_" + outcome
    batch["manual_evidence_note"] = evidence[:400]
    return batch
