"""R6-3 safety tests: publisher gate, durable transitions, failure recovery."""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import ccf_r63_delivery as d

def paper(n=1,venue='TMC',score=6):
    doi='10.1109/tmc.2026.'+str(n)
    return dict(paper_key='doi:'+doi,doi=doi,venue=venue,field='networking',
        year='2026',title='Trusted Service Chain Recovery With Deadlines',
        paper_url='https://doi.org/'+doi,candidate_status='PRELIMINARY',
        abstract_status='ABSTRACT_VERIFIED_METADATA',
        abstract='This paper studies fault recovery, deadline constrained service chains and'
                 ' dependable network services and empirically evaluates the service restoration method.',
        score=score)

def evidence(row):
    return dict(row,publisher_verification='VERIFIED_PUBLISHER',
                verification_evidence='https://api.crossref.org/works/'+row['doi'])

def history(keys=None):return dict(schema_version=1,sent_keys=list(keys or []))
def whitelist():
    return dict(TMC={'field':'networking'},**{
        'VENUE'+str(i):{'field':'networking'} for i in range(15)})

class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.rows=[paper(i,score=10-i) for i in range(1,6)]
        self.proofs=[evidence(r) for r in self.rows]
        self.ledger=d.empty_ledger()
        self.history=history()
    def selected(self):
        return d.select_sendable(self.rows,self.proofs,whitelist(),self.history,self.ledger)['selected']
    def prepare(self):
        return d.prepare_batch(self.ledger,self.history,self.selected(),'2026-11-23',b'<html>test</html>')
    def test_gate_only_verified(self):
        result=d.select_sendable(self.rows,[self.proofs[0]],whitelist(),self.history,self.ledger)
        self.assertEqual(len(result['selected']),1)
        self.assertEqual(result['selected'][0]['paper_key'],self.rows[0]['paper_key'])
    def test_gate_mismatched_title_fails(self):
        f=dict(self.proofs[0],title='Unrelated Encryption Theory')
        with self.assertRaises(d.SafetyError):
            d.select_sendable([self.rows[0]],[f],whitelist(),self.history,self.ledger)
    def test_gate_wrong_doi_fails(self):
        f=dict(self.proofs[0],doi='10.1109/tmc.2026.999')
        with self.assertRaises(d.SafetyError):
            d.select_sendable([self.rows[0]],[f],whitelist(),self.history,self.ledger)
    def test_gate_wrong_evidence_url_fails(self):
        f=dict(self.proofs[0],verification_evidence='https://example.org/true')
        with self.assertRaises(d.SafetyError):
            d.select_sendable([self.rows[0]],[f],whitelist(),self.history,self.ledger)
    def test_gate_no_abstract_fails(self):
        r=dict(self.rows[0],abstract='a')
        with self.assertRaises(d.SafetyError):
            d.select_sendable([r],self.proofs,whitelist(),self.history,self.ledger)
    def test_gate_preprint_url_fails(self):
        r=dict(self.rows[0],paper_url='https://arxiv.org/abs/2601.1234')
        with self.assertRaises(d.SafetyError):
            d.select_sendable([r],self.proofs,whitelist(),self.history,self.ledger)
    def test_gate_no_score_fails(self):
        r=dict(self.rows[0],score=float('nan'))
        with self.assertRaises(d.SafetyError):
            d.select_sendable([r],self.proofs,whitelist(),self.history,self.ledger)
    def test_gate_sent_history_filters(self):
        self.history=history([self.rows[0]['paper_key']])
        result=self.selected()
        self.assertNotIn(self.rows[0]['paper_key'],{r['paper_key'] for r in result})
        self.assertEqual(len(result),3)
    def test_gate_does_not_use_date_bonus(self):
        result=self.selected()
        self.assertEqual([r['paper_key'] for r in result],[r['paper_key'] for r in self.rows[:3]])
    def test_max_three(self):
        self.assertEqual(len(self.selected()),3)
    def test_prepared_reserves(self):
        task=self.prepare()
        self.assertIn(task,self.ledger['batches'])
        self.assertEqual(self.ledger['batches'][task]['state'],'PREPARED')
        with self.assertRaises(d.SafetyError):self.selected()
    def test_crash_after_handoff_unknown(self):
        task=self.prepare()
        d.begin_attempt(self.ledger,task)
        self.assertEqual(d.recover_after_crash(self.ledger),1)
        self.assertEqual(self.ledger['batches'][task]['state'],'UNCERTAIN')
        with self.assertRaises(d.SafetyError):self.selected()
    def test_crash_after_acceptance_does_not_undo(self):
        task=self.prepare();d.begin_attempt(self.ledger,task)
        d.smtp_accepted(self.ledger,task,True)
        self.assertEqual(d.recover_after_crash(self.ledger),0)
        self.assertEqual(self.ledger['batches'][task]['state'],'SMTP_ACCEPTED')
    def test_no_fake_ack(self):
        task=self.prepare();d.begin_attempt(self.ledger,task)
        with self.assertRaises(d.SafetyError):d.smtp_accepted(self.ledger,task,False)
    def test_cannot_recover_uncertain_without_evidence(self):
        task=self.prepare();d.begin_attempt(self.ledger,task)
        d.uncertain(self.ledger,task)
        with self.assertRaises(d.SafetyError):d.reconcile_uncertain(self.ledger,task,'ACCEPTED','yes')
        with self.assertRaises(d.SafetyError):d.begin_attempt(self.ledger,task)
    def test_manual_reconciliation_accepted(self):
        task=self.prepare();d.begin_attempt(self.ledger,task);d.uncertain(self.ledger,task)
        d.reconcile_uncertain(self.ledger,task,'ACCEPTED','SMTP server delivery acknowledgement verified')
        self.assertEqual(self.ledger['batches'][task]['state'],'SMTP_ACCEPTED')
    def test_manual_confirmed_nonhandoff_can_retry(self):
        task=self.prepare();d.begin_attempt(self.ledger,task);d.uncertain(self.ledger,task)
        d.reconcile_uncertain(self.ledger,task,'PROVEN_NOT_HANDED_OFF',
                              'Connection failed before the SMTP DATA phase')
        d.begin_attempt(self.ledger,task)
        self.assertEqual(self.ledger['batches'][task]['attempts'],2)
    def test_failed_before_handoff(self):
        task=self.prepare();d.begin_attempt(self.ledger,task)
        d.definite_failure_before_handoff(self.ledger,task)
        self.assertEqual(self.ledger['batches'][task]['state'],'FAILED_BEFORE_HANDOFF')
    def test_reject_duplicate_date(self):
        task=self.prepare()
        with self.assertRaises(d.SafetyError):
            d.prepare_batch(self.ledger,self.history,[paper(44)],'2026-11-23',b'x')
    def test_atomic_persistence_crash_recovery(self):
        task=self.prepare()
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'journal.json'
            d.atomic_store(path,self.ledger)
            d.begin_attempt(self.ledger,task)
            d.atomic_store(path,self.ledger)
            reopened=d.load_ledger(path)
            self.assertEqual(d.recover_after_crash(reopened),1)
            d.atomic_store(path,reopened)
            again=d.load_ledger(path)
            self.assertEqual(again['batches'][task]['state'],'UNCERTAIN')
    def test_ledger_legacy_history_union(self):
        task=self.prepare();d.begin_attempt(self.ledger,task)
        d.smtp_accepted(self.ledger,task,True)
        got=d.accepted_keys(self.ledger,history(['doi:10.1109/tmc.2026.999']))
        self.assertEqual(len(got),4)
    def test_corrupt_double_batch_keys_fails(self):
        task=self.prepare()
        other=copy.deepcopy(self.ledger['batches'][task])
        other['id']='other-task';other['day']='2026-11-24'
        self.ledger['batches']['other-task']=other
        with self.assertRaises(d.SafetyError):d.check_ledger(self.ledger)
    def test_local_atomic_file_keeps_original_on_invalid(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'ledger.json'
            d.atomic_store(path,d.empty_ledger())
            before=path.read_bytes()
            with self.assertRaises(d.SafetyError):d.atomic_store(path,{'schema_version':3,'batches':{}})
            self.assertEqual(path.read_bytes(),before)
    def test_history_not_mutated(self):
        hist=copy.deepcopy(self.history)
        task=self.prepare();d.begin_attempt(self.ledger,task);d.uncertain(self.ledger,task)
        self.assertEqual(hist,self.history)
    def test_readonly_state_no_unintended_send(self):
        self.assertNotIn('smtplib',Path(d.__file__).read_text(encoding='utf-8'))
        self.assertNotIn('send_email(',Path(d.__file__).read_text(encoding='utf-8'))
    def test_multiple_simulations_no_duplicate(self):
        first=self.selected();t=self.prepare()
        d.begin_attempt(self.ledger,t);d.smtp_accepted(self.ledger,t,True)
        nextday=self.selected()
        self.assertTrue(set(r['paper_key'] for r in first).isdisjoint(
            set(r['paper_key'] for r in nextday)))
if __name__=='__main__':unittest.main()
