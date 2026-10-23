"""Bounded free OpenAlex/arXiv/Crossref polling; no account credentials or paid fallbacks."""
from datetime import datetime,timedelta,timezone
import argparse
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import requests
from scripts.collect_recent import collect


def arxiv_records(xml):
    root=ET.fromstring(xml);ns={'a':'http://www.w3.org/2005/Atom','x':'http://arxiv.org/schemas/atom'};rows=[]
    for e in root.findall('a:entry',ns):
        text=lambda key:(e.findtext(key,default='',namespaces=ns) or '').strip()
        pid=text('a:id').replace('http://','https://');abstract=text('a:summary');date=text('a:published')
        if not pid.startswith('https://arxiv.org/abs/') or not date:continue
        rows.append({'paper_id':pid,'arxiv_id':pid,'doi':text('x:doi') or None,'title':' '.join(text('a:title').split()),'abstract':' '.join(abstract.split()),'year':int(date[:4]),'publication_date':date[:10],'updated_date':text('a:updated'),'citation_count':0,'authors':[{'name':a.findtext('a:name',namespaces=ns)} for a in e.findall('a:author',ns)],'topics':[],'keywords':[],'referenced_works':[],'is_open_access':True,'source':'arxiv','citation_count_available':False})
    return rows


def crossref_records(payload):
    rows=[]
    for work in payload.get('message',{}).get('items',[]):
        title=' '.join(work.get('title') or []);abstract=re.sub('<[^>]+>',' ',work.get('abstract') or '')
        if not re.search(r'language model|machine learning|neural|retrieval|robot|computer|software|cybersecurity|artificial intelligence',title+' '+abstract,re.I):continue
        doi=work.get('DOI');date=(work.get('published',{}).get('date-parts') or [[None]])[0];updated=work.get('indexed',{}).get('date-time')
        if not doi or not date[0]:continue
        rows.append({'paper_id':'https://doi.org/'+doi,'doi':doi,'title':title,'abstract':' '.join(abstract.split()),'year':date[0],'publication_date':'-'.join([str(date[0]),str(date[1] if len(date)>1 else 1).zfill(2),str(date[2] if len(date)>2 else 1).zfill(2)]),'updated_date':updated,'citation_count':work.get('is-referenced-by-count',0),'authors':[{'name':(' '.join([a.get('given',''),a.get('family','')])).strip()} for a in work.get('author',[])],'topics':[],'keywords':[],'referenced_works':[],'source':'crossref'})
    return rows


def collect_sources(output):
    output=Path(output)
    if output.exists():raise ValueError('Use a fresh collection directory')
    output.mkdir(parents=True);now=datetime.now(timezone.utc);since=now-timedelta(days=14);session=requests.Session();session.trust_env=False
    report=collect(output/'openalex',pages=1);rows=json.loads((output/'openalex/candidates.json').read_text());reports={'openalex':report}
    # One arXiv call per run; no repeated calls within the same three-second window.
    response=session.get('https://export.arxiv.org/api/query',params={'search_query':'(cat:cs.AI OR cat:cs.CL OR cat:cs.IR OR cat:cs.CV OR cat:cs.LG OR cat:cs.CR OR cat:cs.SE OR cat:cs.RO OR cat:cs.DC) AND lastUpdatedDate:['+since.strftime('%Y%m%d0000')+' TO '+now.strftime('%Y%m%d2359')+']','sortBy':'lastUpdatedDate','sortOrder':'descending','max_results':100},timeout=90)
    if response.status_code!=200:raise RuntimeError('arXiv returned HTTP '+str(response.status_code))
    (output/'arxiv.xml').write_text(response.text);arxiv=arxiv_records(response.text);rows.extend(arxiv);reports['arxiv']={'requests':1,'papers':len(arxiv),'truncated':len(arxiv)==100}
    response=session.get('https://api.crossref.org/works',params={'filter':'from-index-date:'+since.date().isoformat(),'query':'artificial intelligence machine learning computer software','rows':100,'sort':'indexed','order':'desc'},headers={'User-Agent':'ResearchGraph/0.7 (https://github.com/siddardh-293001/research-graph)'},timeout=90)
    if response.status_code!=200:raise RuntimeError('Crossref returned HTTP '+str(response.status_code))
    payload=response.json();(output/'crossref.json').write_text(json.dumps(payload));crossref=crossref_records(payload);rows.extend(crossref);reports['crossref']={'requests':1,'papers':len(crossref),'scope':'Deposited abstracts only; citation counts are Crossref counts, not OpenAlex counts.'}
    (output/'candidates.json').write_text(json.dumps(rows)+'\n');summary={'sources':reports,'papers':len(rows),'paid_spend_usd':0,'authenticated':False,'observed_at':now.isoformat(),'limitations':['Bounded recent windows, not complete historical/retraction synchronization.','arXiv does not supply citation counts; Crossref/OpenAlex counts are different measures.','An unavailable source aborts promotion; the previous release remains served.']};(output/'report.json').write_text(json.dumps(summary,indent=2)+'\n');return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(collect_sources(a.output),indent=2))
