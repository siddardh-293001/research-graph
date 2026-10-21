"""Load and validate completed baseline runs without deserializing pickle."""
import json
from pathlib import Path
import networkx as nx
import numpy as np
import pandas as pd
from src.audit import audit_frames
from src.pipeline import ROOT, sha256

REQUIRED = ('embedded_papers.parquet', 'paper_embeddings.npy', 'embedded_paper_ids_safe.npy',
            'research_analysis_dataset.parquet', 'graph_nodes.parquet', 'graph_edges.parquet')


def resolve_run(path=None):
    if path is not None:
        directory = Path(path).resolve()
    else:
        candidates = []
        for p in (ROOT / 'data/runs').glob('*/manifest.json'):
            manifest = json.loads(p.read_text())
            if manifest.get('status') == 'complete':
                candidates.append((manifest.get('finished_at', ''), str(p.parent)))
        if not candidates:
            raise ValueError('No completed baseline run. Run python -m src.pipeline first.')
        directory = Path(max(candidates)[1])
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest.get('status') != 'complete':
        raise ValueError('Only completed runs can be served')
    for name in REQUIRED:
        expected = manifest.get('artifacts', {}).get(name)
        if expected is None or sha256(directory / name) != expected:
            raise ValueError(f'Artifact integrity check failed: {name}')
    return directory, manifest


def load_run(path=None):
    directory, manifest = resolve_run(path)
    papers = pd.read_parquet(directory / 'embedded_papers.parquet')
    embeddings = np.load(directory / 'paper_embeddings.npy', allow_pickle=False)
    ids = np.load(directory / 'embedded_paper_ids_safe.npy', allow_pickle=False)
    analysis = pd.read_parquet(directory / 'research_analysis_dataset.parquet')
    audit = audit_frames(papers, embeddings, ids, analysis)
    if not audit['passed']:
        raise ValueError(f'Invalid run: {audit["errors"]}')
    nodes = pd.read_parquet(directory / 'graph_nodes.parquet')
    edges = pd.read_parquet(directory / 'graph_edges.parquet')
    if (not np.array_equal(nodes.paper_id.to_numpy(), papers.paper_id.to_numpy())
            or not np.array_equal(nodes.node.to_numpy(), np.arange(len(papers)))):
        raise ValueError('Graph node IDs are not aligned to paper rows')
    index = {p: i for i, p in enumerate(papers.paper_id)}
    if not set(edges.source).union(edges.target).issubset(index):
        raise ValueError('Graph contains unknown paper IDs')
    if (not np.isfinite(edges.weight.to_numpy()).all() or edges.weight.le(0).any()
            or edges.source.eq(edges.target).any()):
        raise ValueError('Invalid graph edge weights or self edges')
    graph = nx.Graph()
    graph.add_nodes_from((i, row.to_dict()) for i, row in nodes.iterrows())
    graph.add_weighted_edges_from((index[e.source], index[e.target], e.weight)
                                  for e in edges.itertuples())
    metadata_columns = ['paper_id'] + [c for c in papers if c not in analysis]
    merged = analysis.merge(papers[metadata_columns], on='paper_id', how='left', validate='one_to_one')
    merged['_graph_node'] = np.arange(len(merged))
    return directory, manifest, merged, embeddings, graph


def latest_tier_s_run():
    """Return the newest completed Tier S run whose measured build gates passed."""
    candidates=[]
    for path in (ROOT/'data/tier_s_runs').glob('*/manifest.json'):
        manifest=json.loads(path.read_text())
        gates=manifest.get('gates',{})
        if (manifest.get('status')=='complete' and manifest.get('kind')=='tier_s'
                and all(gates.get(key) is True for key in ['target_size','ann_recall','aligned_artifacts'])):
            candidates.append((manifest.get('finished_at',''),str(path.parent)))
    return Path(max(candidates)[1]) if candidates else None
