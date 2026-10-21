"""FAISS HNSW cosine index, deterministic construction and exact-reference checks."""
from pathlib import Path
from time import perf_counter
import faiss
import numpy as np
from src.pipeline import sha256


def normalized_vectors(vectors):
    x=np.ascontiguousarray(vectors,dtype=np.float32)
    if x.ndim!=2 or not len(x) or not np.isfinite(x).all() or (np.linalg.norm(x,axis=1)==0).any():
        raise ValueError('ANN requires finite nonzero vectors')
    x=x.copy();faiss.normalize_L2(x)
    return x


class CosineHNSW:
    def __init__(self,vectors,m=32,ef_construction=200,ef_search=128,seed=42):
        if m<2 or ef_construction<1 or ef_search<1:raise ValueError('Invalid HNSW parameters')
        x=normalized_vectors(vectors)
        faiss.omp_set_num_threads(1)
        self.index=faiss.IndexHNSWFlat(x.shape[1],int(m),faiss.METRIC_INNER_PRODUCT)
        self.index.hnsw.rng=faiss.RandomGenerator(int(seed))
        self.index.hnsw.efConstruction=int(ef_construction)
        self.index.hnsw.efSearch=int(ef_search)
        start=perf_counter();self.index.add(x);self.build_seconds=perf_counter()-start

    def search(self,queries,k=10,ef_search=None):
        q=normalized_vectors(queries)
        if q.shape[1]!=self.index.d or k<1:raise ValueError('Invalid query dimensions or k')
        if ef_search is not None:self.index.hnsw.efSearch=int(ef_search)
        scores,ids=self.index.search(q,min(int(k),self.index.ntotal))
        return ids,scores

    def save(self,path):faiss.write_index(self.index,str(path))

    @classmethod
    def load(cls,path,expected_hash,rows,dimensions):
        # Verify a locally generated artifact before passing it to the binary reader.
        if sha256(path)!=expected_hash:raise ValueError('ANN index checksum mismatch')
        obj=cls.__new__(cls);faiss.omp_set_num_threads(1)
        obj.index=faiss.read_index(str(path))
        if obj.index.ntotal!=rows or obj.index.d!=dimensions or obj.index.metric_type!=faiss.METRIC_INNER_PRODUCT:
            raise ValueError('ANN index is not aligned to corpus vectors')
        obj.build_seconds=None
        return obj


def recall_checks(index,vectors,queries,k=10,excluded_ids=None,ef_values=(32,64,128)):
    x=normalized_vectors(vectors);q=normalized_vectors(queries)
    excluded_ids=excluded_ids if excluded_ids is not None else [-1]*len(q)
    if len(excluded_ids)!=len(q):raise ValueError('Excluded IDs must align to queries')
    truth=[];thresholds=[]
    for row,exclude in zip(q,excluded_ids):
        scores=x@row
        if exclude>=0:scores[int(exclude)]=-np.inf
        order=np.lexsort((np.arange(len(x)),-scores))
        selected=order[:min(k,len(x)-(exclude>=0))]
        truth.append(set(selected.tolist()));thresholds.append(float(scores[selected[-1]]))
    rows=[]
    original=index.index.hnsw.efSearch
    for ef in ef_values:
        recalls=[];tie_recalls=[];latency=[]
        for i,(query,exclude) in enumerate(zip(q,excluded_ids)):
            start=perf_counter();ids,_=index.search(query[None,:],k+int(exclude>=0),ef)
            latency.append((perf_counter()-start)*1000)
            selected=[int(j) for j in ids[0] if j>=0 and j!=exclude][:len(truth[i])]
            recalls.append(len(set(selected)&truth[i])/len(truth[i]))
            tie_recalls.append(sum(float(x[j]@query)>=thresholds[i]-1e-6 for j in selected)/len(truth[i]))
        rows.append({'ef_search':int(ef),'queries':len(q),'recall_at_10':float(np.mean(recalls)),
            'tie_aware_recall_at_10':float(np.mean(tie_recalls)),
            'index_search_p50_ms':float(np.quantile(latency,.5)),'index_search_p95_ms':float(np.quantile(latency,.95))})
    index.index.hnsw.efSearch=original
    return rows


def ann_graph_edges(index,vectors,k=15,batch_size=256):
    if not 1<=k<len(vectors):raise ValueError('Graph k must be below the corpus size')
    edges={};near_duplicates=[]
    for start in range(0,len(vectors),batch_size):
        ids,scores=index.search(vectors[start:start+batch_size],k+1)
        for offset,(neighbors,weights) in enumerate(zip(ids,scores)):
            i=start+offset
            retained=0
            for j,weight in zip(neighbors,weights):
                j=int(j);weight=float(np.clip(weight,-1,1))
                if j<0 or j==i or weight<=0:continue
                pair=tuple(sorted((i,j)))
                edges[pair]=max(edges.get(pair,0),weight)
                if weight>=.99 and i<j:near_duplicates.append((i,j,weight))
                retained+=1
                if retained==k:break
    return [(i,j,w) for (i,j),w in sorted(edges.items())],near_duplicates
