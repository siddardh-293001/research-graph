"""Fixed-query retrieval evaluation with bootstrap intervals and review pools."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from time import perf_counter
import uuid
import numpy as np
import pandas as pd
from src.pipeline import ROOT, sha256
from src.search import SearchEngine


def validate_benchmark(benchmark, known_ids, expected_queries=50):
    queries = benchmark['queries']
    if len(queries) != expected_queries:
        raise ValueError(f'Expected {expected_queries} benchmark queries')
    query_ids, query_text = set(), set()
    for query in queries:
        if query['query_id'] in query_ids or not query['query'].strip() or query['query'] in query_text:
            raise ValueError('Duplicate query or missing query text')
        query_ids.add(query['query_id'])
        query_text.add(query['query'])
        ids, positive = set(), False
        for j in query['judgments']:
            if j['paper_id'] not in known_ids or j['paper_id'] in ids:
                raise ValueError('Unknown or duplicate judgment paper ID')
            if type(j['grade']) is not int or not 0 <= j['grade'] <= 3:
                raise ValueError('Relevance grade must be an integer in 0..3')
            ids.add(j['paper_id'])
            positive |= j['grade'] > 0
        if not positive:
            raise ValueError('Every query requires at least one known positive')
    return queries


def retrieval_metrics(ranking, qrels):
    if len(ranking) != len(set(ranking)):
        raise ValueError('Rankings must not contain duplicate IDs')
    gains = np.array([2 ** qrels.get(p, 0) - 1 for p in ranking[:10]], dtype=float)
    dcg = float(np.sum(gains / np.log2(np.arange(len(gains)) + 2)))
    ideal = np.array(sorted([2**g - 1 for g in qrels.values()], reverse=True)[:10], dtype=float)
    idcg = float(np.sum(ideal / np.log2(np.arange(len(ideal)) + 2)))
    positive = {p for p, g in qrels.items() if g > 0}
    if not positive:
        raise ValueError('Metrics require at least one judged relevant paper')
    rr = next((1 / rank for rank, p in enumerate(ranking, 1) if p in positive), 0.)
    return {'ndcg_at_10': dcg / idcg if idcg else 0., 'reciprocal_rank': rr,
            'recall_at_20': len(set(ranking[:20]) & positive) / len(positive),
            'judged_fraction_at_10': sum(p in qrels for p in ranking[:10]) / 10}


def bootstrap_mean(values, seed=42, samples=2000):
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all() or samples < 1:
        raise ValueError('Bootstrap requires finite observations and a positive sample count')
    rng = np.random.default_rng(seed)
    means = values[rng.integers(len(values), size=(samples, len(values)))].mean(axis=1)
    return {'mean': float(values.mean()), 'ci95': np.quantile(means, [.025, .975]).tolist()}


def evaluate(engine, benchmark_path=None, output_root=None):
    benchmark_path = Path(benchmark_path or ROOT / engine.config['benchmark'])
    benchmark = json.loads(benchmark_path.read_text())
    queries = validate_benchmark(benchmark, set(engine.ids))
    output = Path(output_root or ROOT / 'data/evaluation') / (
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    output.mkdir(parents=True, exist_ok=False)
    modes = ['bm25', 'dense', 'hybrid']
    t0 = perf_counter()
    engine.encode('warm up retrieval model')
    model_warmup_ms = (perf_counter() - t0) * 1000
    rows, rankings, pool = [], [], {}
    for query in queries:
        qrels = {j['paper_id']: j['grade'] for j in query['judgments']}
        for mode in modes:
            # Time the actual top-20 application path including inference,
            # filtering, ranking, materialization and snippet explanations.
            start = perf_counter()
            served = engine.search(query['query'], mode=mode, top_k=20)
            latency_ms = (perf_counter() - start) * 1000
            full = engine.search(query['query'], mode=mode, top_k=min(1000, len(engine.papers)), explain=False)
            ids = full.paper_id.tolist()
            if served.paper_id.tolist() != ids[:20]:
                raise ValueError('Ranking depends on requested result count')
            rows.append({'query_id': query['query_id'], 'mode': mode, 'latency_ms': latency_ms,
                         **retrieval_metrics(ids, qrels)})
            for rank, row in enumerate(full.itertuples(), 1):
                rankings.append({'query_id': query['query_id'], 'mode': mode,
                                 'rank': rank, 'paper_id': row.paper_id, 'score': row.score})
                if rank <= 10:
                    key = (query['query_id'], row.paper_id)
                    entry = pool.setdefault(key, {'query_id': query['query_id'], 'query': query['query'],
                        'paper_id': row.paper_id, 'title': row.title, 'abstract_excerpt': row.abstract[:1000],
                        'existing_grade': qrels.get(row.paper_id, ''), 'reviewed_grade': '',
                        'reviewer': '', 'notes': ''})
                    entry[f'{mode}_rank'] = rank
        print(f'Evaluated {query["query_id"]}', flush=True)
    frame = pd.DataFrame(rows)
    summary = {}
    for mode in modes:
        subset = frame[frame['mode'].eq(mode)]
        summary[mode] = {metric: bootstrap_mean(subset[metric], engine.config['seed'],
                            engine.config['bootstrap_samples'])
                        for metric in ['ndcg_at_10', 'reciprocal_rank', 'recall_at_20']}
        summary[mode]['judged_fraction_at_10'] = float(subset.judged_fraction_at_10.mean())
        summary[mode]['latency_ms'] = {'p50': float(subset.latency_ms.quantile(.5)),
                                     'p95': float(subset.latency_ms.quantile(.95)), 'observations': len(subset)}
    paired = {}
    for metric in ['ndcg_at_10', 'reciprocal_rank', 'recall_at_20']:
        pivot = frame.pivot(index='query_id', columns='mode', values=metric)
        paired[metric] = {f'hybrid_minus_{base}': bootstrap_mean(pivot.hybrid - pivot[base],
                           engine.config['seed'], engine.config['bootstrap_samples']) for base in ['bm25', 'dense']}
    report = {'benchmark_version': benchmark['version'], 'benchmark_status': benchmark['status'],
        'query_count': len(queries), 'judgment_count': sum(len(q['judgments']) for q in queries),
        'limitations': ['Assistant-authored metadata seed judgments; independent review pending.',
            'Judgments are incomplete: unjudged results receive zero gain for scoring, not a nonrelevance label.',
            'Recall@20 measures recovery of known positives, not all relevant papers in the corpus.',
            'Bootstrap intervals reflect query sampling only, not label uncertainty.',
            'MRR uses at most 1000 returned results; ANN dense returns 100 candidates and hybrid pools 100 per channel.',
            'Latency is warm single-process top-20 search including inference and explanations; not HTTP latency or a load test.'],
        'ranking_limit': min(1000, len(engine.papers)), 'dense_backend': 'hnsw' if engine.ann is not None else 'exact',
        'corpus_size': len(engine.papers), 'baseline_run': str(engine.directory),
        'baseline_manifest_sha256': sha256(engine.directory / 'manifest.json'),
        'benchmark_sha256': sha256(benchmark_path), 'config': engine.config,
        'model_warmup_ms': model_warmup_ms, 'results': summary, 'paired_differences': paired,
        'evaluation_code_sha256': {str(p.relative_to(ROOT)): sha256(p) for p in
            [ROOT/'src/search.py', ROOT/'src/evaluation.py', ROOT/'src/artifacts.py']}}
    frame.to_csv(output / 'per_query.csv', index=False)
    pd.DataFrame(rankings).to_parquet(output / 'rankings.parquet', index=False)
    pd.DataFrame(pool.values()).to_csv(output / 'review_pool.csv', index=False)
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'Evaluation saved: {output}', flush=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path)
    parser.add_argument('--benchmark', type=Path)
    parser.add_argument('--output-root', type=Path)
    args = parser.parse_args()
    evaluate(SearchEngine.from_run(args.artifacts), args.benchmark, args.output_root)


if __name__ == '__main__':
    main()
