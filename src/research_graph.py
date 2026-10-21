"""Sparse graph construction and reproducible Leiden community analysis."""
import numpy as np
import networkx as nx
from sklearn.metrics import adjusted_mutual_info_score


def knn_edges(embeddings, k, variant='union', min_similarity=0., batch_size=128):
    """Exact blocked cosine kNN: O(n*k) output, O(batch*n) score memory.

    Both directions must select an edge in mutual mode; either suffices in
    union mode. Only positive similarities are used. This is not an ANN index.
    Ties break by row index, and self matches are explicitly removed.
    """
    x = np.asarray(embeddings)
    if (x.ndim != 2 or not np.isfinite(x).all() or len(x) < 2
            or np.any(np.linalg.norm(x, axis=1) == 0)):
        raise ValueError('Expected at least two finite nonzero embedding rows')
    if type(k) is not int or not 1 <= k < len(x) or variant not in {'union', 'mutual'}:
        raise ValueError('Invalid k or graph variant')
    if not 0 <= min_similarity < 1 or batch_size < 1:
        raise ValueError('Invalid similarity floor or batch size')
    x = x / np.linalg.norm(x, axis=1, keepdims=True)
    selected = {}
    indices = np.arange(len(x))
    for start in range(0, len(x), batch_size):
        scores = np.clip(x[start:start+batch_size] @ x.T, -1., 1.)
        for offset, row in enumerate(scores):
            i = start + offset
            order = np.lexsort((indices, -row))
            neighbors = order[(order != i) & (row[order] > min_similarity)][:k]
            for j in neighbors:
                selected[(i, int(j))] = float(row[j])
    edges = []
    for (i, j), weight in sorted(selected.items()):
        if variant == 'mutual' and (j, i) not in selected:
            continue
        if i < j or (j, i) not in selected:
            a, b = sorted((i, j))
            edges.append((a, b, weight))
    return sorted(edges)


def graph_from_edges(n, edges, distance_floor=1e-6):
    if distance_floor <= 0:
        raise ValueError('Distance floor must be positive')
    graph = nx.Graph()
    graph.add_nodes_from(range(n))
    for i, j, weight in edges:
        if i == j or not (0 <= i < n and 0 <= j < n) or not np.isfinite(weight) or not 0 < weight <= 1.000001:
            raise ValueError('Invalid similarity edge')
        graph.add_edge(i, j, weight=float(weight), distance=max(distance_floor, 1-float(weight)))
    return graph


def leiden_partition(graph, resolution=1., seed=42, iterations=4):
    import igraph as ig
    import leidenalg as la
    if resolution <= 0 or iterations < 1:
        raise ValueError('Invalid Leiden parameters')
    order = sorted(graph.nodes())
    lookup = {node: i for i, node in enumerate(order)}
    if not graph.number_of_edges():
        return np.arange(len(order))
    edges = sorted(graph.edges(data=True))
    igraph = ig.Graph(n=len(order), edges=[(lookup[i], lookup[j]) for i, j, _ in edges], directed=False)
    weights = [float(data.get('weight', 1.)) for _, _, data in edges]
    partition = la.find_partition(igraph, la.RBConfigurationVertexPartition, weights=weights,
        resolution_parameter=float(resolution), seed=int(seed), n_iterations=int(iterations))
    # Canonical IDs order communities by the first node, so label IDs are stable.
    communities = sorted((sorted(c) for c in partition), key=lambda c: c[0])
    labels = np.zeros(len(order), dtype=int)
    for label, community in enumerate(communities):
        labels[community] = label
    return labels


def choose_resolution(rows, target_count):
    """Use median occupied community count over seeds, never topic alignment."""
    grouped = {}
    for row in rows:
        grouped.setdefault(row['resolution'], []).append(row['communities'])
    if not grouped or target_count < 1:
        raise ValueError('Resolution selection needs partitions and a positive target')
    return min(grouped, key=lambda r: (abs(float(np.median(grouped[r])) - target_count), r))


def graph_metrics(graph, seed=42, exact_max=2000, sample_size=256):
    n = len(graph)
    sampled = n > exact_max
    between = nx.betweenness_centrality(graph, weight='distance', normalized=True,
        k=min(sample_size, n) if sampled else None, seed=seed)
    return {'degree_centrality': nx.degree_centrality(graph),
        'betweenness_centrality': between, 'pagerank': nx.pagerank(graph, weight='weight'),
        'k_core': nx.core_number(graph)}, {'betweenness_method': 'sampled' if sampled else 'exact',
        'betweenness_samples': min(sample_size, n) if sampled else n,
        'distance_definition': 'max(distance_floor, 1 - cosine_similarity)'}


def citation_edges(papers):
    """Retain directed internal references; never invent missing reference links."""
    lookup = {paper: i for i, paper in enumerate(papers.paper_id)}
    edges = set()
    total, external, self_edges = 0, 0, 0
    for i, references in enumerate(papers.referenced_works):
        for reference in (() if references is None else references):
            total += 1
            j = lookup.get(reference)
            if j is None:
                external += 1
            elif j == i:
                self_edges += 1
            else:
                edges.add((i, j))
    active = {i for edge in edges for i in edge}
    return sorted(edges), {'reference_entries': total, 'external_reference_entries': external,
        'self_reference_entries': self_edges, 'internal_directed_edges': len(edges),
        'papers_with_internal_citation_incidence': len(active),
        'internal_incidence_fraction': len(active)/len(papers) if len(papers) else 0.}


def partition_seed_stability(labels_by_seed):
    seeds = sorted(labels_by_seed)
    return [{'seed_a': a, 'seed_b': b,
             'ami': float(adjusted_mutual_info_score(labels_by_seed[a], labels_by_seed[b]))}
            for i, a in enumerate(seeds) for b in seeds[i+1:]]
