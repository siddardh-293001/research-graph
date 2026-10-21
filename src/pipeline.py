"""Rebuild the local baseline: python -m src.pipeline."""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import random
import uuid

import numpy as np
import pandas as pd
import yaml
from sklearn.metrics import adjusted_mutual_info_score, adjusted_rand_score, normalized_mutual_info_score
from src.audit import audit_frames
from src.preprocessing import clean_metadata, prepare_embedding_corpus
from src.baseline_methods import fit_topics, build_graph, integrate_analysis

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def encode_papers(papers, config, seed):
    import torch
    from sentence_transformers import SentenceTransformer
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    model = SentenceTransformer(config['model'], revision=config['revision'],
        device=config['device'], local_files_only=config['local_files_only'])
    return model.encode(papers.text_for_embedding.tolist(), batch_size=config['batch_size'],
        normalize_embeddings=config['normalize'], show_progress_bar=True, convert_to_numpy=True)


def compare_legacy(papers, embeddings, nodes, edges, analysis, legacy):
    """Read-only comparison; partition metrics tolerate community renumbering."""
    old = pd.read_parquet(legacy / 'embedded_papers.parquet')
    ids_match = np.array_equal(old.paper_id.to_numpy(), papers.paper_id.to_numpy())
    result = {'paper_ids_and_order_match': bool(ids_match)}
    if not ids_match:
        return result
    previous = np.load(legacy / 'paper_embeddings.npy', allow_pickle=False)
    if previous.shape == embeddings.shape:
        result['embedding_max_absolute_difference'] = float(np.max(np.abs(previous - embeddings)))
        result['embedding_mean_paired_cosine'] = float(np.mean(np.sum(previous * embeddings, axis=1) /
            (np.linalg.norm(previous, axis=1) * np.linalg.norm(embeddings, axis=1))))
    old_analysis = pd.read_parquet(legacy / 'research_analysis_dataset.parquet')
    aligned = analysis.merge(old_analysis, on='paper_id', suffixes=('_new', '_old'), validate='one_to_one')
    result['topic_ami'] = float(adjusted_mutual_info_score(aligned.topic_id_old, aligned.topic_id_new))
    result['community_ami'] = float(adjusted_mutual_info_score(aligned.community_old, aligned.community_new))
    result['new_edges'] = len(edges)
    result['legacy_reported_edges'] = 11064
    result['legacy_reported_edges_source'] = 'project profile exploratory baseline'
    return result


def run(config_path, output_root=None, encoder=None, compare=True):
    config_path = Path(config_path).resolve()
    config = yaml.safe_load(config_path.read_text())
    source = ROOT / config['source']
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    output = Path(output_root or ROOT / config['output_root']).resolve() / run_id
    output.mkdir(parents=True, exist_ok=False)
    manifest = {'run_id': run_id, 'status': 'running', 'started_at': datetime.now(timezone.utc).isoformat(),
        'config': config, 'source': {'path': str(source),
        'kind': config['source_kind']}, 'python': platform.python_version(),
        'packages': {name: version(name) for name in ['numpy', 'pandas', 'pyarrow', 'scikit-learn',
            'networkx', 'python-louvain', 'torch', 'sentence-transformers', 'PyYAML',
            'scipy', 'transformers', 'tokenizers', 'huggingface-hub', 'safetensors']},
        'code_sha256': {str(p.relative_to(ROOT)): sha256(p) for p in sorted((ROOT / 'src').rglob('*.py'))}}
    manifest_path = output / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    try:
        manifest['source']['sha256'] = sha256(source)
        provenance = source.with_name('provenance.json')
        if provenance.exists():
            manifest['source']['recovery_provenance'] = json.loads(provenance.read_text())
            manifest['source']['provenance_sha256'] = sha256(provenance)
            if manifest['source']['recovery_provenance']['output_sha256'] != manifest['source']['sha256']:
                raise ValueError('Recovered input does not match its provenance hash')
        print(f'Run {run_id}: cleaning metadata', flush=True)
        source_frame = pd.read_parquet(source)
        clean = clean_metadata(source_frame)
        papers = prepare_embedding_corpus(clean)
        print(f'{len(source_frame)} input -> {len(clean)} cleaned -> {len(papers)} with abstracts', flush=True)
        if len(papers) > config['graph']['max_papers']:
            raise ValueError('Baseline size guard exceeded before embedding')
        embeddings = (encoder or encode_papers)(papers, config['embedding'], config['seed'])
        ids = papers.paper_id.to_numpy(dtype=str)
        validation = audit_frames(papers, embeddings, ids, papers)
        if not validation['passed']:
            raise ValueError(validation['errors'])
        print('Fitting topics and building baseline graph', flush=True)
        topics, vectorizer, nmf, terms = fit_topics(papers, config['topics'], config['seed'])
        nodes, edges = build_graph(papers, embeddings, config['graph'], config['seed'])
        analysis = integrate_analysis(papers, topics, nodes)
        audit = audit_frames(papers, embeddings, ids, analysis)
        if not audit['passed']:
            raise ValueError(audit['errors'])
        tables = {'papers_clean': clean, 'embedded_papers': papers, 'nlp_topic_assignments': topics,
                  'graph_nodes': nodes, 'graph_edges': edges, 'research_analysis_dataset': analysis}
        for name, table in tables.items():
            table.to_parquet(output / f'{name}.parquet', index=False)
        np.save(output / 'paper_embeddings.npy', embeddings, allow_pickle=False)
        np.save(output / 'embedded_paper_ids_safe.npy', ids, allow_pickle=False)
        # Save numerical model state and vocabulary without pickle.
        np.savez_compressed(output / 'topic_model.npz', components=nmf.components_, idf=vectorizer.idf_)
        (output / 'topic_vocabulary.json').write_text(json.dumps(vectorizer.vocabulary_, default=int))
        (output / 'topic_terms.json').write_text(json.dumps(terms, indent=2) + '\n')
        (output / 'audit.json').write_text(json.dumps(audit, indent=2) + '\n')
        metrics = {'papers': len(papers), 'cleaned_papers': len(clean),
            'excluded_without_abstract': len(clean) - len(papers), 'edges': len(edges),
            'communities': int(nodes.community.nunique()), 'topics': int(topics.topic_id.nunique()),
            'topic_community_ari': float(adjusted_rand_score(analysis.topic_id, analysis.community)),
            'topic_community_nmi': float(normalized_mutual_info_score(analysis.topic_id, analysis.community))}
        if compare:
            metrics['legacy_comparison'] = compare_legacy(papers, embeddings, nodes, edges, analysis, ROOT / 'data/processed')
        (output / 'metrics.json').write_text(json.dumps(metrics, indent=2) + '\n')
        manifest.update(status='complete', finished_at=datetime.now(timezone.utc).isoformat(),
            counts=metrics, artifacts={p.name: sha256(p) for p in sorted(output.iterdir()) if p != manifest_path})
    except Exception as exc:
        manifest.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Completed: {output}', flush=True)
    print(json.dumps(metrics, indent=2), flush=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/baseline.yaml')
    parser.add_argument('--output-root', type=Path)
    args = parser.parse_args()
    run(args.config, args.output_root)


if __name__ == '__main__':
    main()
