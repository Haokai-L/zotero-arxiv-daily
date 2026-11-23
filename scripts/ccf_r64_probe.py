"""R6-4 isolated remote GitHub persistence probe; strictly NO SMTP.

Commands are run as separate GitHub Actions steps/processes, proving
cross-process remote durability. Never use production history or ledger as
write destinations.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

from ccf_r63_delivery import (
    SafetyError, empty_ledger, prepare_batch, begin_attempt,
    recover_after_crash, reserved_keys, check_ledger, reconcile_uncertain,
)
from ccf_r64_remote_store import (
    BRANCH, CASConflict, GithubTransport, ProbeStore, sha256_file
)

def make_store(args):
    return ProbeStore(args.repo, BRANCH, args.probe, GithubTransport(
        os.environ.get("GITHUB_TOKEN", "")
    ))

def synthetic_rows(run_id):
    # NOT real DOI, publisher verification, user recommendations, or mail!
    return [{"paper_key": "synthetic:r64:" + run_id + ":" + str(i)}
            for i in range(1, 4)]

def synthetic_message(run_id):
    return ("<html><body>R6-4 SYNTHETIC TEST ONLY " +
            run_id + " NO EMAIL</body></html>").encode("utf-8")

def inspect(snapshot, state):
    check_ledger(snapshot.ledger)
    batches=list(snapshot.ledger["batches"].values())
    if len(batches) != 1 or batches[0]["state"] != state:
        raise SafetyError("Remote state mismatch; expected " + state)
    if batches[0]["attempts"] != (0 if state=="PREPARED" else 1):
        raise SafetyError("Remote attempt counter mismatch")
    if len(reserved_keys(snapshot.ledger, {"schema_version": 1, "sent_keys": []})) != 3:
        raise SafetyError("Reserved paper IDs mismatch")
    return batches[0]

def execute(args):
    store=make_store(args)
    history={"schema_version":1,"sent_keys":[]}
    if args.command=="init":
        if store.read() is not None:
            raise SafetyError("Probe already exists; never reset a prior attempt")
        result=store.write(empty_ledger(),None,"initialize isolated synthetic ledger")
        if result.ledger["batches"]:
            raise SafetyError("New probe must be empty")
        return {"step":"init","sha":result.sha,"batch_count":0}
    snap=store.read()
    if snap is None:
        raise SafetyError("Probe not initialized; fail closed")
    if args.command=="prepare":
        if snap.ledger["batches"]:
            raise SafetyError("Cannot prepare a second batch")
        ledger=snap.ledger
        task=prepare_batch(ledger,history,synthetic_rows(args.run_id),
                           "2026-11-23",synthetic_message(args.run_id))
        result=store.write(ledger,snap.sha,"persist prepared probe batch")
        batch=inspect(result,"PREPARED")
        if args.stale_sha:
            Path(args.stale_sha).write_text(result.sha+"\n",encoding="ascii")
        return {"step":"prepare","sha":result.sha,"batch_id":task,
                "state":batch["state"],"attempts":batch["attempts"]}
    if args.command=="attempt":
        batch=inspect(snap,"PREPARED")
        begin_attempt(snap.ledger,batch["id"])
        result=store.write(snap.ledger,snap.sha,"persist attempted handoff without SMTP")
        checked=inspect(result,"ATTEMPTING")
        return {"step":"attempt","sha":result.sha,
                "state":checked["state"],"attempts":checked["attempts"]}
    if args.command=="stale":
        if not args.stale_sha:
            raise SafetyError("Stale expected SHA file required")
        prior=Path(args.stale_sha).read_text(encoding="ascii").strip()
        # The actual remote content must be ATTEMPTING. A stale write may
        # NEVER be allowed to roll it back to PREPARED.
        batch=inspect(snap,"ATTEMPTING")
        rollback=empty_ledger()
        prepare_batch(rollback,history,synthetic_rows(args.run_id),
                      "2026-11-23",synthetic_message(args.run_id))
        try:
            store.write(rollback,prior,"stale-write-conflict-should-be-rejected")
        except CASConflict:
            outcome="STALE_VERSION_REJECTED"
        else:
            raise SafetyError("CRITICAL: stale update was not rejected")
        persisted=store.read()
        inspect(persisted,"ATTEMPTING")
        if persisted.sha!=snap.sha:
            raise SafetyError("Stale write changed the remote version")
        return {"step":"stale","result":outcome,"current_sha":persisted.sha}
    if args.command=="recover":
        inspect(snap,"ATTEMPTING")
        if recover_after_crash(snap.ledger)!=1:
            raise SafetyError("Expected exactly one in-flight attempt")
        result=store.write(snap.ledger,snap.sha,"recover crash into uncertain state")
        batch=inspect(result,"UNCERTAIN")
        return {"step":"recover","sha":result.sha,"state":batch["state"]}
    if args.command=="verify":
        batch=inspect(snap,"UNCERTAIN")
        if recover_after_crash(snap.ledger)!=0:
            raise SafetyError("Uncertain state must remain stable across restarts")
        try:
            begin_attempt(snap.ledger,batch["id"])
        except SafetyError:
            blocked=True
        else:
            blocked=False
        if not blocked:raise SafetyError("Uncertain batch was incorrectly retryable")
        try:
            prepare_batch(snap.ledger,history,synthetic_rows(args.run_id),
                          "2026-11-24",b"<html>synthetic</html>")
        except SafetyError:
            new_batch_blocked=True
        else:
            new_batch_blocked=False
        if not new_batch_blocked:raise SafetyError("Pending batch did not block new batch")
        again=store.read()
        inspect(again,"UNCERTAIN")
        if snap.sha!=again.sha:
            raise SafetyError("Read-only verification unexpectedly mutated remote state")
        return {"step":"verify","sha":again.sha,"state":batch["state"],
                "auto_retry_blocked":blocked,
                "new_batch_blocked":new_batch_blocked}
    raise SafetyError("Unknown probe command")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("command",choices=["init","prepare","attempt","stale","recover","verify"])
    p.add_argument("--repo",required=True)
    p.add_argument("--probe",required=True)
    p.add_argument("--run-id",required=True)
    p.add_argument("--stale-sha",type=Path)
    args=p.parse_args()
    result=execute(args)
    print("R64_GITHUB_PROBE "+json.dumps(result,sort_keys=True),flush=True)
if __name__=="__main__":main()
