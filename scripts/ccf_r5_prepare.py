"""Export a bounded, repeatable preview sample from R4-2 durable CCF state.

No API requests, email or history changes. Sampling is stable, not a recency rank.
"""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
import yaml

FIELDS = ['paper_key','venue','field','year','publication_date','date_precision',
          'title','doi','paper_url','pdf_url','source_type','source_record_id',
          'source_status','candidate_status','reason','evidence_url','source_file']
BANNED_HOSTS = ('arxiv.org','biorxiv.org','medrxiv.org','chemrxiv.org','zenodo.org')

def prepare(state_path,history_path,whitelist_path,output_path,per_venue=4):
    if not 1<=per_venue<=10:
        raise ValueError('Unsafe preview sample size')
    state=json.loads(Path(state_path).read_text(encoding='utf-8'))
    sent=json.loads(Path(history_path).read_text(encoding='utf-8'))
    venues=yaml.safe_load(Path(whitelist_path).read_text(encoding='utf-8'))['venues']
    if state.get('schema_version')!=1 or not isinstance(state.get('papers'),dict):
        raise ValueError('Unexpected candidate-state schema')
    if sent.get('schema_version')!=1 or not isinstance(sent.get('sent_keys'),list):
        raise ValueError('Unexpected sent-history schema')
    if len(venues)!=16:
        raise ValueError('Unexpected CCF venue whitelist')
    sent_keys=set(sent['sent_keys'])
    groups=defaultdict(list)
    counts=Counter()
    for key,item in state['papers'].items():
        counts['state_total']+=1
        if key in sent_keys:
            counts['already_sent']+=1
            continue
        if item.get('candidate_status')!='PRELIMINARY':
            counts['not_preliminary']+=1
            continue
        venue=item.get('venue')
        if venue not in venues or item.get('field')!=venues[venue]['field']:
            counts['not_whitelisted']+=1
            continue
        url=str(item.get('paper_url') or '').lower()
        if any(host in url for host in BANNED_HOSTS):
            counts['preprint_or_repository_url']+=1
            continue
        if not key or item.get('paper_key')!=key or not item.get('title'):
            counts['invalid_record']+=1
            continue
        groups[venue].append(item)
    sampled=[]
    for venue in sorted(groups):
        # Stable DOI/ID ordering: no date bonus or recency priority.
        for item in sorted(groups[venue],key=lambda r:r['paper_key'])[:per_venue]:
            sampled.append({field: str(item.get(field) or '') for field in FIELDS})
    if len(sampled)<3:
        raise ValueError('Insufficient CCF candidate sample')
    output_path=Path(output_path)
    output_path.parent.mkdir(parents=True,exist_ok=True)
    with output_path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(sampled)
    summary={'stage':'R5','scope':'BOUNDED_PREVIEW','input_state_size':len(state['papers']),
             'sampled_count':len(sampled),'venues_sampled':len(groups),
             'sampled_venues':sorted({r['venue'] for r in sampled}),
             'history_count':len(sent_keys),'skipped':dict(counts),
             'email_sent':False,'sent_history_modified':False,
             'caveat':'PRELIMINARY publisher/source candidates, not individually certified papers'}
    (output_path.parent/'prepare_audit.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    return summary

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--state',type=Path,default=Path('data/ccf_candidate_state.json'))
    p.add_argument('--history',type=Path,default=Path('data/ccf_sent_history.json'))
    p.add_argument('--whitelist',type=Path,default=Path('config/ccf_a_venues.yaml'))
    p.add_argument('--out',type=Path,default=Path('ccf-r5-preview/candidates.csv'))
    p.add_argument('--per-venue',type=int,default=4)
    a=p.parse_args()
    print('PREPARED '+json.dumps(prepare(a.state,a.history,a.whitelist,a.out,a.per_venue),ensure_ascii=False),flush=True)
if __name__=='__main__':main()
