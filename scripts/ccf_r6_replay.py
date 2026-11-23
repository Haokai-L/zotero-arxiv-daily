"""R6-2 real Zotero scoring, three-day in-memory replay; never sends email."""
import argparse,csv,json,hashlib
from pathlib import Path
from ccf_recommend_core import choose
from ccf_recommend_preview import read_corpus,original_rerank

def csv_rows(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def simulate(scored,verified,sent):
    eligible=[dict(r) for r in scored if r.get('paper_key') in verified
              and r.get('abstract_status')=='ABSTRACT_VERIFIED_METADATA']
    virtual=set(sent)
    day1=choose(eligible,virtual)['selected']
    k1={r['paper_key'] for r in day1}
    virtual.update(k1)
    day2=choose(eligible,virtual)['selected']
    k2={r['paper_key'] for r in day2}
    day3=choose(eligible,virtual)['selected']
    k3={r['paper_key'] for r in day3}
    if k1&k2 or k2!=k3:raise AssertionError('Duplicate/retry policy failed')
    if any(len(day)>3 for day in (day1,day2,day3)):raise AssertionError('Quota failed')
    def detail(rows):
        return [{'paper_key':r['paper_key'],'venue':r['venue'],'title':r['title'],
                 'score':round(float(r['score']),4),
                 'anrc_keyword_match':bool(r.get('anrc_keyword_match'))} for r in rows]
    return {'stage':'R6-2','mode':'REAL_ZOTERO_SCORES_VIRTUAL_SEND_ONLY',
        'eligible_scored':len(eligible),'first_day_simulated_success':detail(day1),
        'second_day_simulated_failure':detail(day2),
        'third_day_retry':detail(day3),'first_second_no_overlap':not bool(k1&k2),
        'failure_retry_same':k2==k3,'history_changed':False,'email_sent':False,
        'production_ready':False,'limitation':'In-memory simulation is not SMTP delivery verification'}
def run(verified_file,enriched_file,history_file,out_file,max_corpus=150):
    original=Path(history_file).read_bytes(); history=json.loads(original)
    if history.get('schema_version')!=1 or not isinstance(history.get('sent_keys'),list):
        raise ValueError('Invalid history schema')
    verified={r['paper_key'] for r in csv_rows(verified_file)
              if r.get('publisher_verification') in ('VERIFIED_PUBLISHER','VERIFIED_OFFICIAL')}
    rows=[r for r in csv_rows(enriched_file) if r.get('paper_key') in verified
          and r.get('abstract_status')=='ABSTRACT_VERIFIED_METADATA']
    if len(rows)<3:raise RuntimeError('Not enough publisher-verified papers with real abstracts')
    corpus=sorted(read_corpus(),key=lambda x:x.added_date,reverse=True)[:max_corpus]
    if len(corpus)<2:raise RuntimeError('Not enough Zotero references')
    scored=original_rerank(rows,corpus)
    result=simulate(scored,verified,set(history['sent_keys']))
    result['zotero_references_used']=len(corpus)
    result['history_sha256']=hashlib.sha256(original).hexdigest()
    if Path(history_file).read_bytes()!=original:raise AssertionError('History mutated')
    out_file=Path(out_file);out_file.parent.mkdir(parents=True,exist_ok=True)
    out_file.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('R6_REPLAY '+json.dumps({k:v for k,v in result.items() if not k.endswith('success') and not k.endswith('failure') and k!='third_day_retry'},ensure_ascii=False),flush=True)
    return result
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--verified',type=Path,required=True)
    ap.add_argument('--enriched',type=Path,required=True)
    ap.add_argument('--history',type=Path,default=Path('data/ccf_sent_history.json'))
    ap.add_argument('--out',type=Path,default=Path('ccf-r6-audit/replay.json'))
    a=ap.parse_args();run(a.verified,a.enriched,a.history,a.out)
if __name__=='__main__':main()
