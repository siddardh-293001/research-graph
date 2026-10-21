"""Build an allowlisted, read-only serving release from a verified Tier S run."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from huggingface_hub import hf_hub_download
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
from src.artifacts import latest_tier_s_run
from src.search import SearchEngine
from src.public_engine import digest


def prepare(run=None, output=None):
    output = Path(output or ROOT/'build/release')
    if output.exists():
        raise ValueError('Use a new output directory; releases are immutable')
    engine = SearchEngine.from_run(run or latest_tier_s_run())
    if engine.manifest.get('kind') != 'tier_s':
        raise ValueError('Public release requires Tier S')
    for name, expected in engine.manifest['artifacts'].items():
        if digest(engine.directory/name) != expected:
            raise ValueError(f'Input checksum failed: {name}')
    output.mkdir(parents=True)
    p = engine.papers
    np.save(output/'ids.npy', engine.ids, allow_pickle=False)
    np.save(output/'years.npy', p.year.to_numpy(dtype=np.int32), allow_pickle=False)
    np.save(output/'topics.npy', p.topic_id.to_numpy(dtype=np.int32), allow_pickle=False)
    shutil.copyfile(engine.directory/'paper_embeddings.npy', output/'vectors.npy')
    shutil.copyfile(engine.directory/'search_hnsw.faiss', output/'index.faiss')
    db = sqlite3.connect(output/'corpus.sqlite')
    db.execute('CREATE TABLE papers (row_id INTEGER PRIMARY KEY, paper_id TEXT UNIQUE NOT NULL, title TEXT, abstract TEXT, year INTEGER, citation_count INTEGER, topic_id INTEGER, topic_name TEXT, community INTEGER, doi TEXT)')
    for i, row in p.iterrows():
        doi = row.get('doi')
        db.execute('INSERT INTO papers VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (i, row.paper_id, row.title, row.abstract, int(row.year), int(row.citation_count), int(row.topic_id), str(row.topic_name), int(row.community), doi if isinstance(doi, str) else None))
    db.execute('CREATE TABLE neighbors (source INTEGER, target INTEGER, weight REAL, PRIMARY KEY(source,target)) WITHOUT ROWID')
    db.executemany('INSERT INTO neighbors VALUES (?,?,?)', [(i,j,float(d['weight'])) for i,j,d in engine.graph.edges(data=True)]+[(j,i,float(d['weight'])) for i,j,d in engine.graph.edges(data=True)])
    db.commit(); db.close()
    vocabulary, rows, counts = {}, [], []
    for word, postings in sorted(engine.lexical.postings.items()):
        start = len(rows); rows.extend(postings[:,0].astype(int)); counts.extend(postings[:,1].astype(int))
        vocabulary[word] = [start, len(rows)]
    np.savez_compressed(output/'lexical.npz', lengths=engine.lexical.lengths,
                        rows=np.array(rows,dtype=np.int32), tf=np.array(counts,dtype=np.int32))
    (output/'vocabulary.json').write_text(json.dumps(vocabulary))
    (output/'stopwords.json').write_text(json.dumps(sorted(ENGLISH_STOP_WORDS)))
    embedding = engine.embedding_config
    for source, target in [('onnx/model.onnx','model.onnx'),('tokenizer.json','tokenizer.json'),('README.md','MODEL_CARD.md')]:
        cached = hf_hub_download(embedding['model'], source, revision=embedding['revision'], local_dir=ROOT/'build/model_source')
        shutil.copyfile(cached, output/target)
    # No raw snapshots, environment files, tokens or private cache directories leave this allowlist.
    manifest = {'schema_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
                'run_id': engine.manifest['run_id'], 'source_manifest_sha256': digest(engine.directory/'manifest.json'),
                'papers': len(p), 'source_finished_at': engine.manifest['finished_at'],
                'search': {k:engine.config[k] for k in ['bm25','rrf_k','candidate_depth']},
                'ann': engine.manifest['config']['ann'],
                'embedding': {k:embedding[k] for k in ['model','revision','normalize']},
                'topics': [{'topic_id': int(k), 'name': str(v.topic_name.iloc[0]), 'papers': len(v)} for k,v in p.groupby('topic_id')],
                'year_min': int(p.year.min()), 'year_max': int(p.year.max()),
                'limitations': ['Selective OpenAlex snapshot; not a random sample.', 'Independent relevance review pending.', 'Frozen snapshot: no live updates in Section 6.'],
                'artifacts': {f.name: digest(f) for f in output.iterdir() if f.is_file()}}
    # Source config contains local paths; expose no filesystem paths through the API.
    (output/'release.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(f'Release: {output}; papers: {len(p)}', flush=True)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path); parser.add_argument('--output', type=Path)
    args = parser.parse_args(); prepare(args.artifacts, args.output)
