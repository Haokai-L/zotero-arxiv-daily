"""Read-only Zotero corpus and unchanged upstream LocalReranker scoring.

Never sends email. Raw Zotero reference abstracts are not written to artifacts.
"""
import argparse,csv,json,os
from datetime import datetime
from pathlib import Path
from ccf_recommend_core import choose
def read_corpus():
    from pyzotero import zotero
    from zotero_arxiv_daily.protocol import CorpusPaper
    user_id=os.environ.get('ZOTERO_ID','').strip()
    key=os.environ.get('ZOTERO_KEY','').strip()
    if not user_id or not key:raise RuntimeError('Missing read-only Zotero credentials')
    client=zotero.Zotero(user_id,'user',key)
    collections={c['key']:c['data'] for c in client.everything(client.collections())}
    cache={}
    def collection_path(k):
        if k in cache:return cache[k]
        data=collections.get(k)
        if data is None:return ''
        parent=data.get('parentCollection')
        path=((collection_path(parent)+'/') if parent else '')+data.get('name','')
        cache[k]=path;return path
    corpus=[]
    items=client.everything(client.items(itemType='conferencePaper || journalArticle || preprint'))
    for item in items:
        data=item.get('data') or {}
        if not data.get('title') or not data.get('abstractNote'):continue
        try:added=datetime.strptime(data['dateAdded'],'%Y-%m-%dT%H:%M:%SZ')
        except (KeyError,ValueError):continue
        corpus.append(CorpusPaper(title=data['title'],abstract=data['abstractNote'],added_date=added,
            paths=[path for k in data.get('collections',[]) if (path:=collection_path(k))]))
    return corpus
def original_rerank(rows,corpus):
    from omegaconf import OmegaConf
    from zotero_arxiv_daily.protocol import Paper
    from zotero_arxiv_daily.reranker.local import LocalReranker
    cfg=OmegaConf.create({'executor':{'debug':True},
        'reranker':{'local':{'model':'jinaai/jina-embeddings-v5-text-nano-retrieval',
            'encode_kwargs':{'task':'retrieval','prompt_name':'document'}}}})
    papers=[Paper(source=r['venue'],title=r['title'],authors=json.loads(r.get('authors') or '[]'),
       abstract=r['abstract'],url=r['paper_url'],pdf_url=r.get('pdf_url') or None) for r in rows]
    by_identity={id(p):r for p,r in zip(papers,rows)}
    # Reuse upstream scorer's weighted Zotero cosine similarity formula exactly.
    ranked=LocalReranker(cfg).rerank(papers,corpus)
    return [dict(by_identity[id(p)],score=p.score) for p in ranked]
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path('ccf-r41-preview/recommendations.json'))
    parser.add_argument('--max-corpus',type=int,default=150)
    args=parser.parse_args()
    with args.input.open(encoding='utf-8-sig',newline='') as f:
        rows=[r for r in csv.DictReader(f) if r.get('abstract_status')=='ABSTRACT_VERIFIED_METADATA']
    corpus=read_corpus()
    if not rows or len(corpus)<2:raise RuntimeError('No verified abstracts or insufficient Zotero corpus')
    corpus=sorted(corpus,key=lambda p:p.added_date,reverse=True)[:args.max_corpus]
    scored=original_rerank(rows,corpus)
    import yaml
    settings=yaml.safe_load(Path('config/ccf_recommend.yaml').read_text(encoding='utf-8'))
    if settings.get('send_enabled') is not False:raise RuntimeError('Email must remain disabled')
    result=choose(scored,limit=int(settings['daily_max']),margin=float(settings['anrc_score_margin']))
    result.update(zotero_corpus_count_used=len(corpus),candidate_abstract_count=len(rows))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('ZOTERO_SCORE_PREVIEW '+json.dumps({'selected':len(result['selected']),
        'corpus_references':len(corpus),'email_sent':False},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
