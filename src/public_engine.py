"""Memory-bounded serving of frozen releases; no torch/pandas/networkx imports."""
from collections import OrderedDict
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3

import faiss
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


class PublicEngine:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.manifest = json.loads((self.directory/'release.json').read_text())
        for name, expected in self.manifest['artifacts'].items():
            if Path(name).name != name or digest(self.directory/name) != expected:
                raise ValueError(f'Release checksum failed: {name}')
        self.config = self.manifest['search']
        self.ids = np.load(self.directory/'ids.npy', allow_pickle=False)
        self.years = np.load(self.directory/'years.npy', allow_pickle=False)
        self.topics = np.load(self.directory/'topics.npy', allow_pickle=False)
        self.vectors = np.load(self.directory/'vectors.npy', mmap_mode='r', allow_pickle=False)
        self.lexical = np.load(self.directory/'lexical.npz', allow_pickle=False)
        self.lengths = self.lexical['lengths']
        self.posting_rows, self.posting_tf = self.lexical['rows'], self.lexical['tf']
        self.vocabulary = json.loads((self.directory/'vocabulary.json').read_text())
        self.stopwords = set(json.loads((self.directory/'stopwords.json').read_text()))
        faiss.omp_set_num_threads(1)
        self.index = faiss.read_index(str(self.directory/'index.faiss'))
        self.index.hnsw.efSearch = self.manifest['ann']['ef_search']
        if self.index.ntotal != len(self.ids) or self.vectors.shape != (len(self.ids), self.index.d):
            raise ValueError('Release index alignment failed')
        self.tokenizer = Tokenizer.from_file(str(self.directory/'tokenizer.json'))
        self.tokenizer.enable_truncation(max_length=256)
        self.tokenizer.enable_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        self.model = ort.InferenceSession(str(self.directory/'model.onnx'), options,
                                          providers=['CPUExecutionProvider'])
        self.input_names = {i.name for i in self.model.get_inputs()}
        self.cache = OrderedDict()

    def connect(self):
        connection = sqlite3.connect((self.directory/'corpus.sqlite').as_uri()+'?mode=ro&immutable=1', uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA cache_size=-2048')
        return connection

    def tokenize(self, text):
        return [t for t in re.findall(r'(?u)\b\w+\b', text.casefold()) if t not in self.stopwords]

    def encode(self, text):
        encoded = self.tokenizer.encode(text)
        inputs = {'input_ids': np.array([encoded.ids], dtype=np.int64),
                  'attention_mask': np.array([encoded.attention_mask], dtype=np.int64),
                  'token_type_ids': np.array([encoded.type_ids], dtype=np.int64)}
        hidden = self.model.run(None, {k: v for k, v in inputs.items() if k in self.input_names})[0]
        mask = inputs['attention_mask'][..., None]
        vector = (hidden*mask).sum(axis=1)/np.maximum(mask.sum(axis=1), 1)
        return np.asarray(vector[0]/np.linalg.norm(vector[0]), dtype=np.float32)

    def bm25(self, query):
        scores = np.zeros(len(self.ids))
        k1, b = self.config['bm25']['k1'], self.config['bm25']['b']
        average = max(float(self.lengths.mean()), 1.)
        for term in sorted(set(self.tokenize(query))):
            bounds = self.vocabulary.get(term)
            if bounds is None:
                continue
            start, end = bounds
            ids, tf = self.posting_rows[start:end], self.posting_tf[start:end].astype(float)
            idf = np.log1p((len(scores)-(end-start)+.5)/((end-start)+.5))
            scores[ids] += idf*tf*(k1+1)/(tf+k1*(1-b+b*self.lengths[ids]/average))
        return scores

    def ordered(self, rows, scores):
        return rows[np.lexsort((self.ids[rows], -scores[rows]))]

    def search(self, query, mode='hybrid', top_k=10, year_min=None, year_max=None, topic_ids=None):
        key = json.dumps([query, mode, top_k, year_min, year_max, topic_ids])
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key], True
        mask = np.ones(len(self.ids), dtype=bool)
        if year_min is not None:
            mask &= self.years >= year_min
        if year_max is not None:
            mask &= self.years <= year_max
        if topic_ids is not None:
            mask &= np.isin(self.topics, topic_ids)
        eligible = np.flatnonzero(mask)
        lexical, dense = np.zeros(len(mask)), np.full(len(mask), np.nan)
        lr, dr = np.array([], dtype=int), np.array([], dtype=int)
        if query.strip() and len(eligible):
            if mode != 'dense':
                lexical = self.bm25(query)
                lr = self.ordered(eligible[lexical[eligible] > 0], lexical)
            if mode != 'bm25':
                vector = self.encode(query)
                if len(eligible) == len(mask):
                    values, rows = self.index.search(vector[None, :], self.config['candidate_depth'])
                    dense[rows[0]] = values[0]
                    dr = self.ordered(rows[0], dense)
                else:
                    # Exact prefilter fallback, in bounded blocks to limit temporary memory.
                    for start in range(0, len(eligible), 256):
                        rows = eligible[start:start+256]
                        dense[rows] = self.vectors[rows]@vector
                    dr = self.ordered(eligible, dense)
        if mode == 'bm25':
            order, scores = lr, lexical
        elif mode == 'dense':
            order, scores = dr, dense
        else:
            scores = np.zeros(len(mask)); candidates = set()
            for ranking in [lr, dr]:
                for rank, row in enumerate(ranking[:self.config['candidate_depth']], 1):
                    scores[row] += 1/(self.config['rrf_k']+rank); candidates.add(int(row))
            order = self.ordered(np.array(sorted(candidates), dtype=int), scores)
        lexical_ranks = {int(row): rank for rank, row in enumerate(lr, 1)}
        dense_ranks = {int(row): rank for rank, row in enumerate(dr, 1)}
        results = []
        with closing(self.connect()) as db:
            for row in order[:top_k]:
                result = dict(db.execute('SELECT * FROM papers WHERE row_id=?', (int(row),)).fetchone())
                result.pop('row_id')
                terms = set(self.tokenize(query))
                sentences = re.split(r'(?<=[.!?])\s+', result['abstract'])
                ranked = [(len(terms & set(self.tokenize(s))), -i, s) for i, s in enumerate(sentences)]
                best = max(ranked)
                result.update(score=float(scores[row]), similarity=float(dense[row]) if np.isfinite(dense[row]) else None,
                              bm25_score=float(lexical[row]), bm25_rank=lexical_ranks.get(int(row)),
                              dense_rank=dense_ranks.get(int(row)), matching_sentence=best[2][:350] if best[0] else '',
                              shared_terms=sorted(terms & set(self.tokenize(result['title']+'. '+result['abstract']))))
                results.append(result)
        self.cache[key] = results
        if len(self.cache) > 64:
            self.cache.popitem(last=False)
        return results, False

    def paper(self, paper_id):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM papers WHERE paper_id=?', (paper_id,)).fetchone()
            if row is None:
                return None
            result = dict(row); result.pop('row_id')
            return result

    def neighborhood(self, paper_id, limit=20):
        with closing(self.connect()) as db:
            center = db.execute('SELECT row_id FROM papers WHERE paper_id=?', (paper_id,)).fetchone()
            if center is None:
                return None
            center = center[0]
            edges = db.execute('SELECT target, weight FROM neighbors WHERE source=? ORDER BY weight DESC, target LIMIT ?',
                               (center, limit)).fetchall()
            rows = [center]+[e['target'] for e in edges]
            nodes = [dict(db.execute('SELECT paper_id,title,year,topic_id,community FROM papers WHERE row_id=?', (row,)).fetchone()) for row in rows]
            return {'nodes': nodes, 'edges': [{'source': paper_id, 'target': node['paper_id'], 'weight': float(edge['weight'])}
                                              for node, edge in zip(nodes[1:], edges)], 'scope': 'Strongest semantic neighbors; bounded ego graph.'}
