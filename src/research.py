"""Section 4 reproducible research methods: python -m src.research."""
import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
import platform
from pathlib import Path
import tempfile
import uuid

# Scientific plotting caches must remain in a writable task-local temp location.
os.environ.setdefault('MPLCONFIGDIR', str(Path(tempfile.gettempdir())/'researchgraph-matplotlib'))
os.environ.setdefault('XDG_CACHE_HOME', str(Path(tempfile.gettempdir())/'researchgraph-cache'))
import networkx as nx
import numpy as np
import pandas as pd
from sklearn.metrics import adjusted_mutual_info_score, adjusted_rand_score, normalized_mutual_info_score
from threadpoolctl import threadpool_limits
import yaml
from src.artifacts import load_run
from src.pipeline import ROOT, sha256
from src.research_graph import (knn_edges, graph_from_edges, leiden_partition, choose_resolution,
    graph_metrics, citation_edges, partition_seed_stability)
from src.research_topics import topic_sensitivity
from src.research_statistics import (alignment_test, normalize_citations, spearman_interval,
    topic_citation_tests, temporal_prevalence)


def save_table(output, name, frame):
    frame.to_parquet(output/f'{name}.parquet', index=False)


def plots(output, sweep, stability, correlations, temporal):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), constrained_layout=True)
    for (variant, k), group in sweep.groupby(['variant', 'k']):
        curve = group.groupby('resolution').topic_ami.mean()
        axes[0, 0].plot(curve.index, curve.values, marker='.', label=f'{variant} k={k}')
    axes[0, 0].set(xlabel='Leiden resolution', ylabel='Topic–community AMI', title=f'Graph sensitivity across {sweep.seed.nunique()} seeds')
    axes[0, 0].legend(fontsize=7, ncols=2)
    refits = stability[stability.kind.eq('year_stratified_refit')]
    for count, group in refits.groupby('topic_count'):
        values = group.ami_vs_full_reference.to_numpy()
        axes[0, 1].scatter([count]*len(values), values, alpha=.8)
    axes[0, 1].set(xlabel='NMF topic count', ylabel='AMI vs full-corpus fit', title='Year-stratified refit sensitivity')
    axes[0, 1].set_xticks(sorted(refits.topic_count.unique()))
    metrics = ['degree_centrality', 'betweenness_centrality', 'pagerank', 'k_core']
    for offset, value, label in [(-.08, 'citation_count', 'Raw citations'), (.08, 'normalized_citations', 'Year/source-topic normalized')]:
        selected = [r for r in correlations if r['citation_measure']==value]
        selected = {r['metric']: r for r in selected}
        for i, metric in enumerate(metrics):
            row = selected[metric]
            if row['rho'] is not None:
                lower, upper = row['ci95']
                axes[1, 0].plot([i+offset, i+offset], [lower, upper], color='C0' if offset<0 else 'C1')
                axes[1, 0].scatter(i+offset, row['rho'], color='C0' if offset<0 else 'C1', label=label if i==0 else None)
    if all(row['rho'] is None for row in correlations if row['metric']=='k_core'):
        axes[1, 0].text(3,.07,'constant\n(undefined)',transform=axes[1, 0].get_xaxis_transform(),ha='center',fontsize=8)
    axes[1, 0].axhline(0, color='gray', linewidth=.8)
    axes[1, 0].set_xticks(range(4), ['Degree', 'Betweenness', 'PageRank', 'k-core'])
    axes[1, 0].set(ylabel='Spearman rho and conditional 95% CI', title='Citation count and primary semantic graph position')
    axes[1, 0].legend(fontsize=8)
    largest = temporal.groupby('topic_id').paper_count.sum().nlargest(5).index
    for topic in largest:
        group = temporal[temporal.topic_id.eq(topic)].sort_values('year')
        line = axes[1, 1].plot(group.year, group.topic_share, marker='.', label=f'Topic {topic}')[0]
        axes[1, 1].fill_between(group.year, group.wilson_lower, group.wilson_upper,
                              color=line.get_color(), alpha=.08)
    axes[1, 1].set(xlabel='Publication year', ylabel='Share of this corpus', title='Top five topics; Wilson 95% intervals')
    axes[1, 1].legend(fontsize=8)
    fig.suptitle('ResearchGraph baseline methods study — exploratory', fontsize=13)
    fig.savefig(output/'research_overview.png', dpi=160)
    plt.close(fig)


