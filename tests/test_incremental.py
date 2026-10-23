import tempfile
import unittest
from pathlib import Path
import numpy as np
from src.incremental import apply_batch,assign_neighbors,distribution_drift
from src.paper_insights import summarize,overlap_terms

class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'updates.sqlite'
        self.row={'paper_id':'https://openalex.org/W1','title':'Graph retrieval','abstract':'We study graph retrieval. We evaluate our model. Results show improved recall.','citation_count':3,'doi':'https://doi.org/10.1/demo','updated_date':'2026-01-01T00:00:00Z'}
    def tearDown(self):self.temp.cleanup()
    def test_replay_identity_and_newer_metadata(self):
        self.assertEqual(apply_batch(self.path,[self.row])['added'],1)
        self.assertTrue(apply_batch(self.path,[self.row])['replayed'])
        changed={**self.row,'paper_id':'https://openalex.org/W2','citation_count':6,'updated_date':'2026-02-01T00:00:00Z'}
        r=apply_batch(self.path,[changed]);self.assertEqual(r['updated'],1);self.assertEqual(r['total_staged'],1)
        self.assertEqual(apply_batch(self.path,[{**self.row,'citation_count':4}])['stale'],1)
    def test_invalid_and_ambiguous_batches_do_not_partially_apply(self):
        apply_batch(self.path,[self.row])
        with self.assertRaises(ValueError):apply_batch(self.path,[{**self.row,'citation_count':8}])
        with self.assertRaises(ValueError):apply_batch(self.path,[{**self.row,'citation_count':-1}])
        other={**self.row,'paper_id':'https://openalex.org/W3','doi':'10.1/other'}
        apply_batch(self.path,[other])
        with self.assertRaises(ValueError):apply_batch(self.path,[{**other,'doi':self.row['doi'],'updated_date':'2026-03-01'}])
    def test_assignment_and_drift_have_explicit_bounds(self):
        labels,confidence=assign_neighbors([[1,0],[0,1]],[3,4],[[.9,.1],[-1,-1]],k=1)
        self.assertEqual(labels.tolist(),[3,-1]);self.assertGreater(confidence[0],.9)
        self.assertEqual(distribution_drift([1,1],[1,1]),0)
        self.assertEqual(distribution_drift([1,1],[2,2]),1)
        with self.assertRaises(ValueError):assign_neighbors([[0,0]],[1],[[1,0]])
    def test_summary_only_uses_original_abstract_sentences(self):
        out=summarize(self.row['title'],self.row['abstract'])
        self.assertTrue(all(s in self.row['abstract'] for s in out['sentences']))
        self.assertLessEqual(len(out['sentences']),3)
        self.assertEqual(summarize('Missing','')['sentences'],[])
        self.assertIn('graph',overlap_terms('graph retrieval','graph models'))

class FreeCollectionTests(unittest.TestCase):
    def test_anonymous_bounded_collection_stages_without_publishing(self):
        from scripts.collect_recent import collect
        class Response:
            status_code=200
            def json(self):return {'meta':{'count':1},'results':[{'id':'https://openalex.org/W9','title':'Software engineering','publication_year':2026,'publication_date':'2026-10-21','cited_by_count':0,'abstract_inverted_index':{'Software':[0],'engineering':[1]},'updated_date':'2026-10-22T00:00:00Z'}]}
        class Session:
            def get(self,url,**kwargs):
                self.kwargs=kwargs
                return Response()
        with tempfile.TemporaryDirectory() as temp:
            session=Session();result=collect(Path(temp)/'batch',session=session)
            self.assertEqual(result['papers'],1);self.assertFalse(result['authenticated']);self.assertEqual(result['paid_spend_usd'],0)
            self.assertNotIn('api_key',session.kwargs['params']);self.assertFalse(session.kwargs['allow_redirects'])
            self.assertEqual(result['ledger']['pending_rebuild'],1)
    def test_quota_exhaustion_has_no_authenticated_fallback(self):
        from scripts.collect_recent import collect
        class Session:
            def get(self,*args,**kwargs):return type('Response',(),{'status_code':429})()
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(RuntimeError):collect(Path(temp)/'batch',session=Session())
            with self.assertRaises(ValueError):collect(Path(temp)/'other',pages=6)


class DriftPromotionTests(unittest.TestCase):
    def test_batch_novelty_is_warning_but_large_cumulative_shift_blocks(self):
        from src.incremental import update_drift
        base=[0]*10000;added=[1]*100
        result=update_drift(base,added,base+added)
        self.assertTrue(result['batch_warning'])
        self.assertLess(result['corpus_js_bits'],.1)
        with self.assertRaises(ValueError):update_drift(base,[1]*10000,base+[1]*10000)

    def test_corpus_reference_does_not_reset_each_batch(self):
        from src.incremental import update_drift
        with self.assertRaises(ValueError):update_drift([1]*100,[1],[1]*101,{'0':10000})
