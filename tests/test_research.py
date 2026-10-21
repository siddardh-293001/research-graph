import copy
import json
from pathlib import Path
import tempfile
import unittest

import networkx as nx
import numpy as np
import pandas as pd
import yaml
from sklearn.metrics import adjusted_mutual_info_score
from src.research import run as research_run
from src.research_graph import (knn_edges, graph_from_edges, leiden_partition,
    choose_resolution, graph_metrics, citation_edges)
from src.research_statistics import (alignment_test, normalize_citations, cliffs_delta,
    eta_squared_h, spearman_interval, topic_citation_tests, temporal_prevalence)
from src.research_topics import document_npmi, matched_term_jaccard, stratified_indices
from src.pipeline import run as baseline_run, ROOT, sha256


class ResearchGraphTests(unittest.TestCase):
    def test_knn_matches_exact_ranking_and_has_no_self_or_duplicate_edges(self):
        vectors = np.array([[1.,0.], [.9,.1], [0.,1.], [.1,.9]])
        edges = knn_edges(vectors,1)
        self.assertEqual({(i,j) for i,j,_ in edges},{(0,1),(2,3)})
        self.assertTrue(all(i<j for i,j,_ in edges))
        self.assertEqual(knn_edges(vectors,1,batch_size=1), edges)

    def test_mutual_requires_both_selections_and_preserves_isolates(self):
        vectors = np.array([[1.,0.],[.99,.01],[.8,.2]])
        union = knn_edges(vectors,1,'union')
        mutual = knn_edges(vectors,1,'mutual')
        self.assertGreater(len(union),len(mutual))
        graph = graph_from_edges(3,mutual)
        self.assertEqual(len(graph),3)
        self.assertGreater(nx.number_of_isolates(graph),0)

    def test_identical_vectors_ties_do_not_create_self_loops(self):
        edges = knn_edges(np.ones((5,2)),1)
        self.assertTrue(all(i!=j for i,j,_ in edges))
        self.assertLessEqual(len(edges),5)

    def test_leiden_seeded_partition_and_isolates(self):
        graph = graph_from_edges(5,[(0,1,.9),(2,3,.9)])
        a=leiden_partition(graph,seed=42)
        b=leiden_partition(graph,seed=42)
        np.testing.assert_array_equal(a,b)
        self.assertEqual(a[0],a[1])
        self.assertEqual(a[2],a[3])
        self.assertNotEqual(a[4],a[0])

    def test_resolution_selection_ignores_alignment_scores(self):
        rows=[dict(resolution=.2,communities=10,topic_ami=0),dict(resolution=1.,communities=20,topic_ami=1)]
        self.assertEqual(choose_resolution(rows,10),.2)

    def test_betweenness_uses_distance_not_similarity(self):
        graph=graph_from_edges(3,[(0,1,.9),(1,2,.9),(0,2,.5)])
        metrics,meta=graph_metrics(graph)
        self.assertGreater(metrics['betweenness_centrality'][1],0)
        self.assertEqual(nx.betweenness_centrality(graph,weight='weight')[1],0)
        self.assertEqual(meta['betweenness_method'],'exact')

    def test_citation_edges_preserve_direction_and_report_outside_corpus(self):
        papers=pd.DataFrame({'paper_id':['a','b','c'],'referenced_works':[['b','b','a','outside'],[],['a']]})
        edges,coverage=citation_edges(papers)
        self.assertEqual(edges,[(0,1),(2,0)])
        self.assertEqual(coverage['external_reference_entries'],1)
        self.assertEqual(coverage['self_reference_entries'],1)

    def test_invalid_knn_input(self):
        for vectors,k in [(np.eye(2),2),(np.zeros((3,2)),1),(np.array([[np.nan,1],[1,0]]),1)]:
            with self.assertRaises(ValueError):knn_edges(vectors,k)
        with self.assertRaises(ValueError):graph_from_edges(2,[(0,3,.9)])


