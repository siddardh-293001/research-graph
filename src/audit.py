"""Offline corpus integrity gate: python -m src.audit."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.corpus import canonical_doi

ROOT = Path(__file__).resolve().parents[1]


def audit_frames(corpus, embeddings, embedding_ids, analysis):
    errors = []
    required = {'paper_id', 'title', 'abstract', 'year', 'citation_count'}
    missing = sorted(required - set(corpus.columns))
    if missing:
        return {'passed': False, 'errors': [f'Missing corpus columns: {missing}']}
    ids = corpus['paper_id']
    if ids.isna().any() or ids.astype(str).str.strip().eq('').any() or ids.duplicated().any():
        errors.append('Corpus paper IDs must be present and unique')
    if embeddings.ndim != 2 or embeddings.shape[0] != len(corpus):
        errors.append('Embedding matrix must have one row per corpus paper')
    if not np.isfinite(embeddings).all():
        errors.append('Embeddings contain non-finite values')
    if embeddings.ndim == 2 and (np.linalg.norm(embeddings, axis=1) == 0).any():
        errors.append('Embeddings contain zero vectors')
    if embedding_ids.ndim != 1 or not np.array_equal(ids.to_numpy(), embedding_ids):
        errors.append('Embedding IDs do not match corpus row order')
    if 'paper_id' not in analysis or not np.array_equal(ids.to_numpy(), analysis['paper_id'].to_numpy()):
        errors.append('Analysis IDs do not match corpus row order')
    for field in ('title', 'abstract'):
        text = corpus[field].map(lambda value: value if isinstance(value, str) else '')
        if text.str.strip().eq('').any():
            errors.append(f'Corpus contains missing or empty {field}')
    citations = pd.to_numeric(corpus['citation_count'], errors='coerce')
    if citations.isna().any() or not np.isfinite(citations).all() or (citations < 0).any():
        errors.append('Citation counts must be nonnegative numbers')
    years = pd.to_numeric(corpus['year'], errors='coerce')
    if years.isna().any() or not np.isfinite(years).all() or (years % 1 != 0).any():
        errors.append('Publication years must be finite integers')
    dois = corpus.get('doi', pd.Series(dtype=object)).map(canonical_doi).dropna()
    short_abstracts = int(corpus.abstract.map(lambda value: len(value.split())
                          if isinstance(value, str) else 0).lt(30).sum())
    warnings = []
    if dois.duplicated().any():
        warnings.append('Duplicate DOIs require review before next ingestion')
    if short_abstracts:
        warnings.append(f'{short_abstracts} abstracts have fewer than 30 words; review source text quality')
    return {
        'passed': not errors, 'errors': errors, 'paper_count': len(corpus),
        'embedding_shape': list(embeddings.shape),
        'duplicate_dois': int(dois.duplicated().sum()),
        'short_abstracts_under_30_words': short_abstracts,
        'warnings': warnings,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/project.yaml')
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    paths = {k: ROOT / v for k, v in config['paths'].items()}
    corpus = pd.read_parquet(paths['corpus'])
    report = audit_frames(corpus, np.load(paths['embeddings'], allow_pickle=False),
                          np.load(paths['embedding_ids'], allow_pickle=False),
                          pd.read_parquet(paths['analysis']))
    report.update(tier=config['tier'], configured_embedding_model=config['embedding_model'],
                  created_at=datetime.now(timezone.utc).isoformat())
    report['sha256'] = {}
    for key, path in paths.items():
        if key == 'audit':
            continue
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
        report['sha256'][key] = digest.hexdigest()
    paths['audit'].parent.mkdir(parents=True, exist_ok=True)
    paths['audit'].write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