def analyze(output, papers, embeddings, legacy_graph, config):
    gc, tc, sc = config['graph'], config['topics'], config['statistics']
    seed = config['seed']
    print('Topic coherence and refit sensitivity', flush=True)
    topic_stability, topic_assignments, coherence, models = topic_sensitivity(papers, tc, seed)
    save_table(output, 'topic_stability', topic_stability)
    save_table(output, 'topic_assignments', topic_assignments)
    save_table(output, 'topic_coherence', coherence)
    topic_labels = models[tc['primary_count']]['labels']
    valid_topics = topic_labels>0
    target = len(np.unique(topic_labels[valid_topics]))
    if target < 2:
        raise ValueError('Research alignment needs at least two occupied text topics')
    graphs, graph_edges, partitions, sweep, seed_stability = {}, {}, {}, [], []
    assignments = []
    for k in gc['k_values']:
        for variant in gc['variants']:
            key = (k, variant)
            print(f'Leiden sweep: {variant} k={k}', flush=True)
            edges = knn_edges(embeddings, k, variant, gc['min_similarity'], gc['neighbor_batch_size'])
            graph = graph_from_edges(len(papers), edges, gc['distance_floor'])
            graphs[key], graph_edges[key] = graph, edges
            for resolution in gc['resolutions']:
                labels_by_seed = {}
                for s in gc['seeds']:
                    labels = leiden_partition(graph, resolution, s, gc['leiden_iterations'])
                    partitions[(k, variant, resolution, s)] = labels
                    labels_by_seed[s] = labels
                    sweep.append({'k': k, 'variant': variant, 'resolution': resolution, 'seed': s,
                        'edges': len(edges), 'communities': len(np.unique(labels)),
                        'components': nx.number_connected_components(graph), 'isolates': nx.number_of_isolates(graph),
                        'topic_ami': float(adjusted_mutual_info_score(topic_labels[valid_topics], labels[valid_topics])),
                        'alignment_papers': int(valid_topics.sum())})
                    assignments.extend({'k': k, 'variant': variant, 'resolution': resolution, 'seed': s,
                        'paper_id': paper, 'community': int(label)} for paper,label in zip(papers.paper_id, labels))
                seed_stability.extend(dict(k=k, variant=variant, resolution=resolution, **r)
                                      for r in partition_seed_stability(labels_by_seed))
    sweep = pd.DataFrame(sweep)
    save_table(output, 'graph_sweep', sweep)
    save_table(output, 'community_assignments', pd.DataFrame(assignments))
    save_table(output, 'community_seed_stability', pd.DataFrame(seed_stability))
    comparisons, null_rows, matched, count_sensitivity = [], [], {}, []
    for (k, variant), graph in graphs.items():
        rows = sweep[sweep.k.eq(k) & sweep.variant.eq(variant)].to_dict('records')
        for count, model in models.items():
            valid = model['labels']>0
            chosen = choose_resolution(rows, len(np.unique(model['labels'][valid])))
            labels = partitions[(k, variant, chosen, seed)]
            count_sensitivity.append({'k': k, 'variant': variant, 'topic_count': count,
                'selected_resolution': chosen, 'communities': len(np.unique(labels)),
                'ami': float(adjusted_mutual_info_score(model['labels'][valid], labels[valid]))})
        resolution = choose_resolution(rows, target)
        labels = partitions[(k, variant, resolution, seed)]
        matched[(k, variant)] = (resolution, labels)
        print(f'Alignment null and intervals: {variant} k={k}', flush=True)
        stats, null = alignment_test(topic_labels[valid_topics], labels[valid_topics],
            sc['permutations'], sc['bootstrap_samples'], seed, sc['confidence'])
        comparisons.append(dict(k=k, variant=variant, selected_resolution=resolution,
            target_topics=target, communities=len(np.unique(labels)),
            granularity_gap=abs(len(np.unique(labels))-target), **stats))
        null_rows.extend({'k': k, 'variant': variant, 'permutation': i, 'ami': float(v)} for i,v in enumerate(null))
    # These six p-values are secondary; Holm controls this predeclared family.
    pvalues = np.array([row['permutation_p_one_sided'] for row in comparisons])
    order = np.argsort(pvalues)
    adjusted = np.minimum(1, np.maximum.accumulate((len(pvalues)-np.arange(len(pvalues)))*pvalues[order]))
    for i, p in zip(order, adjusted):
        comparisons[int(i)]['permutation_p_holm_secondary'] = float(p)
    save_table(output, 'alignment_permutation_null', pd.DataFrame(null_rows))
    save_table(output, 'topic_count_alignment_sensitivity', pd.DataFrame(count_sensitivity))
    primary_key = (gc['primary_k'], gc['primary_variant'])
    primary = graphs[primary_key]
    resolution, semantic_labels = matched[primary_key]
    sensitivity = []
    primary_edges = {(i,j) for i,j,_ in graph_edges[primary_key]}
    for key, (_, labels) in matched.items():
        edge_set = {(i,j) for i,j,_ in graph_edges[key]}
        sensitivity.append({'k': key[0], 'variant': key[1],
            'partition_ami_vs_primary': float(adjusted_mutual_info_score(semantic_labels, labels)),
            'edge_jaccard_vs_primary': len(edge_set&primary_edges)/len(edge_set|primary_edges) if edge_set|primary_edges else 1.})
    save_table(output, 'graph_structure_sensitivity', pd.DataFrame(sensitivity))
    print('Corrected centralities and citation normalization', flush=True)
    metrics, centrality_metadata = graph_metrics(primary, seed, gc['exact_betweenness_max_papers'], gc['betweenness_samples'])
    nodes = papers[['paper_id','title','year','citation_count']].copy()
    nodes['topic_id'] = topic_labels
    nodes['community'] = semantic_labels
    for metric, values in metrics.items():
        nodes[metric] = [values[i] for i in range(len(papers))]
    normalization = normalize_citations(papers, sc['min_normalization_cohort'])
    nodes = nodes.merge(normalization.drop(columns=['year','citation_count']), on='paper_id', validate='one_to_one')
    save_table(output, 'graph_nodes', nodes)
    edge_frame = pd.DataFrame([{'source':papers.paper_id.iloc[i], 'target':papers.paper_id.iloc[j],
        'weight':weight, 'distance':max(gc['distance_floor'],1-weight)} for i,j,weight in graph_edges[primary_key]])
    save_table(output, 'semantic_edges', edge_frame)
    correlations = []
    for value in ['citation_count', 'normalized_citations']:
        for metric in metrics:
            correlations.append(dict(citation_measure=value, metric=metric,
                **spearman_interval(nodes[value], nodes[metric], sc['bootstrap_samples'],seed,sc['confidence'])))
    legacy_corrected = legacy_graph.copy()
    for _,_,data in legacy_corrected.edges(data=True):
        data['distance'] = max(gc['distance_floor'],1-data['weight'])
    corrected_legacy_between = nx.betweenness_centrality(legacy_corrected, weight='distance', normalized=True)
    legacy_comparison = {
        'topology':'identical legacy threshold graph; only path distance definition changes',
        'original_similarity_distance_rho':spearman_interval(papers.citation_count, papers.betweenness_centrality,
            sc['bootstrap_samples'],seed,sc['confidence']),
        'corrected_distance_rho':spearman_interval(papers.citation_count,
            [corrected_legacy_between[i] for i in range(len(papers))], sc['bootstrap_samples'],seed,sc['confidence'])}
    print('Citation group effects and Dunn post-hoc comparisons', flush=True)
    group_tests = []
    for value in ['citation_count','normalized_citations']:
        summary, pairs = topic_citation_tests(nodes[nodes.topic_id.gt(0)], value,
            sc['bootstrap_samples'],seed,sc['confidence'])
        group_tests.append(summary)
        save_table(output,f'dunn_{value}',pairs)
    directed_edges, citation_coverage = citation_edges(papers)
    save_table(output,'citation_edges',pd.DataFrame([{'source':papers.paper_id.iloc[i],
        'target':papers.paper_id.iloc[j]} for i,j in directed_edges],columns=['source','target']))
    citation_projection = nx.Graph()
    citation_projection.add_edges_from(directed_edges,weight=1.)
    active = sorted(citation_projection)
    citation_comparison = {'coverage':citation_coverage, 'projection':'undirected binary internal-reference graph',
                           'topic_alignment':None, 'semantic_alignment':None}
    citation_assignments = papers[['paper_id']].copy()
    citation_assignments['citation_community'] = pd.Series(pd.NA,index=range(len(papers)),dtype='Int64')
    if len(active)>1:
        citation_sweep, citation_parts = [], {}
        target_citation_count = len(np.unique(semantic_labels[active]))
        for r in gc['resolutions']:
            for s in gc['seeds']:
                labels = leiden_partition(citation_projection,r,s,gc['leiden_iterations'])
                citation_parts[(r,s)] = labels
                citation_sweep.append({'resolution':r,'seed':s,'communities':len(np.unique(labels))})
        chosen = choose_resolution(citation_sweep,target_citation_count)
        citation_labels = citation_parts[(chosen,seed)]
        citation_assignments.loc[active,'citation_community'] = citation_labels
        citation_comparison.update(selected_resolution=chosen, target_semantic_communities=target_citation_count,
            citation_communities=len(np.unique(citation_labels)),
            granularity_gap=abs(len(np.unique(citation_labels))-target_citation_count),
            connected_components=nx.number_connected_components(citation_projection))
        for name, other in [('semantic',semantic_labels[active]),('topic',topic_labels[active])]:
            mask = np.ones(len(active),dtype=bool) if name=='semantic' else other>0
            stats,null = alignment_test(other[mask],citation_labels[mask],sc['permutations'],
                sc['bootstrap_samples'],seed,sc['confidence'])
            citation_comparison[f'{name}_alignment'] = stats
            save_table(output,f'citation_{name}_null',pd.DataFrame({'permutation':range(len(null)),'ami':null}))
        save_table(output,'citation_resolution_sweep',pd.DataFrame(citation_sweep))
    save_table(output,'citation_assignments',citation_assignments)
    temporal = temporal_prevalence(nodes)
    save_table(output,'topic_year_prevalence',temporal)
    plots(output,sweep,topic_stability,correlations,temporal)
    primary_alignment = next(row for row in comparisons if (row['k'],row['variant'])==primary_key)
    return {'papers':len(papers),'primary_graph':{'k':primary_key[0],'variant':primary_key[1],
        'selected_resolution':resolution,'edges':primary.number_of_edges(),
        'communities':len(np.unique(semantic_labels)), 'components':nx.number_connected_components(primary),
        'isolates':nx.number_of_isolates(primary), 'centrality':centrality_metadata},
        'primary_alignment':primary_alignment,'matched_alignment':comparisons,
        'legacy_alignment':{'ami':float(adjusted_mutual_info_score(papers.topic_id,papers.community)),
            'ari':float(adjusted_rand_score(papers.topic_id,papers.community)),
            'nmi':float(normalized_mutual_info_score(papers.topic_id,papers.community)),
            'communities':int(papers.community.nunique())},
        'primary_ari':float(adjusted_rand_score(topic_labels[valid_topics],semantic_labels[valid_topics])),
        'primary_nmi':float(normalized_mutual_info_score(topic_labels[valid_topics],semantic_labels[valid_topics])),
        'primary_text_partition_ami_vs_legacy':float(adjusted_mutual_info_score(topic_labels,papers.topic_id)),
        'topic_primary_count':tc['primary_count'], 'unassigned_topic_papers':int((~valid_topics).sum()),
        'nonconverged_topic_fits':int((~topic_stability.converged).sum()),
        'citation_normalization_levels':normalization.normalization_level.value_counts().to_dict(),
        'citation_group_tests':group_tests,'citation_centrality_correlations':correlations,
        'legacy_distance_definition_check':legacy_comparison,'citation_view':citation_comparison,
        'limitations':['Exploratory findings on a query-defined recovered corpus, not a representative field sample.',
            'Exact blocked kNN avoids an n-by-n stored matrix but still uses quadratic compute; ANN is deferred.',
            'Resolution is selected by median cluster-count proximity across seeds; count gaps are retained.',
            'Row bootstrap intervals condition on fitted labels, graph and normalization denominators; they ignore network dependence and model refitting.',
            'Year/source-topic cohort normalization is cross-sectional and uses OpenAlex topics as a field proxy.',
            'Internal citation links omit out-of-corpus references; citation alignment excludes zero-incidence papers.',
            'Temporal shares describe this corpus, not publication prevalence in the whole field.',
            'Source text includes short bibliographic abstract fields; topic labels still require human audit.']}


