import math
import unittest
import numpy as np
import pandas as pd
from src.search import BM25, SearchEngine, reciprocal_rank_fusion


class Encoder:
    def encode(self, texts, **kwargs):
        return np.tile([1., 0.], (len(texts), 1))


class SearchTests(unittest.TestCase):
    def setUp(self):
        papers = pd.DataFrame(dict(paper_id=['c', 'a', 'b'], title=['graph', 'graph', 'medical'],
            abstract=['networks.', 'knowledge.', 'clinical.'], year=[2020, 2021, 2022],
            topic_id=[1, 1, 2], topic_name=['graph', 'graph', 'health'], _graph_node=[0, 1, 2]))
        self.config = dict(bm25=dict(k1=1.5, b=.75), rrf_k=60, candidate_depth=100,
                           max_query_chars=2000, max_results=1000)
        self.engine = SearchEngine(papers, np.array([[1., 0], [1., 0], [0., 1]]), self.config, Encoder())

    def test_bm25_known_formula(self):
        index = BM25(['graph graph', 'graph medical', 'medical'])
        scores = index.score('graph')
        expected = math.log1p(1.5 / 2.5) * 2 * 2.5 / (2 + 1.5 * (.25 + .75 * 2 / (5/3)))
        self.assertAlmostEqual(scores[0], expected)
        self.assertGreater(scores[0], scores[1])
        self.assertEqual(scores[2], 0)

    def test_rrf_known_formula(self):
        fused = reciprocal_rank_fusion([[0, 1], [1, 2]], k=60)
        self.assertAlmostEqual(fused[1], 1/62 + 1/61)
        self.assertGreater(fused[1], fused[0])

    def test_ties_are_broken_by_paper_id(self):
        for mode in ('bm25', 'dense', 'hybrid'):
            result = self.engine.search('graph', mode)
            self.assertEqual(result.paper_id.tolist()[:2], ['a', 'c'])

    def test_filters_apply_before_top_k(self):
        result = self.engine.search('graph', 'dense', 1, year_min=2022, topic_ids=[2])
        self.assertEqual(result.paper_id.tolist(), ['b'])
        self.assertEqual(result._graph_node.tolist(), [2])

    def test_bm25_does_not_load_encoder_and_oov_does_not_return_zero_matches(self):
        self.engine.encoder = None
        self.assertEqual(len(self.engine.search('graph', 'bm25')), 2)
        self.assertTrue(self.engine.search('unknownword', 'bm25').empty)

    def test_hybrid_uses_dense_fallback_without_lexical_matches(self):
        a = self.engine.search('unseenword', 'hybrid')
        b = self.engine.search('unseenword', 'dense')
        self.assertEqual(a.paper_id.tolist(), b.paper_id.tolist())

    def test_requested_result_count_does_not_change_ranking(self):
        for mode in ('bm25', 'dense', 'hybrid'):
            small = self.engine.search('graph', mode, 1)
            large = self.engine.search('graph', mode, 3)
            self.assertEqual(small.paper_id.tolist(), large.paper_id.tolist()[:1])

    def test_blank_query_and_empty_filter_return_empty(self):
        self.assertTrue(self.engine.search(' ').empty)
        self.assertTrue(self.engine.search('graph', year_min=2030).empty)
        self.assertTrue(self.engine.search('graph', topic_ids=[]).empty)

    def test_invalid_inputs(self):
        for args in [dict(mode='invalid'), dict(top_k=0), dict(year_min=2022, year_max=2020),
                     dict(query_vector=np.array([np.nan, 0.])), dict(query_vector=np.ones(3))]:
            with self.assertRaises(ValueError):
                self.engine.search('graph', **args)
        with self.assertRaises(ValueError):
            self.engine.search('x'*2001)

    def test_explanation_is_grounded_in_paper_text(self):
        result = self.engine.search('clinical', 'bm25')
        self.assertEqual(result.iloc[0].shared_terms, ['clinical'])
        self.assertEqual(result.iloc[0].matching_sentence, 'clinical.')
        self.assertEqual(self.engine.matching_sentence('No overlap.', {'graph'}), '')
