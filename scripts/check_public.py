"""Independent serving equivalence and memory check against the full Tier S engine."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import resource
import subprocess
import sys
from time import perf_counter
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def parity(directory):
    import numpy as np
    from src.artifacts import latest_tier_s_run
    from src.search import SearchEngine
    from src.evaluation import retrieval_metrics
    from src.public_engine import PublicEngine
    original = SearchEngine.from_run(latest_tier_s_run())
    lean = PublicEngine(directory)
    if lean.manifest['source_manifest_sha256'] != __import__('src.public_engine',fromlist=['digest']).digest(original.directory/'manifest.json'):
        raise ValueError('Release does not match the current Tier S run')
    benchmark = json.loads((original.directory/'benchmark_effective.json').read_text())
    source_vectors = np.load(original.directory/'benchmark_query_vectors.npy', allow_pickle=False)
    metrics = {m: [] for m in ['bm25','dense','hybrid']}; cosines=[]; overlap=[]
    lexical_identical = True
    for i, query in enumerate(benchmark['queries']):
        vector = lean.encode(query['query'])
        cosines.append(float(vector@source_vectors[i]/np.linalg.norm(source_vectors[i])))
        for mode in metrics:
            full = original.search(query['query'],mode=mode,top_k=20,query_vector=source_vectors[i],explain=False)
            small, _ = lean.search(query['query'],mode=mode,top_k=20)
            ids = [p['paper_id'] for p in small]
            if mode == 'bm25':
                lexical_identical &= ids == full.paper_id.tolist()
                if len(small) and not np.allclose([p['bm25_score'] for p in small],full.bm25_score,rtol=1e-12):
                    raise ValueError('BM25 score changed')
            qrels={j['paper_id']:j['grade'] for j in query['judgments']}
            baseline=retrieval_metrics(full.paper_id.tolist(),qrels)
            measured=retrieval_metrics(ids,qrels)
            metrics[mode].append({k: measured[k]-baseline[k] for k in ['ndcg_at_10','recall_at_20']})
            if mode == 'dense':
                overlap.append(len(set(ids)&set(full.paper_id))/20)
    if not lexical_identical or min(cosines)<.99999:
        raise ValueError('Serving representation failed baseline parity gate')
    differences={mode:{k:float(np.mean([r[k] for r in rows])) for k in rows[0]} for mode,rows in metrics.items()}
    if any(abs(value)>.005 for mode in differences.values() for value in mode.values()):
        raise ValueError('Public serving relevance changed by more than 0.005')
    query=benchmark['queries'][0]['query']
    # Eligibility and top-k prefix stability are checked against the original engine.
    for mode in metrics:
        full=original.search(query,mode=mode,top_k=20,year_min=2025,year_max=2026,topic_ids=[1],query_vector=lean.encode(query),explain=False)
        small,_=lean.search(query,mode=mode,top_k=20,year_min=2025,year_max=2026,topic_ids=[1])
        if [p['paper_id'] for p in small]!=full.paper_id.tolist():
            raise ValueError('Filtered serving results changed')
    return {'passed':True,'queries':50,'bm25_rankings_identical':bool(lexical_identical),
            'onnx_query_min_cosine':min(cosines),'dense_top20_mean_overlap':float(np.mean(overlap)),
            'mean_metric_difference':differences,'filtered_rankings_match':True}


def memory(directory):
    from src.public_engine import PublicEngine
    engine=PublicEngine(directory)
    for text in ['graph retrieval for multi hop reasoning','word '*2000]:
        for mode in ['bm25','dense','hybrid']:
            engine.search(text,mode,50)
            engine.search(text,mode,50,year_min=2020,year_max=2025)
    # Retain all 64 cached result sets with the public result ceiling.
    for i in range(65):engine.search('retrieval language models '+str(i),'bm25',50)
    peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024**2 if sys.platform=='darwin' else 1024)
    if peak > 460:raise ValueError(f'Free-hosting memory headroom gate failed: {peak:.1f} MiB')
    print(json.dumps({'passed':True,'peak_rss_mib':peak,'gate_mib':460,'platform':sys.platform,
                      'scope':'Separate serving process: long queries, filtered exact search and full 64-entry result cache. Host OS, not a Linux container memory limit.'}))


def http(base_url):
    import numpy as np
    def get(path):
        with urllib.request.urlopen(base_url.rstrip('/')+path,timeout=90) as response:return json.load(response)
    status=get('/api/status')
    if status['papers']!=20000:raise ValueError('Unexpected live corpus')
    def search(mode):
        payload=json.dumps({'query':'graph retrieval for multi hop reasoning','mode':mode,'top_k':10}).encode()
        request=urllib.request.Request(base_url.rstrip('/')+'/api/search',data=payload,headers={'Content-Type':'application/json'})
        start=perf_counter()
        with urllib.request.urlopen(request,timeout=90) as response:result=json.load(response)
        if not result['results']:raise ValueError('Live search returned no results')
        return (perf_counter()-start)*1000,result
    # Warm, then issue concurrent real HTTP requests; rate remains below demo limit.
    search('hybrid')
    latencies=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        for ms,result in pool.map(search,['bm25','dense','hybrid']*3):latencies.append(ms)
    _,result=search('hybrid');paper=result['results'][0]['paper_id']
    from urllib.parse import quote
    if get('/api/paper?paper_id='+quote(paper,safe=''))['paper_id']!=paper:raise ValueError('Paper identity mismatch')
    graph=get('/api/graph?paper_id='+quote(paper,safe='')+'&limit=12')
    if len(graph['nodes'])>13 or len(graph['edges'])>12:raise ValueError('Graph exceeds bound')
    with urllib.request.urlopen(base_url,timeout=90) as response:
        if b'/assets/' not in response.read():raise ValueError('Public React assets not served')
    return {'passed':True,'url':base_url,'papers':status['papers'],'run_id':status['run_id'],
            'http_requests':len(latencies),'concurrency':3,'warm_p50_ms':float(np.quantile(latencies,.5)),
            'warm_p95_ms':float(np.quantile(latencies,.95)),
            'scope':'Repeated warm three-query workload, including cache hits; not an uncached load benchmark.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',type=Path,default=ROOT/'build/release');parser.add_argument('--output',type=Path)
    parser.add_argument('--memory-only',action='store_true');parser.add_argument('--base-url')
    args=parser.parse_args()
    if args.memory_only:memory(args.release)
    else:
        result=parity(args.release)
        from scripts.restore_release import restore,digest
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            restored=restore(ROOT/'deploy/release-parts',Path(temp)/'release')
            if digest(restored/'release.json')!=digest(args.release/'release.json'):
                raise ValueError('Published release parts do not match the served release')
        result['publication_parts_round_trip']=True
        separate=subprocess.run([sys.executable,__file__,'--release',str(args.release),'--memory-only'],capture_output=True,text=True,check=True)
        result['serving_memory']=json.loads(separate.stdout.strip().splitlines()[-1])
        if args.base_url:result['http']=http(args.base_url)
        if args.output:args.output.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))
