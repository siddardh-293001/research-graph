import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
import yaml

from src.preprocessing import clean_metadata, prepare_embedding_corpus, classify_paper
from src.baseline_methods import build_graph, integrate_analysis
from src.pipeline import run, ROOT, sha256


class PreprocessingTests(unittest.TestCase):
    def test_rag_at_title_boundaries(self):
        self.assertEqual(classify_paper('RAG and search'), 'CORE_RAG')
        self.assertEqual(classify_paper('Search with RAG'), 'CORE_RAG')

    def test_legacy_title_dedup_and_abstract_exclusion(self):
        frame = pd.DataFrame([
            dict(paper_id='a', title='Same title!', abstract=None, year=2020, citation_count=2),
            dict(paper_id='b', title='Same title', abstract='abstract', year=2021, citation_count=5),
            dict(paper_id='c', title='Other', abstract=' ', year=2021, citation_count=0),
        ])
        clean = clean_metadata(frame)
        self.assertEqual(set(clean.paper_id), {'b', 'c'})
        self.assertEqual(prepare_embedding_corpus(clean).paper_id.tolist(), ['b'])

    def test_duplicate_ids_rejected(self):
        frame = pd.DataFrame(dict(paper_id=['x', 'x'], title=['a', 'b'],
            abstract=['a', 'b'], year=[2020, 2021], citation_count=[0, 1]))
        with self.assertRaisesRegex(ValueError, 'unique'):
            clean_metadata(frame)

    def test_graph_guard(self):
        with self.assertRaisesRegex(ValueError, 'guard'):
            build_graph(pd.DataFrame(index=range(3)), np.eye(3), {'max_papers': 2}, 42)

    def test_analysis_joins_ids_even_when_titles_match(self):
        papers = pd.DataFrame({'paper_id': ['b', 'a']})
        topics = pd.DataFrame(dict(paper_id=['a', 'b'], title=['same', 'same'],
            year=[2020, 2020], citation_count=[1, 3], topic_id=[1, 2], topic_name=['one', 'two']))
        nodes = pd.DataFrame(dict(paper_id=['a', 'b'], community=[4, 5],
            degree_centrality=[.2, .3], betweenness_centrality=[0., .1], pagerank=[.4, .6]))
        result = integrate_analysis(papers, topics, nodes)
        self.assertEqual(result.paper_id.tolist(), ['b', 'a'])
        self.assertEqual(result.community.tolist(), [5, 4])


class PipelineIntegrationTests(unittest.TestCase):
    def test_offline_rebuild_is_repeatable_and_preserves_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            # Fixture has repeated vocabulary and distinct subject groups, with
            # deliberately identical titles to test ID-based downstream joins.
            records = []
            for i in range(12):
                records.append(dict(paper_id=f'W{i}', title=f'Paper {i}', year=2020 + i % 2,
                    citation_count=i, abstract=('retrieval search semantic language document ' if i < 6 else
                    'medical clinical patient diagnosis hospital ') * 4))
            source = tmp / 'input.parquet'
            pd.DataFrame(records).to_parquet(source, index=False)
            config = yaml.safe_load((ROOT / 'config/baseline.yaml').read_text())
            config.update(source=str(source), output_root=str(tmp / 'runs'))
            config['topics'].update(count=2, min_df=1, max_df=1.0)
            config_path = tmp / 'test.yaml'
            config_path.write_text(yaml.safe_dump(config))
            original_hash = sha256(source)

            def encoder(papers, config, seed):
                vectors = np.array([[1., .1] if int(p[1:]) < 6 else [.1, 1.] for p in papers.paper_id])
                return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

            first = run(config_path, encoder=encoder, compare=False)
            second = run(config_path, encoder=encoder, compare=False)
            manifest = json.loads((first / 'manifest.json').read_text())
            self.assertEqual(manifest['status'], 'complete')
            self.assertEqual(manifest['counts']['papers'], 12)
            self.assertEqual(manifest['counts']['edges'], 30)
            self.assertEqual(manifest['counts']['communities'], 2)
            self.assertEqual(sha256(source), original_hash)
            for artifact in manifest['artifacts']:
                self.assertEqual(sha256(first / artifact), sha256(second / artifact), artifact)
            analysis = pd.read_parquet(first / 'research_analysis_dataset.parquet')
            # Year normalization is recomputed from the fixture, not copied.
            self.assertTrue(np.allclose(analysis.relative_citations,
                analysis.citation_count / (analysis.groupby('year').citation_count.transform('median') + 1)))
            for artifact, expected in manifest['artifacts'].items():
                self.assertEqual(sha256(first / artifact), expected)

    def test_failed_run_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            config = yaml.safe_load((ROOT / 'config/baseline.yaml').read_text())
            config['output_root'] = str(tmp / 'runs')
            config['graph']['max_papers'] = 1
            config_path = tmp / 'test.yaml'
            config_path.write_text(yaml.safe_dump(config))
            with self.assertRaisesRegex(ValueError, 'guard'):
                run(config_path, compare=False)
            manifest = json.loads(next((tmp / 'runs').glob('*/manifest.json')).read_text())
            self.assertEqual(manifest['status'], 'failed')