def run(config_path=None, artifacts=None, output_root=None):
    config_path = Path(config_path or ROOT/'config/research.yaml')
    config = yaml.safe_load(config_path.read_text())
    directory, baseline, papers, embeddings, graph = load_run(artifacts)
    if len(papers)>config['max_papers']:
        raise ValueError('Research baseline size guard exceeded; use the later ANN/scaling section')
    required = {'topics','referenced_works','betweenness_centrality'}
    if required-set(papers):
        raise ValueError(f'Missing research metadata: {sorted(required-set(papers))}')
    if (config['graph']['primary_k'] not in config['graph']['k_values']
            or config['graph']['primary_variant'] not in config['graph']['variants']
            or max(config['graph']['k_values']) >= len(papers)):
        raise ValueError('Primary graph must be in the grid and all k values must be below the corpus size')
    if (config['seed'] not in config['graph']['seeds'] or config['seed'] not in config['topics']['seeds']
            or config['topics']['primary_count'] not in config['topics']['counts']):
        raise ValueError('Primary seed and topic count must be present in the sensitivity grids')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    output = Path(output_root or ROOT/config['output_root'])/run_id
    output.mkdir(parents=True,exist_ok=False)
    manifest = {'run_id':run_id,'status':'running','started_at':datetime.now(timezone.utc).isoformat(),
        'python':platform.python_version(),
        'baseline_run':str(directory),'baseline_manifest_sha256':sha256(directory/'manifest.json'),
        'config':config,'config_sha256':sha256(config_path),
        'packages':{name:version(name) for name in ['numpy','pandas','scipy','scikit-learn','networkx',
            'igraph','leidenalg','scikit-posthocs','matplotlib','threadpoolctl']},
        'code_sha256':{str(p.relative_to(ROOT)):sha256(p) for p in sorted((ROOT/'src').rglob('*.py'))}}
    manifest_path = output/'manifest.json'
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
    try:
        with threadpool_limits(limits=1):
            report = analyze(output,papers,embeddings,graph,config)
        (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
        primary = report['primary_graph']
        a = report['primary_alignment']
        (output/'summary.md').write_text(f'''# ResearchGraph Section 4 results

Exploratory methods study on {len(papers)} papers. All configuration, seeds and
source hashes are recorded in the manifest. Original baseline files are preserved.

- Primary graph: {primary['variant']} k={primary['k']}, Leiden resolution {primary['selected_resolution']}.
- {primary['edges']} sparse semantic edges and {primary['communities']} communities.
- Topic/community AMI: {a['ami']:.4f}; conditional 95% interval {a['conditional_paper_bootstrap_ci95']}.
- Permutation null mean: {a['null_mean']:.4f}; excess AMI: {a['excess_over_null_mean']:.4f}.
- Internal citation incidence coverage: {report['citation_view']['coverage']['internal_incidence_fraction']:.1%}.

![Research methods overview](research_overview.png)

See report.json and the Parquet tables for all sweeps, effect sizes, intervals,
Dunn comparisons, cohort fallbacks and citation-view comparisons. These intervals
are conditional descriptive estimates, not proof of causal or population effects.
''')
        if sha256(directory/'manifest.json')!=manifest['baseline_manifest_sha256']:
            raise AssertionError('Baseline changed during research analysis')
        manifest.update(status='complete',finished_at=datetime.now(timezone.utc).isoformat(),
            artifacts={p.name:sha256(p) for p in sorted(output.iterdir()) if p!=manifest_path})
    except Exception as exc:
        manifest.update(status='failed',error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'Research results: {output}',flush=True)
    print(json.dumps({'primary_graph':report['primary_graph'],'primary_alignment':report['primary_alignment']},indent=2))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--artifacts',type=Path)
    parser.add_argument('--output-root',type=Path)
    args = parser.parse_args()
    run(args.config,args.artifacts,args.output_root)


if __name__=='__main__':
    main()
