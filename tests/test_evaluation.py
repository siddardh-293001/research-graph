import copy
import json
import unittest
import numpy as np
from src.evaluation import retrieval_metrics, bootstrap_mean, validate_benchmark
from src.pipeline import ROOT


class EvaluationTests(unittest.TestCase):
    def test_metric_known_example(self):
        metrics = retrieval_metrics(['b', 'a', 'x'], {'a': 3, 'b': 1})
        expected = (1 + 7/np.log2(3)) / (7 + 1/np.log2(3))
        self.assertAlmostEqual(metrics['ndcg_at_10'], expected)
        self.assertEqual(metrics['reciprocal_rank'], 1)
        self.assertEqual(metrics['recall_at_20'], 1)

    def test_absent_relevant_and_cutoffs(self):
        missing = retrieval_metrics(['x'], {'a': 3})
        self.assertEqual(missing['ndcg_at_10'], 0)
        self.assertEqual(missing['reciprocal_rank'], 0)
        self.assertEqual(missing['recall_at_20'], 0)
        last = retrieval_metrics([f'x{i}' for i in range(20)] + ['a'], {'a': 3})
        self.assertEqual(last['recall_at_20'], 0)
        self.assertAlmostEqual(last['reciprocal_rank'], 1/21)

    def test_duplicate_ranking_and_zero_positives_rejected(self):
        with self.assertRaises(ValueError):
            retrieval_metrics(['a', 'a'], {'a': 3})
        with self.assertRaises(ValueError):
            retrieval_metrics(['a'], {'a': 0})

    def test_bootstrap_is_seeded_and_contains_mean(self):
        a = bootstrap_mean([0., .5, 1.])
        self.assertEqual(a, bootstrap_mean([0., .5, 1.]))
        self.assertLessEqual(a['ci95'][0], a['mean'])
        self.assertGreaterEqual(a['ci95'][1], a['mean'])
        self.assertEqual(bootstrap_mean([1., 1.])['ci95'], [1., 1.])

    def test_fixed_benchmark_integrity_and_validation(self):
        benchmark = json.loads((ROOT/'data/benchmark/queries.json').read_text())
        ids = {j['paper_id'] for q in benchmark['queries'] for j in q['judgments']}
        self.assertEqual(len(validate_benchmark(benchmark, ids)), 50)
        invalid = copy.deepcopy(benchmark)
        invalid['queries'][0]['judgments'][0]['grade'] = 4
        with self.assertRaises(ValueError):
            validate_benchmark(invalid, ids)
        with self.assertRaises(ValueError):
            validate_benchmark(benchmark, set())
