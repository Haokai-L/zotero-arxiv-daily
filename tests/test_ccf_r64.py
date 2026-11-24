"""R6-4 mock-CAS and write-allowlist tests; no GitHub network required."""
import base64,copy,hashlib,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import ccf_r64_remote_store as remote
from ccf_send_engine import ProductionLedgerStore,REPO,DEV
from ccf_r63_delivery import (empty_ledger,prepare_batch,begin_attempt,
                              recover_after_crash,SafetyError,check_ledger)

class FakeTransport:
    def __init__(self):
        self.doc=None
        self.version=0
        self.fail=False
        self.tamper_read=False
    def request(self,method,route,payload=None):
        if self.fail:
            raise remote.PersistenceError("mock outage")
        if method=="GET":
            if self.doc is None:return None
            contents=self.doc
            if self.tamper_read:contents=b'{"schema_version":2}'
            return {"sha":hashlib.sha1(b"blob "+str(len(self.doc)).encode()+b"\0"+self.doc).hexdigest(),
                "content":base64.b64encode(contents).decode("ascii"),"encoding":"base64"}
        if method=="PUT":
            expected=payload.get("sha")
            current=self.request("GET",route)
            if (current is None and expected is not None) or (current is not None and
                expected != current["sha"]):
                raise remote.CASConflict("mock conflict")
            self.doc=base64.b64decode(payload["content"])
            self.version+=1
            return {"content":{"sha":self.request("GET",route)["sha"]}}
        raise AssertionError("Unsupported method")

class RemoteSafety(unittest.TestCase):
    def setUp(self):
        self.transport=FakeTransport()
        self.transport.doc=remote.canonical_bytes(empty_ledger())
        self.store=ProductionLedgerStore(REPO,DEV,self.transport,writes_approved=True)
    def prepare(self):
        s=self.store.read()
        ledger=copy.deepcopy(s.ledger)
        prepare_batch(ledger,{"schema_version":1,"sent_keys":[]},
            [{"paper_key":"synthetic:a"}],"2026-11-23",b"<html/>")
        return self.store.write(ledger,s.sha,"prepare")
    def test_stale_write_conflict(self):
        old=self.store.read();new=self.prepare()
        with self.assertRaises(remote.CASConflict):
            self.store.write(old.ledger,old.sha,"stale")
        self.assertEqual(self.store.read().sha,new.sha)
    def test_crash_recovery(self):
        prepared=self.prepare()
        ledger=copy.deepcopy(prepared.ledger)
        task=next(iter(ledger["batches"]))
        begin_attempt(ledger,task)
        attempt=self.store.write(ledger,prepared.sha,"attempt")
        restart=copy.deepcopy(self.store.read().ledger)
        self.assertEqual(recover_after_crash(restart),1)
        self.store.write(restart,attempt.sha,"uncertain")
        self.assertEqual(self.store.read().ledger["batches"][task]["state"],"UNCERTAIN")
    def test_read_corruption_fails(self):
        self.transport.tamper_read=True
        with self.assertRaises(remote.PersistenceError):self.store.read()
    def test_outage_fails(self):
        self.transport.fail=True
        with self.assertRaises(remote.PersistenceError):self.store.read()
    def test_invalid_sha(self):
        with self.assertRaises(SafetyError):self.store.write(empty_ledger(),"bad","invalid")
    def test_readback_mismatch(self):
        class Tamper(FakeTransport):
            def request(self,method,route,payload=None):
                result=super().request(method,route,payload)
                if method=="PUT":self.doc=b'{"schema_version":1,"batches":{},"tampered":true}'
                return result
        t=Tamper();t.doc=remote.canonical_bytes(empty_ledger())
        store=ProductionLedgerStore(REPO,DEV,t,writes_approved=True)
        with self.assertRaises(remote.PersistenceError):store.write(empty_ledger(),store.read().sha,"test")
if __name__=="__main__":unittest.main()
