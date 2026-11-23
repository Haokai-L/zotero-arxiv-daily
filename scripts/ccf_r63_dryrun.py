"""R6-3 real Zotero scoring + independent evidence + ledger dry-run, NO SMTP."""
import argparse,csv,hashlib,json,tempfile
from pathlib import Path
import yaml
from ccf_r63_delivery import (empty_ledger,load_ledger,atomic_store,
        select_sendable,prepare_batch,begin_attempt,recover_after_crash,
        history_keys,accepted_keys,SafetyError)
from ccf_recommend_preview import read_corpus,original_rerank

def read_csv(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))

def run(verified_path,enriched_path,history_path,ledger_path,whitelist_path,out_path):
    historical_bytes=Path(history_path).read_bytes()
    ledger_bytes=Path(ledger_path).read_bytes()
    history=json.loads(historical_bytes)
    persisted=load_ledger(ledger_path)
    history_keys(history)
    whitelist=yaml.safe_load(Path(whitelist_path).read_text(encoding='utf-8'))['venues']
    verified=read_csv(verified_path)
    enriched=[r for r in read_csv(enriched_path)
              if r.get('abstract_status')=='ABSTRACT_VERIFIED_METADATA']
    good_keys={r['paper_key'] for r in verified if r['publisher_verification'] in
              ('VERIFIED_PUBLISHER','VERIFIED_OFFICIAL')}
    filtered=[r for r in enriched if r.get('paper_key') in good_keys]
    if not filtered:raise SafetyError('No independently verified candidates with authentic abstracts')
    corpus=sorted(read_corpus(),key=lambda p:p.added_date,reverse=True)[:150]
    if len(corpus)<2:raise SafetyError('Insufficient real Zotero references')
    scored=original_rerank(filtered,corpus)
    picks=select_sendable(scored,verified,whitelist,history,persisted)
    records=picks['selected']
    # Do not include raw user corpus in artifact.
    today='2026-11-23'
    example_html=('<html><body>'+''.join('<p>'+r['paper_key']+'</p>' for r in records)+'</body></html>').encode('utf-8')
    with tempfile.TemporaryDirectory(prefix='r63-dryrun-') as folder:
        tmp=Path(folder)/'ledger.json'
        atomic_store(tmp,persisted)
        dry=load_ledger(tmp)
        task=prepare_batch(dry,history,records,today,example_html)
        atomic_store(tmp,dry) # simulate durable PREPARED
        begin_attempt(dry,task)
        atomic_store(tmp,dry) # simulate durable ATTEMPTING
        crashed=load_ledger(tmp)
        recover_after_crash(crashed)
        atomic_store(tmp,crashed)
        if load_ledger(tmp)['batches'][task]['state']!='UNCERTAIN':
            raise AssertionError('Crash should block automatic retry')
        try:
            select_sendable(scored,verified,whitelist,history,crashed)
        except SafetyError:
            blocked=True
        else:
            blocked=False
        if not blocked:raise AssertionError('Uncertain batch was not blocked')
    if Path(history_path).read_bytes()!=historical_bytes or Path(ledger_path).read_bytes()!=ledger_bytes:
        raise AssertionError('Durable production files changed')
    result={
        'stage':'R6-3','audit':'REAL_SOURCE_VERIFIED_AND_ZOTERO_SCORED_DRY_RUN',
        'verified_input':len(verified),'authentic_abstracts':len(filtered),
        'zotero_reference_count':len(corpus),'selected_count':len(records),
        'selected':[{'paper_key':r['paper_key'],'venue':r['venue'],
                     'score':round(float(r['score']),4)}
                    for r in records],
        'task_id':task,'restarted_state':'UNCERTAIN',
        'auto_retry_blocked':blocked,'production_history_unchanged':True,
        'production_ledger_unchanged':True,
        'production_ready':False,'email_sent':False,
        'limitations':[
           'The workflow uses a bounded verified sample rather than all candidates.',
           'Only local atomic persistence was tested; GitHub remote compare-and-swap sender integration is pending.',
           'This test deliberately does not call SMTP or establish mail delivery.'
        ],
    }
    Path(out_path).parent.mkdir(parents=True,exist_ok=True)
    Path(out_path).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('R63_DRYRUN '+json.dumps({k:v for k,v in result.items() if k!='selected'},ensure_ascii=False),flush=True)
    return result
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--verified',required=True,type=Path)
    p.add_argument('--enriched',required=True,type=Path)
    p.add_argument('--history',default=Path('data/ccf_sent_history.json'),type=Path)
    p.add_argument('--ledger',default=Path('data/ccf_delivery_ledger.json'),type=Path)
    p.add_argument('--whitelist',default=Path('config/ccf_a_venues.yaml'),type=Path)
    p.add_argument('--out',default=Path('ccf-r63-audit/dryrun.json'),type=Path)
    args=p.parse_args()
    run(args.verified,args.enriched,args.history,args.ledger,args.whitelist,args.out)
if __name__=='__main__':main()
