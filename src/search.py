"""Shared BM25, dense and reciprocal rank fusion search for CLI, UI and evaluation."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
import yaml
from src.artifacts import load_run
from src.pipeline import ROOT


def tokenize(text):
    return [t for t in re.findall(r'(?u)\b\w+\b', str(text).casefold())
            if t not in ENGLISH_STOP_WORDS]


class BM25:
    """BM25 with positive log1p IDF and unique query terms."""
    def __init__(self, documents, k1=1.5, b=.75):
        if k1 <= 0 or not 0 <= b <= 1:
            raise ValueError('Invalid BM25 parameters')
        counts = [Counter(tokenize(d)) for d in documents]
        self.lengths = np.array([sum(c.values()) for c in counts], dtype=float)
        self.average = max(float(self.lengths.mean()), 1.)
        self.k1, self.b = k1, b
        self.postings = defaultdict(list)
        for i, terms in enumerate(counts):
            for term, frequency in terms.items():
                self.postings[term].append((i, frequency))
        self.postings = {term: np.array(rows, dtype=float) for term, rows in self.postings.items()}

    def score(self, query):
        scores = np.zeros(len(self.lengths))
        for term in sorted(set(tokenize(query))):
            posting = self.postings.get(term)
            if posting is None:
                continue
            ids, tf = posting[:, 0].astype(int), posting[:, 1]
            idf = np.log1p((len(scores) - len(ids) + .5) / (len(ids) + .5))
            norm = self.k1 * (1 - self.b + self.b * self.lengths[ids] / self.average)
            scores[ids] += idf * tf * (self.k1 + 1) / (tf + norm)
        return scores


def reciprocal_rank_fusion(rankings, k=60):
    if k <= 0:
        raise ValueError('RRF k must be positive')
    scores = defaultdict(float)
    for ranking in rankings:
        for rank, paper in enumerate(ranking, 1):
            scores[int(paper)] += 1 / (k + rank)
    return dict(scores)


def load_encoder(config, seed):
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(1)
    torch.manual_seed(seed)
    return SentenceTransformer(config['model'], revision=config['revision'],
        device=config['device'], local_files_only=config['local_files_only'])


class SearchEngine:
    def __init__(self, papers, embeddings, config, encoder=None):
        self.papers = papers.reset_index(drop=True).copy()
        self.embeddings = np.asarray(embeddings)
        if (self.embeddings.ndim != 2 or len(papers) != len(embeddings)
                or not np.isfinite(self.embeddings).all()
                or (np.linalg.norm(self.embeddings, axis=1) == 0).any()):
            raise ValueError('Invalid or misaligned embeddings')
        if papers.paper_id.isna().any() or papers.paper_id.duplicated().any():
            raise ValueError('Search paper IDs must be unique and present')
        self.embeddings = self.embeddings / np.linalg.norm(self.embeddings, axis=1, keepdims=True)
        self.config = config
        if config['rrf_k'] <= 0 or config['candidate_depth'] < 20:
            raise ValueError('Invalid fusion configuration')
        self.encoder = encoder
        self.lexical = BM25((self.papers.title + '. ' + self.papers.abstract).tolist(), **config['bm25'])
        self.ids = self.papers.paper_id.to_numpy(dtype=str)
        self.embedding_config = None
        self.seed = 42
        self.ann = None

    @classmethod
    def from_run(cls, path=None, encoder=None):
        directory, manifest, papers, embeddings, graph = load_run(path)
        config = yaml.safe_load((ROOT / 'config/search.yaml').read_text())
        engine = cls(papers, embeddings, config, encoder=encoder)
        engine.directory, engine.manifest, engine.graph = directory, manifest, graph
        engine.embedding_config = manifest['config']['embedding']
        engine.seed = manifest['config']['seed']
        if 'search_hnsw.faiss' in manifest.get('artifacts', {}):
            from src.ann import CosineHNSW
            engine.ann = CosineHNSW.load(directory/'search_hnsw.faiss',
                manifest['artifacts']['search_hnsw.faiss'], len(papers), embeddings.shape[1])
            engine.config['benchmark'] = str(directory/'benchmark_effective.json')
        return engine

    def encode(self, query):
        if self.encoder is None:
            if self.embedding_config is None:
                raise ValueError('Dense search requires an encoder')
            self.encoder = load_encoder(self.embedding_config, self.seed)
        vector = np.asarray(self.encoder.encode([query], normalize_embeddings=True, convert_to_numpy=True))[0]
        if (vector.shape != (self.embeddings.shape[1],) or not np.isfinite(vector).all()
                or np.linalg.norm(vector) == 0):
            raise ValueError('Invalid query embedding')
        return vector / np.linalg.norm(vector)

    def eligible(self, year_min=None, year_max=None, topic_ids=None):
        if year_min is not None and year_max is not None and year_min > year_max:
            raise ValueError('Minimum year exceeds maximum year')
        mask = np.ones(len(self.papers), dtype=bool)
        if year_min is not None:
            mask &= self.papers.year.ge(year_min).to_numpy()
        if year_max is not None:
            mask &= self.papers.year.le(year_max).to_numpy()
        if topic_ids is not None:
            mask &= self.papers.topic_id.isin(topic_ids).to_numpy()
        return np.flatnonzero(mask)

    def _order(self, candidates, scores):
        return candidates[np.lexsort((self.ids[candidates], -scores[candidates]))]

    def _dense_ranking(self, vector, candidates):
        if self.ann is not None and len(candidates)==len(self.papers):
            ids,values=self.ann.search(vector[None,:],self.config['candidate_depth'])
            scores=np.full(len(self.papers),np.nan)
            scores[ids[0]]=values[0]
            return self._order(ids[0],scores),scores
        # Filtered queries use an exact eligible-subset fallback. This preserves
        # prefilter correctness rather than silently losing eligible ANN results.
        scores=np.full(len(self.papers),np.nan)
        scores[candidates]=self.embeddings[candidates]@vector
        return self._order(candidates,scores),scores

    def search(self, query, mode='hybrid', top_k=10, year_min=None, year_max=None,
               topic_ids=None, query_vector=None, explain=True):
        if mode not in {'bm25', 'dense', 'hybrid'}:
            raise ValueError('Unknown retrieval mode')
        if not isinstance(query, str) or len(query) > self.config['max_query_chars']:
            raise ValueError('Invalid query or query too long')
        if not isinstance(top_k, int) or not 1 <= top_k <= self.config['max_results']:
            raise ValueError('Invalid result limit')
        candidates = self.eligible(year_min, year_max, topic_ids)
        lexical_scores = np.zeros(len(self.papers))
        dense_scores = np.full(len(self.papers), np.nan)
        lexical_order = dense_order = np.array([], dtype=int)
        if query.strip() and len(candidates):
            if mode != 'dense':
                lexical_scores = self.lexical.score(query)
                lexical_order = self._order(candidates[lexical_scores[candidates] > 0], lexical_scores)
            if mode != 'bm25':
                vector = self.encode(query) if query_vector is None else np.asarray(query_vector)
                if (vector.shape != (self.embeddings.shape[1],) or not np.isfinite(vector).all()
                        or np.linalg.norm(vector) == 0):
                    raise ValueError('Invalid query vector')
                dense_order,dense_scores = self._dense_ranking(vector / np.linalg.norm(vector),candidates)
        if mode == 'bm25':
            order, scores = lexical_order, lexical_scores
        elif mode == 'dense':
            order, scores = dense_order, dense_scores
        else:
            depth = self.config['candidate_depth']
            fused = reciprocal_rank_fusion([lexical_order[:depth], dense_order[:depth]], self.config['rrf_k'])
            scores = np.zeros(len(self.papers))
            for i, score in fused.items():
                scores[i] = score
            order = self._order(np.array(list(fused), dtype=int), scores)
        result = self.papers.iloc[order[:top_k]].copy()
        result['score'] = scores[order[:top_k]]
        result['similarity'] = dense_scores[order[:top_k]]
        result['bm25_score'] = lexical_scores[order[:top_k]]
        lexical_ranks = {int(i): rank for rank, i in enumerate(lexical_order, 1)}
        dense_ranks = {int(i): rank for rank, i in enumerate(dense_order, 1)}
        result['bm25_rank'] = [lexical_ranks.get(int(i)) for i in order[:top_k]]
        result['dense_rank'] = [dense_ranks.get(int(i)) for i in order[:top_k]]
        if explain:
            terms = set(tokenize(query))
            result['shared_terms'] = [sorted(terms & set(tokenize(f'{r.title} {r.abstract}')))
                                      for r in result.itertuples()]
            result['matching_sentence'] = [self.matching_sentence(r.abstract, terms) for r in result.itertuples()]
        return result.reset_index(drop=True)

    @staticmethod
    def matching_sentence(abstract, terms):
        sentences = re.split(r'(?<=[.!?])\s+', str(abstract))
        scored = [(len(set(tokenize(s)) & terms), -i, s) for i, s in enumerate(sentences)]
        best = max(scored)
        return best[2][:350] if best[0] else ''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('query')
    parser.add_argument('--artifacts', type=Path)
    parser.add_argument('--mode', choices=['bm25', 'dense', 'hybrid'], default='hybrid')
    parser.add_argument('--top-k', type=int, default=10)
    parser.add_argument('--year-min', type=int)
    parser.add_argument('--year-max', type=int)
    parser.add_argument('--topic', type=int, action='append')
    args = parser.parse_args()
    engine = SearchEngine.from_run(args.artifacts)
    results = engine.search(args.query, args.mode, args.top_k, args.year_min, args.year_max, args.topic)
    print(results[['paper_id', 'title', 'year', 'topic_name', 'score']].to_json(orient='records', indent=2))


if __name__ == '__main__':
    main()
