"""Gate an incremental release with independent relevance, ANN and evidence checks."""
from contextlib import closing
import argparse
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from src.public_engine import PublicEngine
from src.evaluation import retrieval_metrics


def check(source,candidate):
    previous=PublicEngine(source);current=PublicEngine(candidate)
    if current.manifest.get('parent_release_sha256')!=previous.release_sha256:raise ValueError('Update parent hash mismatch')
    if not 1<=len(current.ids)<=25000:raise ValueError('Capacity gate failed')
    with closing(current.connect()) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('SQLite integrity failed')
        if db.execute('SELECT count(*) FROM papers').fetchone()[0]!=len(current.ids):raise ValueError('Row count mismatch')
        if db.execute('SELECT count(*) FROM insights').fetchone()[0]!=len(current.ids):raise ValueError('Insight count mismatch')
        for row,pid in enumerate(current.ids):
            paper=db.execute('SELECT paper_id FROM papers WHERE row_id=?',(row,)).fetchone()
            if paper is None or paper[0]!=pid:raise ValueError('Paper order mismatch')
        for pid in current.ids[-min(20,len(current.ids)):]:
            paper=current.paper(str(pid))
            if any(s not in paper['abstract'] for s in paper['summary']['sentences']):raise ValueError('Ungrounded summary')
    benchmark=json.loads((ROOT/'data/benchmark/effective.json').read_text())['queries']
    deltas={m:[] for m in ['bm25','dense','hybrid']}
    for q in benchmark:
        for mode in deltas:
            a,_=previous.search(q['query'],mode,20);b,_=current.search(q['query'],mode,20)
            qrels={j['paper_id']:j['grade'] for j in q['judgments']}
            x=retrieval_metrics([p['paper_id'] for p in a],qrels);y=retrieval_metrics([p['paper_id'] for p in b],qrels)
            deltas[mode].append({k:y[k]-x[k] for k in ['ndcg_at_10','recall_at_20']})
    metrics={m:{k:float(np.mean([r[k] for r in values])) for k in values[0]} for m,values in deltas.items()}
    if any(v<-.005 for d in metrics.values() for v in d.values()):raise ValueError('Incremental relevance regression exceeds 0.005')
    selected=np.random.default_rng(42).choice(len(current.ids),min(50,len(current.ids)),replace=False);recalls=[]
    for i in selected:
        vector=np.asarray(current.vectors[i]);scores=current.vectors@vector;exact=set(np.lexsort((current.ids,-scores))[:10]);_,rows=current.index.search(vector[None,:],10);recalls.append(len(exact&set(rows[0]))/10)
    if np.mean(recalls)<.95:raise ValueError('ANN recall below 0.95')
    result=subprocess.run([sys.executable,str(ROOT/'scripts/check_public.py'),'--release',str(candidate),'--memory-only'],capture_output=True,text=True,check=True)
    memory=json.loads(result.stdout.strip().splitlines()[-1])
    return {'passed':True,'parent_release_sha256':previous.release_sha256,'release_sha256':current.release_sha256,'papers':len(current.ids),'queries':len(benchmark),'mean_metric_differences':metrics,'ann_recall_at_10':float(np.mean(recalls)),'serving_memory':memory,'limitations':['Incomplete provisional relevance labels; publication-date polling misses historical corrections.','New community/topic assignments are provisional frozen-label neighbor votes.']}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=check(a.source,a.candidate);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
