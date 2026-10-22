"""Add grounded paper insights to a fresh copy of a verified serving release."""
from contextlib import closing
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd
from src.public_engine import digest
from src.paper_insights import summarize


def enrich(source, run, output):
    source,run,output=map(Path,(source,run,output))
    if output.exists():raise ValueError('Use a fresh output directory')
    manifest=json.loads((source/'release.json').read_text())
    provenance=json.loads((run/'manifest.json').read_text())
    if digest(run/'manifest.json')!=manifest['source_manifest_sha256']:raise ValueError('Source run mismatch')
    for name in ['embedded_papers.parquet','citation_edges.parquet']:
        if digest(run/name)!=provenance['artifacts'][name]:raise ValueError('Source integrity failure')
    for name,sha in manifest['artifacts'].items():
        if digest(source/name)!=sha:raise ValueError('Release integrity failure')
    shutil.copytree(source,output)
    papers=pd.read_parquet(run/'embedded_papers.parquet')
    edges=pd.read_parquet(run/'citation_edges.parquet')
    with closing(sqlite3.connect(output/'corpus.sqlite')) as db, db:
        db.execute('CREATE TABLE insights (paper_id TEXT PRIMARY KEY, summary TEXT, authors TEXT, keywords TEXT, publication_date TEXT, source_updated_at TEXT, reference_count INTEGER, open_access INTEGER)')
        db.execute('CREATE TABLE research_topics (topic_key TEXT PRIMARY KEY, name TEXT NOT NULL, papers INTEGER NOT NULL)')
        db.execute('CREATE TABLE paper_topics (paper_id TEXT, topic_key TEXT, score REAL, PRIMARY KEY(paper_id,topic_key)) WITHOUT ROWID')
        db.execute('CREATE INDEX paper_topics_by_topic ON paper_topics(topic_key,paper_id)')
        db.execute('CREATE TABLE citations (source TEXT, target TEXT, PRIMARY KEY(source,target)) WITHOUT ROWID')
        db.execute('CREATE INDEX citations_by_target ON citations(target,source)')
        counts=Counter();names={}
        for row in papers.to_dict('records'):
            pid=row['paper_id']
            authors=[a.get('name') for a in (row.get('authors') if row.get('authors') is not None else []) if a.get('name')]
            keywords=[k.get('name') for k in (row.get('keywords') if row.get('keywords') is not None else []) if k.get('name')]
            refs=list((row.get('referenced_works') if row.get('referenced_works') is not None else []))
            db.execute('INSERT INTO insights VALUES (?,?,?,?,?,?,?,?)',(pid,json.dumps(summarize(row['title'],row['abstract'])),json.dumps(authors),json.dumps(keywords[:12]),str(row.get('publication_date') or ''),str(row.get('updated_date') or ''),len(set(refs)),int(bool(row.get('is_open_access')))))
            seen=set()
            for t in (row.get('topics') if row.get('topics') is not None else []):
                key=t.get('id','').rsplit('/',1)[-1];score=float(t.get('score') or 0)
                if not key.startswith('T') or not key[1:].isdigit() or not t.get('name') or score<=0 or key in seen:continue
                seen.add(key);names[key]=t['name'];counts[key]+=1
                db.execute('INSERT INTO paper_topics VALUES (?,?,?)',(pid,key,score))
        db.executemany('INSERT INTO research_topics VALUES (?,?,?)',[(k,names[k],v) for k,v in counts.items()])
        db.executemany('INSERT OR IGNORE INTO citations VALUES (?,?)',edges[['source','target']].itertuples(index=False,name=None))
        db.execute('CREATE INDEX insights_by_publication ON insights(publication_date DESC,paper_id)')
    manifest.update(schema_version=2,enriched_at=datetime.now(timezone.utc).isoformat(),
        research_topics=[{'topic_key':k,'name':names[k],'papers':v} for k,v in sorted(counts.items(),key=lambda kv:(-kv[1],names[kv[0]]))],
        insight_methods={'summary':'extractive abstract sentences','connections':'semantic cosine and directed snapshot citation edges','topics':'positive-score OpenAlex assignments; multi-label'},
        feed={'mode':'snapshot','live_updates':False,'description':'Latest publications in this release; not a live ingestion stream.'})
    manifest['artifacts']={f.name:digest(f) for f in output.iterdir() if f.is_file() and f.name!='release.json'}
    (output/'release.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'papers':len(papers),'research_topics':len(counts),'citation_edges':len(edges),'output':str(output)}))
    return output

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();enrich(a.source,a.run,a.output)
