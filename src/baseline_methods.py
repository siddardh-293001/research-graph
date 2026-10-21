"""Baseline NMF and threshold graph methods; intended for the small corpus."""
import numpy as np
import pandas as pd
import networkx as nx
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS
from sklearn.decomposition import NMF
from sklearn.metrics.pairwise import cosine_similarity
from src.preprocessing import clean_nlp_text

BOILERPLATE = {'conference', 'proceedings', 'association', 'annual', 'meeting',
    'volume', 'chapter', 'paper', 'papers', 'published', 'publication', 'journal',
    'authors', 'author', 'pp', 'pages'}


def fit_topics(papers, config, seed):
    text = (papers.title.str.strip() + '. ' + papers.abstract.str.strip()).map(clean_nlp_text)
    if text.str.len().le(50).any():
        raise ValueError('Baseline NLP requires every embedded paper to have >50 characters of text')
    vectorizer = TfidfVectorizer(stop_words=sorted(set(ENGLISH_STOP_WORDS) | BOILERPLATE),
        ngram_range=(1, 2), min_df=config['min_df'], max_df=config['max_df'], sublinear_tf=True)
    matrix = vectorizer.fit_transform(text)
    model = NMF(n_components=config['count'], init='nndsvda', random_state=seed,
                max_iter=config['max_iter'])
    weights = model.fit_transform(matrix)
    result = papers[['paper_id', 'title', 'year', 'citation_count']].copy()
    result['topic_id'] = weights.argmax(axis=1) + 1
    result['topic_name'] = result.topic_id.map(lambda i: config['labels'].get(i, f'Topic {i}'))
    terms = vectorizer.get_feature_names_out()
    summary = []
    for i, component in enumerate(model.components_):
        top = component.argsort()[::-1][:12]
        summary.append({'topic_id': i + 1, 'top_terms': terms[top].tolist()})
    return result, vectorizer, model, summary


def build_graph(papers, embeddings, config, seed):
    import community as community_louvain
    if len(papers) > config['max_papers']:
        raise ValueError('Baseline graph size guard exceeded; use sparse kNN in section 4')
    if embeddings.ndim != 2 or len(papers) != len(embeddings):
        raise ValueError('Paper and embedding rows must align')
    papers = papers.reset_index(drop=True)
    graph = nx.Graph()
    for i, row in papers.iterrows():
        graph.add_node(i, paper_id=row.paper_id)
    similarity = cosine_similarity(embeddings)
    rows, cols = np.where(np.triu(similarity >= config['threshold'], k=1))
    graph.add_weighted_edges_from((int(i), int(j), float(similarity[i, j])) for i, j in zip(rows, cols))
    partition = (community_louvain.best_partition(graph, weight='weight', random_state=seed,
                  resolution=config['resolution']) if graph.number_of_edges()
                 else {i: i for i in graph})
    # Preserve notebook semantics for comparison; similarity-as-distance is a known
    # legacy limitation to correct and evaluate in section 4.
    metrics = {'degree_centrality': nx.degree_centrality(graph),
               'betweenness_centrality': nx.betweenness_centrality(graph, weight='weight', normalized=True),
               'pagerank': nx.pagerank(graph, weight='weight')}
    nodes = papers[['paper_id', 'title', 'year', 'citation_count']].copy()
    nodes.insert(0, 'node', range(len(nodes)))
    nodes['community'] = [partition[i] for i in graph]
    for name, values in metrics.items():
        nodes[name] = [values[i] for i in graph]
    edges = pd.DataFrame([{'source': graph.nodes[i]['paper_id'],
                          'target': graph.nodes[j]['paper_id'], 'weight': w['weight']}
                         for i, j, w in graph.edges(data=True)], columns=['source', 'target', 'weight'])
    return nodes, edges


def integrate_analysis(papers, topics, nodes):
    columns = ['paper_id', 'community', 'degree_centrality', 'betweenness_centrality', 'pagerank']
    result = topics.merge(nodes[columns], on='paper_id', validate='one_to_one', how='left')
    result = papers[['paper_id']].merge(result, on='paper_id', validate='one_to_one', how='left')
    if result.isna().any().any():
        raise ValueError('Incomplete integrated analysis')
    result['year_median_citations'] = result.groupby('year').citation_count.transform('median')
    result['relative_citations'] = result.citation_count / (result.year_median_citations + 1)
    return result
