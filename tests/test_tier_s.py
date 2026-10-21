"""Offline checks for identity, snapshot recovery, ANN and scale curation."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
import yaml
from src.corpus import canonical_arxiv, coalesce_metadata
from src.ann import CosineHNSW, recall_checks, ann_graph_edges
from src.ingestion.snapshot import collect, iter_snapshot
from src.pipeline import ROOT, sha256
from src.tier_s import curate, effective_benchmark


class IdentityTests(unittest.TestCase):
    def test_arxiv_versions(self):
        for value in ['https://arxiv.org/pdf/2301.12345v2.pdf','arXiv:2301.12345v3','https://doi.org/10.48550/arXiv.2301.12345']:
            self.assertEqual(canonical_arxiv(value),'2301.12345')
        self.assertEqual(canonical_arxiv('hep-th/9901001v4'),'hep-th/9901001')
        self.assertIsNone(canonical_arxiv('arbitrary title v2'))

    def test_transitive_merge_freshness_and_reference_alias(self):
        rows=[{'paper_id':'seed','doi':'https://doi.org/10.1/ABC','abstract':'longest preserved abstract','citation_count':1,'updated_date':'2020'},
            {'paper_id':'new','doi':'10.1/abc','arxiv_id':'2301.12345v1','abstract':'short','citation_count':12,'updated_date':'2026'},
            {'paper_id':'third','arxiv_id':'2301.12345v3','citation_count':8,'updated_date':'2025'},
            {'paper_id':'citing','referenced_works':['new','third','outside','citing']}]
        merged,aliases=coalesce_metadata(rows,['seed'])
        self.assertEqual(aliases['third'],'seed')
        seed=next(r for r in merged if r['paper_id']=='seed')
        self.assertEqual(seed['citation_count'],12)
        self.assertEqual(seed['abstract'],'longest preserved abstract')
        self.assertEqual(next(r for r in merged if r['paper_id']=='citing')['referenced_works'],['outside','seed'])

    def test_titles_do_not_establish_identity(self):
        records,_=coalesce_metadata([{'paper_id':'a','title':'same'},{'paper_id':'b','title':'same'}])
        self.assertEqual(len(records),2)


class Response:
    def __init__(self,results=(),cursor=None,status=200):
        self.status_code=status;self.headers={};self.payload={'results':list(results),'meta':{'next_cursor':cursor,'count':2}}
    def json(self):return self.payload


class Session:
    def __init__(self,responses):self.responses=iter(responses);self.headers={};self.calls=[]
    def get(self,*args,**kwargs):self.calls.append(kwargs);return next(self.responses)


class SnapshotTests(unittest.TestCase):
    def settings(self,directory,**overrides):
        config=yaml.safe_load((ROOT/'config/tier_s.yaml').read_text())
        config['source'].update(raw_limit=2,per_page=1,min_interval_seconds=0,**overrides)
        path=directory/'config.yaml';path.write_text(yaml.safe_dump(config));return path

    @patch('src.ingestion.snapshot.api_key',return_value='test-secret')
    def test_cursor_raw_replay_and_complete_reuse(self,_):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config=self.settings(root);http=Session([Response([{'id':'a'}],'next'),Response([{'id':'b'}],None)])
            output=collect(config,root/'raw',http,lambda _:None)
            self.assertEqual([r['id'] for r in iter_snapshot(output)],['a','b'])
            self.assertEqual(http.calls[1]['params']['cursor'],'next')
            self.assertNotIn('api_key',http.calls[0]['params'])
            self.assertFalse(http.calls[0]['allow_redirects'])
            self.assertNotIn('test-secret',(output/'manifest.json').read_text())
            collect(config,output,Session([]),lambda _:None)
            page=output/'page-00000.json.gz';page.write_bytes(b'corrupted')
            with self.assertRaisesRegex(ValueError,'checksum'):list(iter_snapshot(output))

    @patch('src.ingestion.snapshot.api_key',return_value='test-secret')
    def test_interrupt_and_resume_cursor(self,_):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config=self.settings(root)
            with self.assertRaisesRegex(RuntimeError,'HTTP 401'):
                collect(config,root/'raw',Session([Response([{'id':'a'}],'next'),Response(status=401)]),lambda _:None)
            http=Session([Response([{'id':'b'}],None)])
            collect(config,root/'raw',http,lambda _:None)
            self.assertEqual(http.calls[0]['params']['cursor'],'next')
            self.assertEqual(len(list(iter_snapshot(root/'raw'))),2)

    @patch('src.ingestion.snapshot.api_key',return_value='test-secret')
    def test_retry_and_request_budget(self,_):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config=self.settings(root,max_requests=2)
            http=Session([Response(status=429),Response([{'id':'a'}],'next')])
            with self.assertRaisesRegex(RuntimeError,'cap reached'):collect(config,root/'raw',http,lambda _:None)
            self.assertEqual(json.loads((root/'raw/manifest.json').read_text())['requests'],2)


class ANNTests(unittest.TestCase):
    def setUp(self):
        self.vectors=np.random.default_rng(42).normal(size=(100,16)).astype('float32')
        self.index=CosineHNSW(self.vectors,m=8,ef_search=128)

    def test_exact_recall_and_no_self_graph_edges(self):
        checks=recall_checks(self.index,self.vectors,self.vectors[:10],excluded_ids=list(range(10)),ef_values=[128])
        self.assertAlmostEqual(checks[0]['recall_at_10'],1.)
        edges,_=ann_graph_edges(self.index,self.vectors,k=5)
        self.assertEqual(len({(i,j) for i,j,_ in edges}),len(edges))
        self.assertTrue(all(i<j and 0<w<=1 for i,j,w in edges))

    def test_persist_and_alignment_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'index.faiss';self.index.save(path)
            loaded=CosineHNSW.load(path,sha256(path),100,16)
            np.testing.assert_array_equal(loaded.search(self.vectors[:2])[0],self.index.search(self.vectors[:2])[0])
            with self.assertRaisesRegex(ValueError,'checksum'):CosineHNSW.load(path,'wrong',100,16)
            with self.assertRaisesRegex(ValueError,'aligned'):CosineHNSW.load(path,sha256(path),99,16)

    def test_invalid_vectors(self):
        for value in [np.zeros((2,3)),np.full((2,3),np.nan)]:
            with self.assertRaises(ValueError):CosineHNSW(value)


class CurationTests(unittest.TestCase):
    def test_quality_rejection_seed_retention_and_reference_union(self):
        seed=pd.DataFrame([{'paper_id':'seed','doi':'10.1/x','title':'Seed','abstract':'short seed','year':2021,'citation_count':1,'referenced_works':['external']}])
        raw=[{'id':'new','doi':'10.1/x','title':'Updated','publication_year':2021,'cited_by_count':5,'abstract_inverted_index':{'valid':[0],'abstract':[1]},'referenced_works':['other']},
             {'id':'reject','title':'Missing abstract','publication_year':2022,'cited_by_count':1}]
        papers,aliases,coverage=curate(raw,seed,{'target_papers':2,'source':{'min_abstract_words':2}})
        self.assertEqual(papers.paper_id.tolist(),['seed']);self.assertEqual(aliases['new'],'seed')
        self.assertEqual(papers.referenced_works.iloc[0],['external','other'])
        self.assertEqual(coverage['rejected_raw_records'],{'short_or_missing_abstract':1})
        self.assertEqual(coverage['seed_identities_retained'],1)

    def test_benchmark_cannot_silently_drop_unknown_identity(self):
        with self.assertRaisesRegex(ValueError,'identity lost'):effective_benchmark({},set())

class TierSIntegrationTests(unittest.TestCase):
    def test_full_offline_build_load_and_index_reconstruction(self):
        from src.tier_s import run
        from src.artifacts import load_run
        from src.search import SearchEngine
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'seed.parquet'
            records=[dict(paper_id=f'W{i}',doi=None,title=f'Paper {i}',year=2020+i%2,citation_count=i,
                referenced_works=['W0','outside'],abstract=('retrieval language semantic document ' if i<6 else 'medical clinical patient hospital ')*5) for i in range(12)]
            pd.DataFrame(records).to_parquet(source,index=False)
            snapshot=root/'snapshot';snapshot.mkdir();(snapshot/'manifest.json').write_text('{}')
            config=yaml.safe_load((ROOT/'config/tier_s.yaml').read_text())
            config.update(seed_metadata=str(source),target_papers=12,output_root=str(root/'runs'))
            config['topics'].update(count=2,min_df=1,max_df=1.,fit_sample=12)
            config['ann'].update(graph_k=3,evaluation_queries=12)
            settings=root/'config.yaml';settings.write_text(yaml.safe_dump(config))
            vectors=np.random.default_rng(42).normal(size=(12,16)).astype('float32')
            vectors/=np.linalg.norm(vectors,axis=1,keepdims=True)
            class Encoder:
                def encode(self,texts,**kwargs):return np.tile(vectors[0],(len(texts),1))
            benchmark={'version':'test','status':'fixture','queries':[{'query_id':f'q{i}','query':f'query {i}',
                'judgments':[{'paper_id':'W0','grade':3}]} for i in range(50)]}
            with patch('src.tier_s.iter_snapshot',return_value=iter([])), patch('src.tier_s.cached_embeddings',return_value=(vectors,['fixture']*12,Encoder())), patch('src.tier_s.effective_benchmark',return_value=benchmark):
                output=run(snapshot,settings)
            directory,manifest,papers,stored,graph=load_run(output)
            self.assertEqual(len(papers),12);self.assertTrue(all(manifest['gates'].values()))
            self.assertGreater(graph.number_of_edges(),0)
            for name,expected in manifest['artifacts'].items():self.assertEqual(sha256(directory/name),expected)
            engine=SearchEngine.from_run(output,encoder=Encoder())
            small=engine.search('query 0',mode='hybrid',top_k=5)
            large=engine.search('query 0',mode='hybrid',top_k=12)
            self.assertEqual(small.paper_id.tolist(),large.paper_id.tolist()[:5])
            approximate=engine.search('query 0',mode='dense',year_min=2021,top_k=5)
            engine.ann=None
            exact=engine.search('query 0',mode='dense',year_min=2021,top_k=5)
            self.assertEqual(approximate.paper_id.tolist(),exact.paper_id.tolist())
            self.assertTrue(approximate.year.eq(2021).all())
            rebuilt=CosineHNSW(stored,seed=42);rebuilt.save(root/'rebuilt.faiss')
            self.assertEqual(sha256(root/'rebuilt.faiss'),manifest['artifacts']['search_hnsw.faiss'])

if __name__=='__main__':unittest.main()
