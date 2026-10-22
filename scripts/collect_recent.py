"""Collect a bounded anonymous/free AI+CS candidate batch, never auto-publish it."""
import argparse
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import requests
from src.ingestion.openalex import normalize_paper
from src.incremental import apply_batch


def collect(output,pages=5,session=None,today=None):
    if type(pages) is not int or not 1<=pages<=5:raise ValueError('Maximum five anonymous requests per run')
    output=Path(output)
    if output.exists():raise ValueError('Use a new batch directory')
    output.mkdir(parents=True)
    now=today or datetime.now(timezone.utc);since=(now-timedelta(days=14)).date().isoformat()
    http=session or requests.Session()
    # Intentionally never load .env, account API keys, netrc credentials or auth headers.
    if session is None:http.trust_env=False
    records={};requests_made=0;source_count=None
    for page in range(1,pages+1):
        response=http.get('https://api.openalex.org/works',params={
            'filter':f'topics.field.id:17,from_publication_date:{since},to_publication_date:{now.date().isoformat()},has_abstract:true,is_retracted:false',
            'sort':'publication_date:desc','per_page':100,'page':page},timeout=45,allow_redirects=False)
        requests_made+=1
        if response.status_code!=200:raise RuntimeError(f'Anonymous OpenAlex returned HTTP {response.status_code}; no authenticated or paid fallback is allowed')
        payload=response.json()
        if not isinstance(payload.get('results'),list):raise ValueError('Invalid source response')
        source_count=payload.get('meta',{}).get('count')
        (output/f'page-{page:02d}.json').write_text(json.dumps(payload)+'\n')
        for work in payload['results']:
            row=normalize_paper(work)
            if row['paper_id'] and row['title'] and row['abstract']:records[row['paper_id']]=row
        if len(payload['results'])<100:break
        if page<pages:time.sleep(.2)
    rows=sorted(records.values(),key=lambda row:row['paper_id'])
    (output/'candidates.json').write_text(json.dumps(rows)+'\n')
    staged=apply_batch(output/'ledger.sqlite',rows,observed_at=now.isoformat())
    report={'scope':'Anonymous recent-publication poll of Computer Science field 17; staged candidates only',
            'started_at':now.isoformat(),'finished_at':datetime.now(timezone.utc).isoformat(),
            'since':since,'requests':requests_made,'papers':len(rows),'matching_source_count':source_count,
            'truncated':source_count is None or source_count>len(rows),'authenticated':False,'paid_spend_usd':0,
            'publication':'Not published: embeddings, assignments, drift and relevance gates still required',
            'ledger':staged,'candidate_sha256':hashlib.sha256((output/'candidates.json').read_bytes()).hexdigest(),
            'limitations':['Overlapping 14-day window; may miss late-indexed and older corrected/retracted work.','Maximum 500 source rows; dense publication periods are truncated.','No automatic promotion to the public snapshot.']}
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--pages',type=int,default=5);a=p.parse_args();print(json.dumps(collect(a.output,a.pages),indent=2))