class ResearchStatisticsTests(unittest.TestCase):
    def test_alignment_permutation_null_and_seeded_intervals(self):
        labels=np.repeat(np.arange(4),10)
        a,null=alignment_test(labels,labels,permutations=19,bootstraps=20)
        b,other=alignment_test(labels,labels,permutations=19,bootstraps=20)
        self.assertEqual(a,b)
        np.testing.assert_array_equal(null,other)
        self.assertEqual(a['ami'],1)
        self.assertAlmostEqual(a['permutation_p_one_sided'],.05)
        self.assertLess(a['null_mean'],.1)

    def test_normalization_cohorts_fallback_and_zero_mean(self):
        papers=pd.DataFrame(dict(paper_id=list('abcdef'),year=[2020]*4+[2021]*2,
            citation_count=[0,4,8,0,0,0],topics=[[{'id':'X','score':1}]]*3+[[{'id':'Y','score':1}]]*3))
        normalized=normalize_citations(papers,minimum=3)
        np.testing.assert_allclose(normalized.normalized_citations.iloc[:3],[0,1,2])
        self.assertEqual(normalized.normalization_level.iloc[3],'year')
        self.assertEqual(normalized.normalization_level.iloc[4],'corpus')
        all_zero=papers.copy();all_zero['citation_count']=0
        self.assertTrue(normalize_citations(all_zero,minimum=1).normalized_citations.eq(0).all())

    def test_effect_sizes_and_dunn_tie_handling(self):
        self.assertEqual(cliffs_delta([3,4],[1,2]),1)
        self.assertEqual(cliffs_delta([1,2],[3,4]),-1)
        self.assertEqual(cliffs_delta([1,1],[1,1]),0)
        h,p,effect=eta_squared_h([np.ones(5),np.ones(5)])
        self.assertEqual((h,p,effect),(0.,1.,0.))
        frame=pd.DataFrame({'topic_id':[1]*5+[2]*5,'normalized_citations':[0]*5+[10]*5})
        summary,pairs=topic_citation_tests(frame,bootstraps=20)
        self.assertGreater(summary['eta_squared_h'],.5)
        self.assertEqual(pairs.iloc[0].cliffs_delta_a_minus_b,-1)
        self.assertLess(pairs.iloc[0].dunn_p_holm,.05)

    def test_spearman_intervals_and_constant_inputs(self):
        result=spearman_interval(np.arange(20),np.arange(20),bootstraps=20)
        self.assertAlmostEqual(result['rho'],1)
        self.assertIsNone(spearman_interval(np.ones(10),np.arange(10))['rho'])

    def test_temporal_zero_cells_and_wilson_intervals(self):
        frame=pd.DataFrame({'year':[2020,2020,2021],'topic_id':[1,1,2]})
        output=temporal_prevalence(frame)
        self.assertEqual(len(output),4)
        self.assertTrue(np.allclose(output.groupby('year').topic_share.sum(),1))
        self.assertTrue(output.wilson_lower.le(output.topic_share+1e-12).all())
        self.assertTrue(output.wilson_upper.ge(output.topic_share-1e-12).all())


class ResearchTopicTests(unittest.TestCase):
    def test_document_npmi_known_cooccurrences(self):
        self.assertAlmostEqual(document_npmi([[1,1],[1,1],[0,0],[0,0]]),1)
        self.assertAlmostEqual(document_npmi([[1,0],[1,0],[0,1],[0,1]]),-1)
        self.assertAlmostEqual(document_npmi([[1,1],[1,0],[0,1],[0,0]]),0)

    def test_term_matching_ignores_topic_label_permutations(self):
        self.assertEqual(matched_term_jaccard([['a','b'],['c','d']],[['c','d'],['a','b']]),1)

    def test_stratification_is_reproducible_and_retains_each_year(self):
        papers=pd.DataFrame({'year':[2020]*10+[2021]*2})
        a=stratified_indices(papers,.8,42)
        np.testing.assert_array_equal(a,stratified_indices(papers,.8,42))
        self.assertEqual(set(papers.iloc[a].year),{2020,2021})


class ResearchIntegrationTests(unittest.TestCase):
    def test_small_three_view_analysis_reproduces_all_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp)
            records=[]
            for i in range(12):
                records.append(dict(paper_id=f'W{i}',title=f'Paper {i}',year=2020+i%2,citation_count=i,
                    abstract=('retrieval search semantic language document ' if i<6 else 'medical clinical patient diagnosis hospital ')*4,
                    topics=[{'id':'T1' if i<6 else 'T2','score':1.}],
                    referenced_works=[f'W{(i//6)*6+(i+1)%6}']))
            source=tmp/'input.parquet';pd.DataFrame(records).to_parquet(source,index=False)
            config=yaml.safe_load((ROOT/'config/baseline.yaml').read_text())
            config.update(source=str(source),output_root=str(tmp/'baseline'))
            config['topics'].update(count=2,min_df=1,max_df=1.)
            path=tmp/'baseline.yaml';path.write_text(yaml.safe_dump(config))
            def encoder(papers,*args):
                x=np.array([[1.,.1] if int(p[1:])<6 else [.1,1.] for p in papers.paper_id])
                return x/np.linalg.norm(x,axis=1,keepdims=True)
            baseline=baseline_run(path,encoder=encoder,compare=False)
            research=yaml.safe_load((ROOT/'config/research.yaml').read_text())
            research['graph'].update(k_values=[2],primary_k=2,resolutions=[.2,1.],seeds=[42,43])
            research['topics'].update(counts=[2],primary_count=2,seeds=[42,43],min_df=1,max_df=1.,max_iter=200)
            research['statistics'].update(permutations=9,bootstrap_samples=10,min_normalization_cohort=2)
            research_path=tmp/'research.yaml';research_path.write_text(yaml.safe_dump(research))
            before=sha256(source)
            first=research_run(research_path,baseline,tmp/'research')
            second=research_run(research_path,baseline,tmp/'research')
            a,b=[json.loads((p/'manifest.json').read_text()) for p in [first,second]]
            self.assertEqual(a['status'],'complete')
            self.assertEqual(a['artifacts'],b['artifacts'])
            self.assertEqual(sha256(source),before)
            report=json.loads((first/'report.json').read_text())
            self.assertEqual(report['papers'],12)
            self.assertEqual(report['citation_view']['coverage']['internal_incidence_fraction'],1)
            self.assertEqual(report['primary_graph']['communities'],2)
            self.assertTrue((first/'research_overview.png').is_file())
