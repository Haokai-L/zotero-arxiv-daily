"""Pure CCF selection policy. No date bonus, LLM calls, email or secrets."""
import math
import re
import unicodedata
TARGET_RECOVERY = re.compile(r"\b(recover(?:y|ies)?|restor(?:ation|e|ing)|resilien(?:t|ce)|fault[- ]toleran(?:ce|t)|failover|failure|deadline[- ]aware|service[- ]continuity)\b",re.I)
TARGET_CONTEXT = re.compile(r"\b(edge|microservices?|service[- ]chains?|network(?:ed)?[- ]services?|network[- ]slic(?:e|ing)|deadline|datacenter|distributed[- ]systems?)\b",re.I)
def normalize_title(title):
    return ''.join(ch for ch in unicodedata.normalize('NFKC',str(title or '')).casefold() if ch.isalnum())
def is_anrc_related(title,abstract):
    text=str(title or '')+' '+str(abstract or '')
    return bool(TARGET_RECOVERY.search(text) and TARGET_CONTEXT.search(text))
def choose(scored_rows,sent_keys=(),*,limit=3,margin=0.5):
    """Preserve the upstream score; allow an optional near-top A-NRC paper."""
    if limit!=3 or not 0<=margin<=1:
        raise ValueError("R4-1 policy is 3 papers with a small research margin")
    sent=set(sent_keys);seen=set();candidates=[]
    for raw in scored_rows:
        row=dict(raw);key=str(row.get('paper_key') or '').strip()
        if not key or key in sent or key in seen:continue
        seen.add(key)
        if row.get('candidate_status')!='PRELIMINARY':continue
        try:score=float(row['score'])
        except (ValueError,TypeError,KeyError):continue
        if not math.isfinite(score) or not str(row.get('abstract') or '').strip():continue
        row['score']=score
        row['anrc_keyword_match']=is_anrc_related(row.get('title'),row.get('abstract'))
        candidates.append(row)
    ordered=sorted(candidates,key=lambda r:(-r['score'],r['paper_key']))
    selected=ordered[:limit]
    if len(selected)==limit and not any(r['anrc_keyword_match'] for r in selected):
        cutoff=selected[-1]['score']-margin
        related=next((r for r in ordered[limit:] if r['anrc_keyword_match'] and r['score']>=cutoff),None)
        if related:
            selected[-1]=related
            selected.sort(key=lambda r:(-r['score'],r['paper_key']))
    return {
       'max_papers':limit,'selected':selected,'eligible_scored_count':len(ordered),
       'anrc_keyword_match_count':sum(bool(r['anrc_keyword_match']) for r in selected),
       'preview_only':True,'email_sent':False,
       'score_method':'upstream Zotero BaseReranker.rerank; no publication-date bonus',
       'research_match_note':'Conservative keyword proxy; human review required'
    }
