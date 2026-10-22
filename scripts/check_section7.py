"""Verify enriched paper evidence and replay incremental assignments offline."""
from contextlib import closing
import argparse
import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
from sklearn.metrics import adjusted_mutual_info_score
from src.artifacts import latest_tier_s_run
from src.incremental import apply_batch,assign_neighbors,distribution_drift
from src.public_engine import PublicEngine
from src.research_graph import knn_edges,graph_from_edges,leiden_partition


def check(release):
    run=latest_tier_s_run();papers=pd.read_parquet(run/'embedded_papers.parquet');engine=PublicEngine(release)
    with closing(engine.connect()) as db:
        assert db.execute('SELECT count(*) FROM insights').fetchone()[0]==len(papers)
        assert db.execute('SELECT count(*) FROM citations').fetchone()[0]==len(pd.read_parquet(run/'citation_edges.parquet'))
        candidates=[r[0] for r in db.execute('SELECT source FROM citations GROUP BY source ORDER BY count(*) DESC LIMIT 20')]
        for pid in candidates:
            detail=engine.paper(pid);abstract=detail['abstract']
            assert all(sentence in abstract for sentence in detail['summary']['sentences'])
            assert len(detail['summary']['sentences'])<=3
            assert detail['citation_context']['global_count']==detail['citation_count']
            for kind,rows in detail['connections'].items():
                for linked in rows:
                    source,target=(pid,linked['paper_id']) if kind=='cites' else (linked['paper_id'],pid)
                    assert db.execute('SELECT 1 FROM citations WHERE source=? AND target=?',(source,target)).fetchone()
        for topic in engine.manifest['research_topics'][:8]:
            result,_=engine.search('learning',mode='dense',top_k=5,research_topic=topic['topic_key'])
            assert result
            for r in result:assert db.execute('SELECT 1 FROM paper_topics WHERE paper_id=? AND topic_key=?',(r['paper_id'],topic['topic_key'])).fetchone()
    assert engine.feed(6)['live_updates'] is False
    vectors=np.load(run/'paper_embeddings.npy',mmap_mode='r')
    rng=np.random.default_rng(42);selected=rng.choice(len(papers),1200,replace=False)
    selected=sorted(selected,key=lambda i:(str(papers.iloc[i]['publication_date']),papers.iloc[i]['paper_id']))
    x=np.asarray(vectors[selected]);base_count=960
    start=perf_counter();base_labels=leiden_partition(graph_from_edges(base_count,knn_edges(x[:base_count],10)))
    assign_start=perf_counter();assigned,similarity=assign_neighbors(x[:base_count],base_labels,x[base_count:]);assignment_seconds=perf_counter()-assign_start
    full_labels=leiden_partition(graph_from_edges(len(x),knn_edges(x,10)))
    incremental_labels=np.concatenate([base_labels,assigned])
    drift=distribution_drift(base_labels,assigned)
    fields=['paper_id','doi','arxiv_id','title','abstract','year','citation_count','updated_date','is_retracted']
    records=json.loads(papers.iloc[selected][fields].to_json(orient='records'))
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'ledger.sqlite';initial=apply_batch(path,records[:base_count]);batch=apply_batch(path,records[base_count:]);replay=apply_batch(path,records[base_count:])
        assert initial['added']==base_count and batch['added']==240 and replay['replayed']
    base_bytes=(Path(release)/'vectors.npy').stat().st_size+(Path(release)/'index.faiss').stat().st_size
    return {'passed':True,'paper_insights_checked':len(candidates),'source_topics':len(engine.manifest['research_topics']),
            'citation_edges':136471,'summary':'extractive abstract only; no full-text synthesis',
            'incremental':{'scope':'Historical 1,200-paper sample sorted by publication date; 960 initial plus 240 replayed. Not a live ingest or 200k run.',
                'metadata_replay_idempotent':True,'assignment_method':'positive-cosine weighted 5-neighbor vote over frozen Leiden labels',
                'assignment_seconds':assignment_seconds,'incremental_vs_full_ami':float(adjusted_mutual_info_score(full_labels,incremental_labels)),
                'new_paper_ami':float(adjusted_mutual_info_score(full_labels[base_count:],assigned)),
                'distribution_js_bits':drift,'drift_warning':drift>.1,'unassigned':int((assigned<0).sum()),'median_nearest_cosine':float(np.median(similarity)),
                'evaluation_seconds':perf_counter()-start},
            'tier_m':{'built':False,'target_papers':200000,'vector_and_index_linear_bytes':base_bytes*10,
                      'scope':'Linear disk-size projection for the current representations, not a measured RAM requirement; model, metadata and postings add overhead.'},
            'live_collection_enabled':False,'paid_spend_usd':0,
            'limitations':['Recent-publication polling does not detect every historical correction or retraction.','Paid updated-date filters and paid compute are not enabled.','Incremental assignments are provisional and need full rebuild/relevance gates before promotion.','200k collection, embedding, ANN and hosted performance remain future gates.']}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--release',type=Path,default=ROOT/'build/release');p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=check(a.release);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
