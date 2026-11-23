import sys
import unittest
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_ccf_candidate_pool as p

VENUES={'TON':{'kind':'journal','field':'networking'}, 'NSDI':{'kind':'conference','field':'networking'}}

class TestUnifiedPool(unittest.TestCase):
    def test_doi_and_url_normalization(self):
        self.assertEqual(p.norm_doi('https://doi.org/10.1109/TON.2025.123'), '10.1109/ton.2025.123')
        self.assertEqual(p.canonical_url('http://www.usenix.org/conference/nsdi25/presentation/smith?utm=x'), 'https://www.usenix.org/conference/nsdi25/presentation/smith')
    def test_journal_identity_and_day(self):
        row={'venue':'TON','field':'networking','year':'2026','date':'2026-05-01','title':'Important Robust Networking Recovery','doi':'10.1109/ton.2026.123','openalex_id':'https://openalex.org/W123','status':'PASS_METADATA_RULES'}
        v=p.map_record(row,'journals','journal_papers_preview.csv',VENUES,date(2026,11,23))
        self.assertEqual(v['candidate_status'], 'PRELIMINARY')
        self.assertEqual(v['date_precision'], 'day')
    def test_official_no_doi(self):
        row={'venue':'NSDI','field':'networking','year':'2025','title':'Paper on Fault Recovery in Datacenters',
             'paper_url':'https://www.usenix.org/conference/nsdi25/presentation/lee',
             'official_evidence_url':'https://www.usenix.org/conference/nsdi25/technical-sessions',
             'status':'OFFICIAL_LISTED','source':'Official conference listing'}
        v=p.map_record(row,'conferences','conference_papers_preview.csv',VENUES,date(2026,11,23))
        self.assertEqual(v['candidate_status'], 'PRELIMINARY')
        self.assertEqual(v['date_precision'], 'year')
    def test_short_official_title_is_not_excluded(self):
        row={'venue':'NSDI','field':'networking','year':'2025','title':'Move2EVM',
             'paper_url':'https://www.usenix.org/conference/nsdi25/presentation/short',
             'official_evidence_url':'https://www.usenix.org/conference/nsdi25/technical-sessions',
             'status':'OFFICIAL_LISTED'}
        self.assertEqual(p.map_record(row,'conferences','conference_papers_preview.csv',VENUES,date(2026,11,23))['candidate_status'],'PRELIMINARY')
    def test_date_invalid(self):
        row={'venue':'TON','field':'networking','year':'2026','date':'2026-12-01','title':'Important Robust Networking Recovery','doi':'10.1109/ton.2026.123','openalex_id':'https://openalex.org/W123','status':'PASS_METADATA_RULES'}
        v=p.map_record(row,'journals','journal_papers_preview.csv',VENUES,date(2026,11,23))
        self.assertEqual(v['candidate_status'], 'EXCLUDED')
    def test_year_outside(self):
        row={'venue':'TON','field':'networking','year':'2023','date':'2023-09-01','title':'Important Robust Networking Recovery','doi':'10.1109/ton.2023.123','openalex_id':'https://openalex.org/W123','status':'PASS_METADATA_RULES'}
        self.assertEqual(p.map_record(row,'journals','x',VENUES,date(2026,11,23))['candidate_status'], 'EXCLUDED')
    def test_dedup_same_doi(self):
        x={'paper_key':'doi:10.1234/x','doi':'10.1234/x','title':'Interesting Work','year':2025,'venue':'TON','candidate_status':'PRELIMINARY','source_status':'PASS_METADATA_RULES','paper_url':'https://doi.org/10.1234/x','reason':''}
        uniq,dups=p.combine([x,dict(x,source_status='REVIEW',candidate_status='REVIEW')])
        self.assertEqual((len(uniq),len(dups)),(1,1))
    def test_same_title_diff_doi_kept_for_review(self):
        x={'paper_key':'doi:10.1234/x','doi':'10.1234/x','title':'Interesting Work','year':2025,'venue':'TON','candidate_status':'PRELIMINARY','source_status':'PASS_METADATA_RULES','paper_url':'https://doi.org/10.1234/x','reason':''}
        y=dict(x,paper_key='doi:10.1234/y',doi='10.1234/y')
        u,d=p.combine([x,y]);self.assertEqual(len(d),0)
        self.assertTrue(all(i['candidate_status']=='REVIEW' for i in u))
    def test_excluded_status_never_eligible(self):
        row={'venue':'TON','field':'networking','year':'2026','date':'2026-05-01','title':'Correction to Interesting Work','doi':'10.1109/ton.2026.123','openalex_id':'https://openalex.org/W123','status':'REJECT'}
        self.assertEqual(p.map_record(row,'journals','journal_excluded.csv',VENUES,date(2026,11,23))['candidate_status'],'EXCLUDED')

if __name__ == '__main__': unittest.main()
