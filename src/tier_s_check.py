"""Verify a completed Tier S run, its raw provenance and exact-reference ANN recall."""
import argparse
import json
from pathlib import Path
import tempfile
import numpy as np
import pandas as pd
from src.pipeline import ROOT, sha256
from src.ingestion.snapshot import iter_snapshot
from src.corpus import canonical_doi, canonical_arxiv
from src.ann import CosineHNSW, recall_checks
from src.search import SearchEngine
from src.evaluation import validate_benchmark, retrieval_metrics


def check(directory):
    engine=SearchEngine.from_run(directory)
    directory,manifest,papers,embeddings=engine.directory,engine.manifest,engine.papers,engine.embeddings
    if manifest.get('kind')!='tier_s' or not all(manifest.get('gates',{}).values()):raise ValueError('Tier S gates were not satisfied')
    for name,expected in manifest['artifacts'].items():
        if sha256(directory/name)!=expected:raise ValueError(f'Tier S checksum failed: {name}')
    source=Path(manifest['source_snapshot'])
    if sha256(source/'manifest.json')!=manifest['source_manifest_sha256']:raise ValueError('Source manifest changed')
    if sha256(ROOT/manifest['config']['seed_metadata'])!=manifest['seed_metadata_sha256']:raise ValueError('Seed metadata changed')
    raw_count=sum(1 for _ in iter_snapshot(source))
    coverage=json.loads((directory/'coverage.json').read_text())
    if raw_count!=coverage['raw_records'] or len(papers)!=manifest['config']['target_papers']:raise ValueError('Coverage count mismatch')
    aliases=pd.read_parquet(directory/'identity_aliases.parquet')
    if aliases.source_id.duplicated().any():raise ValueError('Ambiguous identity aliases')
    for field,canonicalizer in [('doi',canonical_doi),('arxiv_id',canonical_arxiv)]:
        values=papers[field].map(canonicalizer).dropna()
        if values.duplicated().any():raise ValueError(f'Duplicate canonical {field}')
    benchmark=json.loads((directory/'benchmark_effective.json').read_text())
    validate_benchmark(benchmark,set(papers.paper_id))
    config=manifest['config']['ann']
    sample_rows=np.linspace(0,len(papers)-1,8,dtype=int)
    fresh=np.stack([engine.encode(papers.text_for_embedding.iloc[i]) for i in sample_rows])
    sample_cosines=np.sum(fresh*embeddings[sample_rows],axis=1)/(np.linalg.norm(fresh,axis=1)*np.linalg.norm(embeddings[sample_rows],axis=1))
    if float(sample_cosines.min())<.99999:raise ValueError('Cold embedding sample does not match pinned model')
    original=json.loads((directory/'ann_checks.json').read_text())
    probes=original['probe_rows'];queries=np.load(directory/'benchmark_query_vectors.npy',allow_pickle=False)
    fresh_queries=np.stack([engine.encode(q['query']) for q in benchmark['queries']])
    if not np.allclose(fresh_queries,queries,atol=1e-5):raise ValueError('Benchmark vectors do not match pinned model')
    repeated={'document_probes':recall_checks(engine.ann,embeddings,embeddings[probes],excluded_ids=probes,ef_values=[config['ef_search']]),
        'benchmark_queries':recall_checks(engine.ann,embeddings,queries,ef_values=[config['ef_search']])}
    if not all(rows[0]['recall_at_10']>=config['recall_target'] for rows in repeated.values()):raise ValueError('Repeated ANN recall failed')
    # Rebuild the complete deterministic index, rather than trusting dimension checks alone.
    rebuilt=CosineHNSW(np.load(directory/'paper_embeddings.npy',allow_pickle=False),**{k:config[k] for k in ['m','ef_construction','ef_search']},seed=manifest['config']['seed'])
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'index.faiss';rebuilt.save(path)
        if sha256(path)!=manifest['artifacts']['search_hnsw.faiss']:raise ValueError('ANN reconstruction mismatch')
    # Compare exact and ANN retrieval on identical corpus, query vectors and judgments.
    by_query={q['query']:vector for q,vector in zip(benchmark['queries'],queries)}
    class CachedEncoder:
        def encode(self,texts,**kwargs):return np.stack([by_query[t] for t in texts])
    engine.encoder=CachedEncoder();index=engine.ann;paired=[]
    for query in benchmark['queries']:
        qrels={j['paper_id']:j['grade'] for j in query['judgments']}
        row={'query_id':query['query_id']}
        for mode in ['dense','hybrid']:
            engine.ann=index;approx=engine.search(query['query'],mode=mode,top_k=20,explain=False)
            engine.ann=None;exact=engine.search(query['query'],mode=mode,top_k=20,explain=False)
            for metric in ['ndcg_at_10','recall_at_20']:
                row[mode+'_'+metric+'_ann_minus_exact']=retrieval_metrics(approx.paper_id.tolist(),qrels)[metric]-retrieval_metrics(exact.paper_id.tolist(),qrels)[metric]
        paired.append(row)
    # A restrictive filter must use eligible exact candidates and preserve prefix ordering.
    engine.ann=index;query=benchmark['queries'][0]['query'];year=int(papers.year.max())
    approximate=engine.search(query,mode='dense',top_k=20,year_min=year,year_max=year,explain=False)
    engine.ann=None;exact=engine.search(query,mode='dense',top_k=20,year_min=year,year_max=year,explain=False)
    if approximate.paper_id.tolist()!=exact.paper_id.tolist() or not approximate.year.eq(year).all():raise ValueError('Filtered ANN fallback changed results')
    comparison=pd.DataFrame(paired)
    return {'passed':True,'papers':len(papers),'raw_records':raw_count,'artifact_count':len(manifest['artifacts']),
        'cold_embedding_sample_min_cosine':float(sample_cosines.min()),'cold_embedding_sample_count':len(sample_rows),'index_reconstruction_identical':True,'filtered_dense_matches_exact':True,'ann_recall':repeated,
        'ann_minus_exact_mean':{key:float(comparison[key].mean()) for key in comparison if key!='query_id'},
        'scope':'Complete artifact and raw-page checksums, identity checks, deterministic index rebuild, 200 document probes and 50 benchmark vectors. No source recollection or full re-embedding.'}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--artifacts',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=check(args.artifacts);args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
