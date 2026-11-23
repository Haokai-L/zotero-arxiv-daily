"""R4-2 offline contract tests, no external network or credentials."""
import csv
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import ccf_incremental as m

TODAY=date(2026,11,23)


def candidate(doi='10.1109/ton.2026.123',venue='TON'):
    return dict(paper_key='doi:'+doi,venue=venue,field='networking',year='2026',
                publication_date='2026-11-01',date_precision='day',title='A research paper with a good title',
                doi=doi,paper_url='https://doi.org/'+doi,source_type='OpenAlex journal',
                source_record_id='https://openalex.org/W1',source_status='PASS_METADATA_RULES',
                candidate_status='PRELIMINARY',reason='',evidence_url='https://openalex.org/W1')


class IncrementalTests(unittest.TestCase):
    def test_whitelist_six_journals_ten_conferences(self):
        w=yaml.safe_load((ROOT/'config/ccf_a_venues.yaml').read_text(encoding='utf8'))
        j=yaml.safe_load((ROOT/'config/journal_source_map.yaml').read_text(encoding='utf8'))
        c=yaml.safe_load((ROOT/'config/ccf_incremental_2026.yaml').read_text(encoding='utf8'))
        m.validate_config(w,j,c,2026)
        self.assertEqual(len(c['venues']),10)
        self.assertEqual(len(c['venues']['CRYPTO']['verified_book_dois']),10)
        self.assertEqual(len(c['venues']['EUROCRYPT']['verified_book_dois']),7)

    def test_crossref_springer_official_book_match(self):
        c=yaml.safe_load((ROOT/'config/ccf_incremental_2026.yaml').read_text(encoding='utf8'))
        record={'title':['Formal Security Research Article'],
                'container-title':['Lecture Notes in Computer Science'],
                'type':'book-chapter','published':{'date-parts':[[2026,8,1]]},
                'DOI':'10.1007/978-3-032-35367-2_9','publisher':'Springer Science'}
        from ccf_conference_quality import check_crossref
        self.assertEqual(check_crossref(record,'CRYPTO',c['venues']['CRYPTO'],2026)['status'],'SPRINGER_BOOK_MATCH')
        record['DOI']='10.1007/978-3-032-99999-9_9'
        self.assertEqual(check_crossref(record,'CRYPTO',c['venues']['CRYPTO'],2026)['status'],'REVIEW')

    def test_conference_official_link_2026(self):
        conf=yaml.safe_load((ROOT/'config/ccf_incremental_2026.yaml').read_text(encoding='utf8'))['venues']
        with patch.object(m,'fetch_text',return_value='<html>'+('<p>Official proceedings</p>'*100)+
                          '<a href="/conference/nsdi26/presentation/smith">Network Services Recovery for Modern Datacenters</a></html>'):
            rows,audit=m.conference_source('NSDI',conf['NSDI'],2026,TODAY,'')
        self.assertEqual(audit['status'],'CHECKED')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['candidate_status'],'PRELIMINARY')
        self.assertEqual(rows[0]['paper_key'].split(':')[0],'url')

    def test_crossref_uses_index_date_overlap(self):
        queries=[]
        def fake_fetch(url):
            queries.append(url)
            return json.dumps({'status':'ok','message':{'total-results':0,'items':[]}})
        with patch.object(m,'fetch_text',side_effect=fake_fetch):
            rows,partial,total=m.crossref_pages('CCS',{'query':'Some proceedings'},2026,TODAY,'2026-11-20')
        self.assertEqual((rows,partial,total),([],False,0))
        self.assertIn('from-index-date%3A2026-10-06',queries[0])

    def test_initial_crossref_queries_publication_year(self):
        queries=[]
        def fake_fetch(url):
            queries.append(url)
            return json.dumps({'status':'ok','message':{'total-results':0,'items':[]}})
        with patch.object(m,'fetch_text',side_effect=fake_fetch):
            m.crossref_pages('CCS',{'query':'Some proceedings'},2026,TODAY,'')
        self.assertIn('from-pub-date%3A2026-01-01',queries[0])

    def test_merge_is_idempotent_and_preserves_first_seen(self):
        state=m.empty_state()
        r=candidate()
        result=m.merge(state,[r,r],TODAY,set())
        self.assertEqual((result['new'],result['duplicate_scan_results']),(1,1))
        next_day=date(2026,11,24)
        result=m.merge(state,[r],next_day,set())
        self.assertEqual((result['new'],result['previously_known']),(0,1))
        self.assertEqual(state['papers'][r['paper_key']]['first_seen'],'2026-11-23')
        self.assertEqual(state['papers'][r['paper_key']]['last_seen'],'2026-11-24')

    def test_sent_history_does_not_mutate(self):
        with tempfile.TemporaryDirectory() as directory:
            history=Path(directory)/'history.json'
            history.write_text(json.dumps({'schema_version':1,'sent_keys':['doi:10.1109/ton.2026.123']}))
            before=history.read_bytes()
            sent=m.validate_sent_history(history)
            state=m.empty_state();result=m.merge(state,[candidate()],TODAY,sent)
            self.assertEqual(result['unsent_candidates'],0)
            self.assertEqual(history.read_bytes(),before)

    def test_no_preprint_discovery(self):
        c=yaml.safe_load((ROOT/'config/ccf_incremental_2026.yaml').read_text(encoding='utf8'))
        self.assertTrue(all(v['provider'] in ('crossref','official') for v in c['venues'].values()))
        self.assertNotIn('arxiv',str(c).lower())

    def test_seed_from_previous_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'seed.csv'
            with path.open('w',encoding='utf8',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(candidate()))
                writer.writeheader();writer.writerow(candidate())
            state=m.empty_state()
            n=m.seed_from_snapshot(state,path,TODAY)
            self.assertEqual(n,1)
            self.assertEqual(m.seed_from_snapshot(state,path,TODAY),0)

    def test_bounded_crossref_audit_reports_partial(self):
        def fake_fetch(_):
            return json.dumps({'status':'ok','message':{'total-results':999,'items':[{}]*100}})
        with patch.object(m,'fetch_text',side_effect=fake_fetch):
            records,partial,total=m.crossref_pages('CCS',{'query':'Some proceedings'},2026,TODAY,'',page_cap=2)
        self.assertEqual((len(records),partial,total),(200,True,999))

    def test_fails_closed_on_api_errors_and_does_not_save_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            history=root/'sent.json';history.write_text(json.dumps({'schema_version':1,'sent_keys':[]}))
            state=root/'state.json'
            with patch.dict('os.environ',{'OPENALEX_API_KEY':''}):
                with patch.object(m,'conference_source',return_value=([],{'status':'CHECKED'})):
                    with self.assertRaises(SystemExit):
                        m.run(state,history,None,ROOT/'config/ccf_a_venues.yaml',
                              ROOT/'config/journal_source_map.yaml',ROOT/'config/ccf_incremental_2026.yaml',
                              root/'out',TODAY)
            self.assertFalse(state.exists())
            self.assertTrue((root/'out'/'source_audit.json').exists())


if __name__=='__main__':unittest.main()
