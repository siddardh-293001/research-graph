"""Bounded, evidence-labelled exploration of the local scholarly snapshot."""
from contextlib import closing
import json
import re


def browse(engine, query='', field='title', sort='newest', page=1, year_min=None, year_max=None):
    columns={'title':'p.title','abstract':'p.abstract','doi':'p.doi','author':'a.value'}
    if field not in columns or sort not in {'newest','citations','title'}:
        raise ValueError('Unsupported field or sort')
    joins=' JOIN insights i USING(paper_id), json_each(i.authors) a' if field=='author' else ''
    conditions=[columns[field]+" LIKE ? ESCAPE '\\'"]
    args=['%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%']
    for value,op in [(year_min,'>='),(year_max,'<=')]:
        if value is not None:conditions.append('p.year'+op+'?');args.append(value)
    source=' FROM papers p'+joins+' WHERE '+' AND '.join(conditions)
    order={'newest':'p.year DESC,p.paper_id','citations':'p.citation_count DESC,p.paper_id','title':'p.title,p.paper_id'}[sort]
    with closing(engine.connect()) as db:
        total=db.execute('SELECT count(DISTINCT p.paper_id)'+source,args).fetchone()[0]
        rows=[dict(r) for r in db.execute('SELECT DISTINCT p.*'+source+' ORDER BY '+order+' LIMIT 20 OFFSET ?',args+[(page-1)*20])]
    with closing(engine.connect()) as db:
        matching_ids=[r[0] for r in db.execute('SELECT DISTINCT p.paper_id'+source+' ORDER BY p.paper_id LIMIT 25000',args)]
    return {'matching_ids':matching_ids,'release_sha256':getattr(engine,'release_sha256',None),'results':rows,'total':total,'page':page,'page_size':20,'scope':'Field matching across this atlas; citation sorting uses snapshot counts.'}


def evidence(engine,paper_id,question=''):
    paper=engine.paper(paper_id)
    if paper is None:return None
    with closing(engine.connect()) as db:
        timeline=[dict(r) for r in db.execute('SELECT p.year,count(*) AS count FROM citations c JOIN papers p ON p.paper_id=c.source WHERE c.target=? GROUP BY p.year ORDER BY p.year',(paper_id,))]
        links={direction:[dict(r) for r in db.execute('SELECT p.paper_id,p.title,p.year,p.citation_count FROM citations c JOIN papers p ON p.paper_id=c.'+other+' WHERE c.'+own+'=? ORDER BY p.citation_count DESC,p.paper_id LIMIT 100',(paper_id,))] for direction,own,other in [('references','source','target'),('citing','target','source')]}
    sentences=re.split(r'(?<=[.!?])\s+',paper['abstract'])
    terms=set(engine.tokenize(question))
    matches=sorted([(len(terms&set(engine.tokenize(s))),i,s) for i,s in enumerate(sentences)],key=lambda x:(-x[0],x[1]))
    passages=[{'text':s,'sentence':i+1,'source':'abstract','paper_id':paper_id} for score,i,s in matches[:3] if score]
    patterns={'question':r'aim|investigat|problem|question|propose','methods':r'method|approach|model|framework','datasets':r'dataset|benchmark|corpus|data set','findings':r'result|find|achiev|improv','limitations':r'limit|however|challenge|future'}
    matrix={k:[{'text':s,'sentence':i+1} for i,s in enumerate(sentences) if re.search(pattern,s,re.I)][:2] for k,pattern in patterns.items()}
    return {'timeline':timeline,'timeline_scope':'Publication years of citing papers recorded in this atlas, not global annual citation counts.','links':links,'links_limit':100,'passages':passages,'answer_scope':'Extractive abstract passage lookup; no generated answer or full-text reasoning. No match means the abstract provides no matching passage.','matrix':matrix,'matrix_scope':'Keyword-selected abstract excerpts; categories require researcher review. Empty cells mean not identified, not absent.','open_access':bool(paper.get('open_access')),'full_text_url':None,'full_text_scope':'The snapshot records access status but contains no verified PDF URLs.'}


def trends(engine):
    with closing(engine.connect()) as db:
        years=[dict(r) for r in db.execute('SELECT year,topic_name,count(*) AS papers FROM papers GROUP BY year,topic_name ORDER BY year,topic_name')]
        gaps=[dict(r) for r in db.execute('SELECT a.topic_name AS topic_a,b.topic_name AS topic_b,count(*) AS links FROM citations c JOIN papers a ON a.paper_id=c.source JOIN papers b ON b.paper_id=c.target WHERE a.topic_id!=b.topic_id GROUP BY a.topic_id,b.topic_id ORDER BY links,a.topic_id,b.topic_id LIMIT 12')]
    return {'years':years,'leads':gaps,'scope':'Selective corpus counts, not field-wide growth. Sparse observed cross-topic citation links are exploration leads, not proof of a research gap; coverage and topic size confound them.'}


def source_metadata(paper_id):
    """One anonymous OpenAlex singleton request; never uses a saved API key."""
    import urllib.request
    from urllib.parse import urlparse
    if not re.fullmatch(r'https://openalex.org/W[0-9]{1,20}',paper_id):
        return {'available':False,'reason':'Live metadata lookup requires an OpenAlex work ID.'}
    request=urllib.request.Request('https://api.openalex.org/works/'+paper_id.rsplit('/',1)[-1],headers={'User-Agent':'ResearchGraph/0.7'})
    with urllib.request.urlopen(request,timeout=10) as response:
        raw=response.read(2_000_001)
    if len(raw)>2_000_000:raise ValueError('Source response too large')
    work=json.loads(raw);location=work.get('best_oa_location') or {}
    url=location.get('pdf_url') or location.get('landing_page_url')
    if not isinstance(url,str) or urlparse(url).scheme not in {'https','http'}:url=None
    return {'authors':[{'name':a.get('author',{}).get('display_name'),'id':a.get('author',{}).get('id'),'orcid':a.get('author',{}).get('orcid')} for a in work.get('authorships',[])],'available':True,'source':paper_id,'updated_date':work.get('updated_date'),'citations_by_year':work.get('counts_by_year',[]),'open_access_url':url,'venue':((work.get('primary_location') or {}).get('source') or {}).get('display_name'),'scope':'Current source-reported metadata; annual citation coverage may be incomplete. Open-access link availability is reported by OpenAlex, not a guarantee that the remote file remains accessible.'}
