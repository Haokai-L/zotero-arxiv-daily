import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import ccf_r5_mail as mail
import ccf_r5_prepare as prep

CFG={'daily_max':3,'send_enabled':False,'preview_only':True,'model':'deepseek-chat'}
WHITELIST={'TON':{'field':'networking','kind':'journal'},'TMC':{'field':'networking','kind':'journal'}}

def row(n='1',venue='TON'):
    return {'paper_key':'doi:10.1109/example.'+n,'candidate_status':'PRELIMINARY',
            'abstract_status':'ABSTRACT_VERIFIED_METADATA','title':'Service chain recovery '+n,
            'abstract':'In this study, researchers investigate deadline aware recovery and propose a new robust method for edge service chains. '*3,
            'paper_url':'https://doi.org/10.1109/example.'+n,'doi':'10.1109/example.'+n,
            'venue':venue,'year':'2026','score':4.2,'authors':'["X", "Y"]','pdf_url':''}

def preview(rows):return {'email_sent':False,'preview_only':True,'selected':rows}

class R5Tests(unittest.TestCase):
    def test_no_deepseek_key_never_generates_fake_summary(self):
        with tempfile.TemporaryDirectory() as t:
            result=mail.build(preview([row()]),CFG,WHITELIST,Path(t),env={},today='2026-11-23')
            self.assertEqual(result['deepseek_generated'],0)
            self.assertEqual(result['summary_status_counts'],{'DEEPSEEK_NOT_CONFIGURED':1})
            self.assertFalse(result['email_sent'])
            self.assertIn('以下为英文摘要节选',Path(t,'email_preview.html').read_text())
    def test_use_verified_deepseek_api_mock(self):
        mock=MagicMock()
        mock.chat.completions.create.return_value.choices[0].message.content='该研究针对边缘服务链的故障恢复，提出截止时间感知方法，以改善恢复过程中的稳定性与资源利用。'
        with tempfile.TemporaryDirectory() as t:
            result=mail.build(preview([row()]),CFG,WHITELIST,Path(t),env={},client=mock)
            self.assertEqual(result['deepseek_generated'],1)
            self.assertIn('该研究',Path(t,'email_preview.html').read_text())
    def test_max_three(self):
        with self.assertRaises(ValueError):mail.valid_selected(preview([row(str(i)) for i in range(4)]),WHITELIST)
    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):mail.valid_selected(preview([row(),row()]),WHITELIST)
    def test_review_rejected(self):
        paper=row();paper['candidate_status']='REVIEW'
        with self.assertRaises(ValueError):mail.valid_selected(preview([paper]),WHITELIST)
    def test_unknown_venue_rejected(self):
        with self.assertRaises(ValueError):mail.valid_selected(preview([row(venue='arXiv')]),WHITELIST)
    def test_fake_score_rejected(self):
        paper=row();paper['score']='NaN'
        with self.assertRaises(ValueError):mail.valid_selected(preview([paper]),WHITELIST)
    def test_preprint_link_blocked(self):
        paper=row();paper['paper_url']='https://arxiv.org/abs/1234'
        with self.assertRaises(ValueError):mail.valid_selected(preview([paper]),WHITELIST)
    def test_html_escapes_untrusted_text(self):
        paper=row();paper['title']='<img src=x onerror=alert(1)>'
        html=mail.render_html([dict(paper,score=4.5,zh_summary='<script>alert(1)</script>')],'OK','2026-11-23')
        self.assertNotIn('<script>',html)
        self.assertNotIn('<img src=x',html)
        self.assertIn('&lt;script&gt;',html)
    def test_no_pdf_button_when_missing(self):
        text=mail.render_html([dict(row(),zh_summary='',score=3)],'无','2026-11-23')
        self.assertNotIn('>PDF</a>',text)
    def test_different_provider_key_not_labeled_deepseek(self):
        self.assertEqual(mail.provider_key({'OPENAI_API_KEY':'abc','OPENAI_API_BASE':'https://api.openai.com/v1'})[1], 'DEEPSEEK_NOT_CONFIGURED')
    def test_existing_deepseek_key_detected(self):
        self.assertEqual(mail.provider_key({'OPENAI_API_KEY':'abc','OPENAI_API_BASE':'https://api.deepseek.com/v1'})[1], 'EXISTING_DEEPSEEK_COMPATIBLE_KEY')
    def test_fail_closed_when_send_enabled(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ValueError):mail.build(preview([row()]),dict(CFG,send_enabled=True),WHITELIST,Path(t),env={})
    def test_persisted_state_preview_does_not_change_history(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp); state=d/'state.json'; hist=d/'history.json'; cfg=d/'venues.yaml'; out=d/'sample.csv'
            state.write_text(json.dumps({'schema_version':1,'papers':{r['paper_key']:r for r in [dict(row('1'),field='networking'),dict(row('2'),field='networking'),dict(row('3'),field='networking'),dict(row('4'),field='networking')]}}))
            hist.write_text(json.dumps({'schema_version':1,'sent_keys':['doi:10.1109/example.2']}))
            cfg.write_text('venues:\n  TON:\n    field: networking\n    kind: journal\n  TMC:\n    field: networking\n    kind: journal\n'+''.join('  V'+str(i)+':\n    field: networking\n    kind: journal\n' for i in range(14)))
            # seed items lack ID? no; includes in row() yes.
            prior=hist.read_bytes()
            result=prep.prepare(state,hist,cfg,out,per_venue=3)
            self.assertEqual(result['sampled_count'],3)
            self.assertEqual(hist.read_bytes(),prior)
            with out.open(encoding='utf-8-sig') as stream:
                self.assertEqual(len(list(csv.DictReader(stream))),3)

if __name__=='__main__':unittest.main()
