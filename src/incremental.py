"""Section 7A: transactional replay ledger and bounded incremental assignment.

This stages normalized metadata. It does not silently mutate a published release
or claim that a metadata-only update has refreshed embeddings or graphs.
"""
from contextlib import closing
import hashlib
import json
from datetime import datetime, timezone
import sqlite3
from collections import Counter
import numpy as np
from src.corpus import canonical_doi, canonical_arxiv


def timestamp(value):
    if not value:return datetime.min.replace(tzinfo=timezone.utc)
    parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def validate(row):
    if not isinstance(row.get('paper_id'),str) or not row['paper_id'].startswith('https://openalex.org/W'):raise ValueError('Expected OpenAlex work identity')
    if not str(row.get('title') or '').strip():raise ValueError('Title is required')
    count=row.get('citation_count',0)
    if isinstance(count,bool) or not isinstance(count,(int,float)) or not np.isfinite(count) or count<0:raise ValueError('Invalid citation count')
    timestamp(row.get('updated_date'))


def apply_batch(path, records, observed_at=None):
    records=[dict(r) for r in records]
    for row in records:validate(row)
    payload=json.dumps(records,sort_keys=True,separators=(',',':'),allow_nan=False)
    batch=hashlib.sha256(payload.encode()).hexdigest()
    observed_at=observed_at or datetime.now(timezone.utc).isoformat();timestamp(observed_at)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS works (paper_id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT, needs_rebuild INTEGER NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS identities (identity TEXT PRIMARY KEY, paper_id TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS batches (batch_id TEXT PRIMARY KEY, observed_at TEXT, report TEXT)')
        existing=db.execute('SELECT report FROM batches WHERE batch_id=?',(batch,)).fetchone()
        if existing:return {**json.loads(existing[0]),'replayed':True}
        counts=Counter(added=0,updated=0,unchanged=0,stale=0,retracted=0)
        for row in records:
            keys=['id:'+row['paper_id']]
            doi=canonical_doi(row.get('doi')); arxiv=canonical_arxiv(row.get('arxiv_id')) or canonical_arxiv(row.get('doi'))
            if doi:keys.append('doi:'+doi)
            if arxiv:keys.append('arxiv:'+arxiv)
            matched={r[0] for key in keys if (r:=db.execute('SELECT paper_id FROM identities WHERE identity=?',(key,)).fetchone())}
            if len(matched)>1:raise ValueError('Identity bridge requires reconciliation; batch rolled back')
            pid=next(iter(matched),row['paper_id']);old=db.execute('SELECT payload,updated_at FROM works WHERE paper_id=?',(pid,)).fetchone()
            row['paper_id']=pid; encoded=json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False)
            if old and timestamp(row.get('updated_date'))<timestamp(old[1]):counts['stale']+=1;continue
            if old and encoded==old[0]:counts['unchanged']+=1;continue
            if old and timestamp(row.get('updated_date'))==timestamp(old[1]):raise ValueError('Conflicting metadata at identical source timestamp; batch rolled back')
            counts['updated' if old else 'added']+=1
            counts['retracted']+=int(bool(row.get('is_retracted')))
            db.execute('INSERT OR REPLACE INTO works VALUES (?,?,?,1)',(pid,encoded,row.get('updated_date')))
            for key in keys:db.execute('INSERT OR IGNORE INTO identities VALUES (?,?)',(key,pid))
        report={'batch_id':batch,'observed_at':observed_at,'replayed':False,**dict(counts),
                'total_staged':db.execute('SELECT count(*) FROM works').fetchone()[0],
                'pending_rebuild':db.execute('SELECT count(*) FROM works WHERE needs_rebuild=1').fetchone()[0],
                'publication':'staged only; build, integrity and relevance gates required before promotion'}
        db.execute('INSERT INTO batches VALUES (?,?,?)',(batch,observed_at,json.dumps(report)))
        return report


def assign_neighbors(base_vectors, base_labels, new_vectors, k=5, block_size=128):
    """Assign frozen labels by positive-cosine weighted nearest-neighbor vote."""
    base=np.asarray(base_vectors,dtype=np.float32);new=np.asarray(new_vectors,dtype=np.float32);labels=np.asarray(base_labels)
    if base.ndim!=2 or new.ndim!=2 or base.shape[1]!=new.shape[1] or len(base)!=len(labels) or not len(base):raise ValueError('Misaligned assignment inputs')
    if k<1 or block_size<1 or not np.isfinite(base).all() or not np.isfinite(new).all():raise ValueError('Invalid assignment input')
    if np.any(np.linalg.norm(base,axis=1)==0) or np.any(np.linalg.norm(new,axis=1)==0):raise ValueError('Zero vector')
    base=base/np.linalg.norm(base,axis=1,keepdims=True);new=new/np.linalg.norm(new,axis=1,keepdims=True)
    assigned=[]; confidence=[]
    for start in range(0,len(new),block_size):
        scores=new[start:start+block_size]@base.T
        for row in scores:
            order=np.lexsort((np.arange(len(base)),-row))[:min(k,len(base))]
            votes=Counter()
            for i in order:
                if row[i]>0:votes[int(labels[i])]+=float(row[i])
            winner=min(votes,key=lambda label:(-votes[label],label)) if votes else -1
            assigned.append(winner);confidence.append(float(row[order[0]]))
    return np.array(assigned),np.array(confidence)


def distribution_drift(before,after):
    """Jensen-Shannon divergence in bits, bounded [0,1]; not a significance test."""
    a,b=Counter(before),Counter(after); keys=sorted(a.keys()|b.keys())
    if not a or not b:raise ValueError('Both distributions must be nonempty')
    p=np.array([a[k]/sum(a.values()) for k in keys]);q=np.array([b[k]/sum(b.values()) for k in keys]);m=(p+q)/2
    def kl(x):
        valid=x>0;return float(np.sum(x[valid]*np.log2(x[valid]/m[valid])))
    return (kl(p)+kl(q))/2


def update_drift(base_labels, added_labels, final_labels, reference_counts=None):
    """Batch novelty is diagnostic; cumulative corpus shift is a promotion gate."""
    counts=reference_counts or dict(Counter(int(x) for x in base_labels))
    reference=[int(label) for label,count in counts.items() for _ in range(int(count))]
    batch=distribution_drift(base_labels,added_labels) if len(added_labels) else 0.
    global_drift=distribution_drift(reference,final_labels)
    if global_drift>.1:raise ValueError('Cumulative corpus drift exceeds 0.1 bits; review required')
    return {'batch_js_bits':batch,'batch_warning':len(added_labels)>=50 and batch>.1,'corpus_js_bits':global_drift,'reference_counts':counts}
