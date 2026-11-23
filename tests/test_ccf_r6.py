import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import ccf_r6_verify as verify
import ccf_r6_replay as replay
class R6Tests(unittest.TestCase):
    def setUp(self):
        self.row={'paper_key':'doi:10.1109/tmc.2026.123','venue':'TMC','field':'networking',
            'year':'2026','title':'Trusted Network Recovery With Deadline Constraints',
            'doi':'10.1109/tmc.2026.123','paper_url':'https://doi.org/10.1109/tmc.2026.123',
            'candidate_status':'PRELIMINARY'}
        self.mapped={'sources':[{'from_year':2024,'to_year':2026,
            'doi_series':'tmc','issn':['1536-1233']}]}
        self.work={'DOI':'10.1109/tmc.2026.123','type':'journal-article',
            'title':[self.row['title']],'ISSN':['1536-1233'],
            'publisher':'Institute of Electrical and Electronics Engineers (IEEE)',
            'published':{'date-parts':[[2026,5,1]]},
            'container-title':['IEEE Transactions on Mobile Computing']}
    def test_journal_publisher_valid(self):
        self.assertEqual(verify.journal_verdict(self.row,self.work,self.mapped)[0],'VERIFIED_PUBLISHER')
    def test_reject_bad_issn(self):
        self.assertEqual(verify.journal_verdict(self.row,dict(self.work,ISSN=['0000-0000']),self.mapped)[1],'ISSN_MISMATCH')
    def test_reject_preprint_type(self):
        self.assertEqual(verify.journal_verdict(self.row,dict(self.work,type='posted-content'),self.mapped)[0],'REVIEW')
    def test_reject_wrong_year(self):
        self.assertEqual(verify.journal_verdict(self.row,dict(self.work,published={'date-parts':[[2024,1,1]]}),self.mapped)[1],'YEAR_MISMATCH')
    def test_reject_wrong_title(self):
        self.assertEqual(verify.journal_verdict(self.row,dict(self.work,title=['Unrelated Cryptographic Mathematical Proofs']),self.mapped)[0],'REVIEW')
    def test_reject_legacy_source(self):
        self.assertEqual(verify.journal_verdict(self.row,self.work,
            {'sources':[dict(self.mapped['sources'][0],legacy_review=True)]})[0],'REVIEW')
    def test_reject_wrong_series(self):
        row=dict(self.row,doi='10.1109/other.2026.123')
        self.assertEqual(verify.journal_verdict(row,dict(self.work,DOI=row['doi']),self.mapped)[1],'DOI_SERIES_MISMATCH')
    def test_preprint_hosts(self):
        self.assertFalse(verify.safe_link('https://arxiv.org/abs/123'))
        self.assertFalse(verify.safe_link('https://a.arxiv.org/abs/123'))
        self.assertTrue(verify.safe_link(self.row['paper_url']))
    def test_official_exact_article_url(self):
        row={'paper_url':'https://www.usenix.org/conference/nsdi26/presentation/test',
             'title':'Reliable Edge Network Recovery Under Deadline'}
        self.assertEqual(verify.official_verdict(row,[dict(row)])[0],'VERIFIED_OFFICIAL')
        self.assertEqual(verify.official_verdict(dict(row,title='Mathematical Cryptography Proofs'),[dict(row)])[0],'REVIEW')
    def test_sampler_preprint_blocked(self):
        bad=dict(self.row,paper_key='url:bad',paper_url='https://arxiv.org/abs/123')
        state={'schema_version':1,'papers':{self.row['paper_key']:self.row,'url:bad':bad}}
        self.assertEqual(len(verify.sample(state,{'TMC':{'field':'networking'}},5)),1)
    def test_unknown_crossref_review(self):
        self.assertEqual(verify.journal_verdict(self.row,None,self.mapped)[0],'REVIEW')
    def test_verification_does_not_promote_persisted_status(self):
        row=verify.check(self.row,{'journals':{'TMC':self.mapped}},{},
                         lambda _:self.work,lambda *args:[])
        self.assertEqual(row['candidate_status'],'PRELIMINARY')
        self.assertEqual(row['publisher_verification'],'VERIFIED_PUBLISHER')
    def paper(self,i):
        return {'paper_key':str(i),'venue':'TON','title':'Paper '+str(i),
                'score':float(20-i),'candidate_status':'PRELIMINARY',
                'abstract':'Substantive network systems research abstract',
                'abstract_status':'ABSTRACT_VERIFIED_METADATA'}
    def test_three_day_retry_idempotency(self):
        rows=[self.paper(i) for i in range(9)]
        x=replay.simulate(rows,{str(i) for i in range(9)},set())
        self.assertEqual(len(x['first_day_simulated_success']),3)
        self.assertEqual(len(x['second_day_simulated_failure']),3)
        self.assertTrue(x['first_second_no_overlap'])
        self.assertTrue(x['failure_retry_same'])
        self.assertFalse(x['email_sent'])
    def test_preserve_previous_sent_history(self):
        rows=[self.paper(i) for i in range(7)]
        x=replay.simulate(rows,{str(i) for i in range(7)},{'0','1'})
        self.assertEqual({r['paper_key'] for r in x['first_day_simulated_success']},{'2','3','4'})
    def test_unverified_cannot_replay(self):
        self.assertEqual(replay.simulate([self.paper(0)],set(),set())['first_day_simulated_success'],[])
    def test_daily_cap(self):
        rows=[self.paper(i) for i in range(30)]
        self.assertEqual(len(replay.simulate(rows,{str(i) for i in range(30)},set())['first_day_simulated_success']),3)
    def test_invalid_state_schema(self):
        with self.assertRaises(ValueError):verify.sample({'schema_version':2,'papers':{}},{},5)
if __name__=='__main__':unittest.main()
