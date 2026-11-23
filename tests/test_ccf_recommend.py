import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from ccf_recommend_core import choose,is_anrc_related
from ccf_paper_enrichment import abstract_from_inverted,enrich_one,sample_balanced
def item(key,score,abstract='Service chain recovery in edge networks',title='Reliable network services'):
    return {'paper_key':key,'candidate_status':'PRELIMINARY','score':score,
            'title':title,'abstract':abstract,'venue':'TON'}
class RecommendationTests(unittest.TestCase):
    def test_at_most_three(self):
        self.assertEqual([r['paper_key'] for r in choose([item(str(i),i) for i in range(10)])['selected']],['9','8','7'])
    def test_soft_research_slot(self):
        x=[item('a',8.9,'Security and cryptographic hardness','Cryptography research'),
           item('b',8.8,'Wireless radio channel processing','Wireless research'),
           item('c',8.7,'Robust algorithms for formal verification','Formal verification'),
           item('d',8.5,'Deadline-aware recovery of edge service chains','Service recovery')]
        self.assertEqual({r['paper_key'] for r in choose(x)['selected']},{'a','b','d'})
    def test_no_forced_research(self):
        x=[item(str(i),9-i,'Cryptographic protocols','Security paper') for i in range(5)]
        self.assertEqual(choose(x)['anrc_keyword_match_count'],0)
    def test_low_scoring_research_not_forced(self):
        x=[item(str(i),9-i*0.1,'Secure protocols','Cryptography') for i in range(3)]
        x.append(item('anrc',1,'Recovery of edge service chains'))
        self.assertNotIn('anrc',[r['paper_key'] for r in choose(x)['selected']])
    def test_reject_unverified(self):
        x=[item('a',9),dict(item('b',99),candidate_status='REVIEW')]
        self.assertEqual([r['paper_key'] for r in choose(x)['selected']],['a'])
    def test_no_repeat(self):
        x=[item('a',9),item('a',9),item('b',8)]
        self.assertEqual(len(choose(x,sent_keys={'a'})['selected']),1)
    def test_no_fake_score_or_abstract(self):
        self.assertEqual(choose([item('a',float('nan')),item('b',9,abstract='')])['selected'],[])
    def test_dates_do_not_affect_score(self):
        x=[dict(item('older',9),year='2024'),dict(item('newer',6),year='2026')]
        self.assertEqual(choose(x)['selected'][0]['paper_key'],'older')
    def test_keyword_proxy(self):
        self.assertTrue(is_anrc_related('Recovery of edge service chains','Robust deadline constraints'))
        self.assertFalse(is_anrc_related('Security protocol','New privacy proof'))
    def test_inverted_index(self):
        self.assertEqual(abstract_from_inverted({'Resilient':[0],'network':[1],'service':[2]}),'Resilient network service')
    def test_doi_mismatch(self):
        r=dict(item('x',8),doi='10.1109/ton.2025.1')
        w={'id':'https://openalex.org/W1','doi':'https://doi.org/10.1109/ton.2025.2','title':r['title']}
        self.assertEqual(enrich_one(r,w)['abstract_status'],'DOI_MISMATCH')
    def test_balanced_sample(self):
        rows=[dict(item(str(i),1),venue='TON') for i in range(5)]+[dict(item('b',1),venue='CCS')]
        self.assertEqual({r['venue'] for r in sample_balanced(rows,2)},{'CCS','TON'})
class UpstreamScoringTests(unittest.TestCase):
    def test_original_weighted_formula(self):
        import numpy as np
        from datetime import datetime
        from zotero_arxiv_daily.reranker.base import BaseReranker
        from zotero_arxiv_daily.protocol import CorpusPaper,Paper
        class DeterministicMatrix(BaseReranker):
            def get_similarity_score(self,s1,s2):
                self.requested=s1,s2
                return np.array([[0.9,0.7],[0.2,0.4]])
        scorer=DeterministicMatrix(config=None)
        docs=[Paper(source='TON',title='a',authors=[],abstract='alpha',url='https://example.org/a'),
              Paper(source='CCS',title='b',authors=[],abstract='beta',url='https://example.org/b')]
        corpus=[CorpusPaper(title='recent',abstract='recent',added_date=datetime(2026,1,1),paths=[]),
                CorpusPaper(title='older',abstract='older',added_date=datetime(2025,1,1),paths=[])]
        ranked=scorer.rerank(docs,corpus)
        self.assertEqual([r.title for r in ranked],['a','b'])
        w=np.array([1/(1+np.log10(i+1)) for i in range(2)]);w=w/w.sum()
        self.assertAlmostEqual(docs[0].score,float(10*(0.9*w[0]+0.7*w[1])))
        self.assertEqual(scorer.requested[0],['alpha','beta'])
if __name__=='__main__':unittest.main()
