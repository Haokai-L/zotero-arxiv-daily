"""Read-only Zotero corpus and unchanged upstream LocalReranker scoring.

Never sends email. Raw Zotero reference abstracts are not written to artifacts.
"""
import json,os
from datetime import datetime
def in_research_collection(paths):
    return any(p == 'A-NRC-Research' or p.startswith('A-NRC-Research/') for p in paths)

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
    return [p for p in corpus if in_research_collection(p.paths)]
def original_rerank(rows,corpus,*,title_only=False):
    from omegaconf import OmegaConf
    from zotero_arxiv_daily.protocol import Paper
    from zotero_arxiv_daily.reranker.local import LocalReranker
    cfg=OmegaConf.create({'executor':{'debug':True},
        'reranker':{'local':{'model':'jinaai/jina-embeddings-v5-text-nano-retrieval',
            'encode_kwargs':{'task':'retrieval','prompt_name':'document'}}}})
    papers=[Paper(source=r['venue'],title=r['title'],authors=json.loads(r.get('authors') or '[]'),
       abstract=r['title'] if title_only else r['abstract'],url=r['paper_url'],pdf_url=r.get('pdf_url') or None) for r in rows]
    by_identity={id(p):r for p,r in zip(papers,rows)}
    # Reuse upstream scorer's weighted Zotero cosine similarity formula exactly.
    ranked=LocalReranker(cfg).rerank(papers,corpus)
    return [dict(by_identity[id(p)],score=p.score) for p in ranked]
