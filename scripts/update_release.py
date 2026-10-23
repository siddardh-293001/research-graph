"""Build a new immutable release from bounded candidates; never mutate the active one."""
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import faiss
import numpy as np
from src.corpus import canonical_doi, canonical_arxiv
from src.incremental import timestamp, distribution_drift
from src.paper_insights import summarize
from src.public_engine import PublicEngine, digest


def update(source, candidates, output, max_papers=25000):
    source,output=Path(source),Path(output)
    if output.exists():raise ValueError('Output must be a fresh immutable release directory')
    if len(candidates)>500:raise ValueError('Maximum 500 candidate records per update')
    engine=PublicEngine(source)
    if engine.manifest.get('schema_version',1)<2:raise ValueError('Enriched release required')
    with closing(engine.connect()) as db:
        papers=[dict(r) for r in db.execute('SELECT * FROM papers ORDER BY row_id')]
        insights={r['paper_id']:dict(r) for r in db.execute('SELECT * FROM insights')}
        themes=[tuple(r) for r in db.execute('SELECT * FROM paper_topics')]
        names={r['topic_key']:r['name'] for r in db.execute('SELECT * FROM research_topics')}
        citations=set(tuple(r) for r in db.execute('SELECT source,target FROM citations'))
    by_id={p['paper_id']:p for p in papers};by_doi={canonical_doi(p['doi']):p['paper_id'] for p in papers if canonical_doi(p['doi'])}
    aliases={p['paper_id']:p['paper_id'] for p in papers}
    vectors={p['paper_id']:np.array(engine.vectors[p['row_id']]) for p in papers}
    changed=set();removed=set();assigned=[];references={};counts=Counter()
    for raw in candidates:
        row=dict(raw);pid=row.get('paper_id')
        if not isinstance(pid,str) or not (re.fullmatch(r'https://openalex.org/W\d+',pid) or pid.startswith('https://arxiv.org/abs/') or pid.startswith('https://doi.org/')):raise ValueError('Unsupported paper identity')
        if pid.startswith('https://arxiv.org/abs/'):
            identity=canonical_arxiv(pid)
            if not identity:raise ValueError('Invalid arXiv identity')
            pid='https://arxiv.org/abs/'+identity
        doi=canonical_doi(row.get('doi'));matches={x for x in [pid if pid in by_id else None,by_doi.get(doi)] if x}
        if len(matches)>1:raise ValueError('Conflicting identities require reconciliation')
        stable=next(iter(matches),pid);aliases[pid]=stable;pid=stable
        previous=by_id.get(pid);old=insights.get(pid)
        if previous and row.get('source') in {'crossref','arxiv'} and not pid.startswith('https://arxiv.org/abs/'):
            counts['supplemental_only']+=1;continue
        if old and timestamp(row.get('updated_date'))<=timestamp(old.get('source_updated_at')):
            counts['stale_or_replayed']+=1;continue
        if row.get('is_retracted'):
            if previous:removed.add(pid);counts['removed_retracted']+=1
            continue
        title=str(row.get('title') or '').strip();abstract=str(row.get('abstract') or '').strip()
        if not title or len(abstract.split())<30:counts['insufficient_abstract']+=1;continue
        year=row.get('year');citations_count=row.get('citation_count',0)
        if type(year) is not int or not 1900<=year<=2100 or type(citations_count) is not int or citations_count<0:raise ValueError('Invalid year or citation count')
        if previous and previous['title']==title and previous['abstract']==abstract:vector=vectors[pid]
        else:vector=engine.encode(title+'. '+abstract)
        _,neighbors=engine.index.search(vector[None,:],5);neighbor_rows=[int(i) for i in neighbors[0] if i>=0]
        def vote(key):
            votes=Counter(papers[i][key] for i in neighbor_rows);return min(votes,key=lambda x:(-votes[x],x))
        nearest=papers[neighbor_rows[0]];topic=previous['topic_id'] if previous else vote('topic_id');community=previous['community'] if previous else vote('community')
        by_id[pid]=dict(row_id=0,paper_id=pid,title=title,abstract=abstract,year=year,citation_count=citations_count,topic_id=topic,topic_name=previous['topic_name'] if previous else next(p['topic_name'] for p in papers if p['topic_id']==topic),community=community,doi=doi)
        vectors[pid]=vector;changed.add(pid);removed.discard(pid)
        if doi:by_doi[doi]=pid
        if not previous:assigned.append(community)
        counts['updated' if previous else 'added']+=1
        insights[pid]=dict(citation_source={'arxiv':'arXiv','crossref':'Crossref'}.get(row.get('source'),'OpenAlex'),citation_count_available=int(row.get('citation_count_available',True)),paper_id=pid,summary=json.dumps(summarize(title,abstract)),authors=json.dumps([a['name'] for a in row.get('authors',[]) if a.get('name')]),keywords=json.dumps([k['name'] for k in row.get('keywords',[]) if k.get('name')][:12]),publication_date=str(row.get('publication_date') or ''),source_updated_at=str(row.get('updated_date') or ''),reference_count=len(set(row.get('referenced_works') or [])),open_access=int(bool(row.get('is_open_access'))))
        themes=[t for t in themes if t[0]!=pid]
        for t in row.get('topics') or []:
            key=str(t.get('id') or '').rsplit('/',1)[-1];score=float(t.get('score') or 0)
            if re.fullmatch(r'T\d+',key) and t.get('name') and np.isfinite(score) and score>0:
                names[key]=t['name'];themes.append((pid,key,score))
        references[pid]=set(row.get('referenced_works') or [])
    for pid in removed:by_id.pop(pid,None);vectors.pop(pid,None);insights.pop(pid,None)
    if not changed and not removed:return {'changed':False,'counts':dict(counts)}
    ids=list(by_id)
    if len(ids)>max_papers:raise ValueError('Free-serving capacity gate: evaluate Tier M before expanding beyond 25,000')
    drift=distribution_drift([p['community'] for p in papers],assigned) if assigned else 0.
    if len(assigned)>=50 and drift>.1:raise ValueError('Community drift exceeds automatic promotion threshold')
    shutil.copytree(source,output)
    try:
        values=np.asarray([vectors[pid] for pid in ids],dtype=np.float32);index=faiss.IndexHNSWFlat(values.shape[1],32,faiss.METRIC_INNER_PRODUCT);index.hnsw.efConstruction=200;index.hnsw.efSearch=128;index.add(values)
        with closing(sqlite3.connect(output/'corpus.sqlite')) as db,db:
            if 'observed_at' not in [r[1] for r in db.execute('PRAGMA table_info(insights)')]:db.execute('ALTER TABLE insights ADD COLUMN observed_at TEXT')
            for name,kind in [('citation_source','TEXT'),('citation_count_available','INTEGER')]:
                if name not in [r[1] for r in db.execute('PRAGMA table_info(insights)')]:db.execute('ALTER TABLE insights ADD COLUMN '+name+' '+kind)
            for table in ['papers','insights','citations','neighbors','paper_topics','research_topics']:db.execute('DELETE FROM '+table)
            for i,pid in enumerate(ids):
                p=by_id[pid];p['row_id']=i
                db.execute('INSERT INTO papers VALUES (?,?,?,?,?,?,?,?,?,?)',tuple(p[k] for k in ['row_id','paper_id','title','abstract','year','citation_count','topic_id','topic_name','community','doi']))
                d=insights[pid];db.execute('INSERT INTO insights (paper_id,summary,authors,keywords,publication_date,source_updated_at,reference_count,open_access) VALUES (?,?,?,?,?,?,?,?)',tuple(d[k] for k in ['paper_id','summary','authors','keywords','publication_date','source_updated_at','reference_count','open_access']))
            db.executemany('UPDATE insights SET observed_at=? WHERE paper_id=?',[(datetime.now(timezone.utc).isoformat() if pid in changed else insights[pid].get('observed_at'),pid) for pid in ids])
            db.executemany('UPDATE insights SET citation_source=?,citation_count_available=? WHERE paper_id=?',[(insights[pid].get('citation_source') or 'OpenAlex',insights[pid].get('citation_count_available',1) if insights[pid].get('citation_count_available') is not None else 1,pid) for pid in ids])
            valid=set(ids);citations={(s,t) for s,t in citations if s in valid and t in valid and s not in references}
            for s,targets in references.items():citations.update((s,aliases.get(t,t)) for t in targets if s in valid and aliases.get(t,t) in valid)
            db.executemany('INSERT INTO citations VALUES (?,?)',sorted(citations))
            themes=sorted(set(t for t in themes if t[0] in valid));db.executemany('INSERT OR REPLACE INTO paper_topics VALUES (?,?,?)',themes)
            topic_counts=Counter(t[1] for t in themes);db.executemany('INSERT INTO research_topics VALUES (?,?,?)',[(k,names[k],v) for k,v in topic_counts.items()])
            for start in range(0,len(ids),128):
                weights,rows=index.search(values[start:start+128],16)
                db.executemany('INSERT INTO neighbors VALUES (?,?,?)',[(start+i,int(j),float(w)) for i in range(len(rows)) for j,w in zip(rows[i],weights[i]) if j>=0 and j!=start+i])
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Database integrity failed')
        faiss.write_index(index,str(output/'index.faiss'));np.save(output/'vectors.npy',values,allow_pickle=False);np.save(output/'ids.npy',np.array(ids,dtype=str),allow_pickle=False)
        np.save(output/'years.npy',np.array([by_id[p]['year'] for p in ids],dtype=np.int32),allow_pickle=False);np.save(output/'topics.npy',np.array([by_id[p]['topic_id'] for p in ids],dtype=np.int32),allow_pickle=False)
        postings=defaultdict(list);lengths=[]
        for i,pid in enumerate(ids):
            p=by_id[pid];tokens=engine.tokenize(p['title']+'. '+p['abstract']);lengths.append(len(tokens))
            for term,tf in Counter(tokens).items():postings[term].append((i,tf))
        vocabulary={};rows=[];freq=[]
        for term in sorted(postings):
            start=len(rows)
            for row,tf in postings[term]:rows.append(row);freq.append(tf)
            vocabulary[term]=[start,len(rows)]
        np.savez_compressed(output/'lexical.npz',lengths=np.array(lengths),rows=np.array(rows,dtype=np.int32),tf=np.array(freq,dtype=np.int32));(output/'vocabulary.json').write_text(json.dumps(vocabulary))
        manifest=dict(engine.manifest);now=datetime.now(timezone.utc).isoformat();parent=digest(source/'release.json')
        manifest.update(schema_version=3,papers=len(ids),run_id='update-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),updated_at=now,parent_release_sha256=parent,year_min=min(by_id[p]['year'] for p in ids),year_max=max(by_id[p]['year'] for p in ids),research_topics=[{'topic_key':k,'name':names[k],'papers':v} for k,v in sorted(topic_counts.items(),key=lambda kv:(-kv[1],names[kv[0]]))],feed={'mode':'scheduled','live_updates':True,'updated_at':now,'description':'Verified scheduled release; source indexing delays apply.'})
        manifest['topics']=[{'topic_id':int(k),'name':next(p['topic_name'] for p in by_id.values() if p['topic_id']==k),'papers':v} for k,v in sorted(Counter(p['topic_id'] for p in by_id.values()).items())]
        manifest['update_report']={'counts':dict(counts),'distribution_js_bits':drift,'assignment':'Frozen community and topic assignment by 5-neighbor vote; graph rebuilt using HNSW top-15 directed neighbors.','source_freshness':'Only observed records refreshed; original snapshot citation counts retain their original date.'}
        manifest['artifacts']={p.name:digest(p) for p in output.iterdir() if p.is_file() and p.name!='release.json'};(output/'release.json').write_text(json.dumps(manifest,indent=2)+'\n')
        return {'changed':True,'papers':len(ids),'release_sha256':digest(output/'release.json'),'counts':dict(counts),'drift':drift}
    except BaseException:
        shutil.rmtree(output);raise

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=ROOT/'build/release');p.add_argument('--candidates',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(update(a.source,json.loads(a.candidates.read_text()),a.output),indent=2))
