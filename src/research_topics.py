"""NMF coherence and stability across seeds, topic counts and stratified refits."""
import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from sklearn.decomposition import NMF
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS
from sklearn.metrics import adjusted_mutual_info_score
from src.baseline_methods import BOILERPLATE
from src.preprocessing import clean_nlp_text


def fit_text_topics(papers, count, config, seed, training_indices=None):
    text = (papers.title.str.strip()+'. '+papers.abstract.str.strip()).map(clean_nlp_text)
    training_indices = np.arange(len(papers)) if training_indices is None else np.asarray(training_indices)
    if len(training_indices) < count:
        raise ValueError('Too few training papers for requested topic count')
    vectorizer = TfidfVectorizer(stop_words=sorted(set(ENGLISH_STOP_WORDS)|BOILERPLATE),
        ngram_range=(1, 2), min_df=config['min_df'], max_df=config['max_df'], sublinear_tf=True)
    train = vectorizer.fit_transform(text.iloc[training_indices])
    matrix = vectorizer.transform(text)
    if min(train.shape) < count:
        raise ValueError('Too few training features for NMF')
    model = NMF(n_components=count, init='nndsvda', random_state=seed, max_iter=config['max_iter'])
    train_weights = model.fit_transform(train)
    if np.array_equal(training_indices, np.arange(len(papers))):
        weights = train_weights
    else:
        weights = model.transform(matrix)
    labels = weights.argmax(axis=1)+1
    labels[weights.sum(axis=1) == 0] = 0
    feature_names = vectorizer.get_feature_names_out()
    top_indices = [component.argsort()[::-1][:config['top_terms']] for component in model.components_]
    terms = [feature_names[indices].tolist() for indices in top_indices]
    coherence = [document_npmi((matrix[:, indices] > 0).astype(float).toarray()) for indices in top_indices]
    return {'labels': labels, 'terms': terms, 'coherence': coherence,
        'iterations': int(model.n_iter_), 'converged': bool(model.n_iter_ < config['max_iter']),
        'assigned_fraction': float(np.mean(labels>0)), 'training_papers': len(training_indices)}


def document_npmi(binary_columns):
    """Mean pairwise document-level NPMI, not a sliding-window word metric."""
    binary = np.asarray(binary_columns, dtype=float)
    if binary.ndim != 2 or binary.shape[1] < 2 or not len(binary):
        return None
    occurrence = (binary > 0).astype(float)
    probability = occurrence.mean(axis=0)
    joint = occurrence.T@occurrence/len(occurrence)
    scores = []
    for i in range(len(probability)):
        for j in range(i+1, len(probability)):
            if joint[i, j] <= 0:
                scores.append(-1.)
            elif joint[i, j] >= 1:
                scores.append(0.)
            else:
                scores.append(float(np.log(joint[i, j]/(probability[i]*probability[j])) / -np.log(joint[i, j])))
    return float(np.mean(scores))


def matched_term_jaccard(reference, alternative):
    scores = np.zeros((len(reference), len(alternative)))
    for i, a in enumerate(reference):
        for j, b in enumerate(alternative):
            a_set, b_set = set(a), set(b)
            scores[i, j] = len(a_set&b_set)/len(a_set|b_set) if a_set|b_set else 1.
    rows, cols = linear_sum_assignment(-scores)
    return float(scores[rows, cols].mean())


def stratified_indices(papers, fraction, seed):
    if not 0 < fraction <= 1:
        raise ValueError('Invalid topic refit sample fraction')
    rng = np.random.default_rng(seed)
    indices = []
    for _, group in papers.reset_index(drop=True).groupby('year', sort=True):
        n = max(1, int(np.floor(len(group)*fraction)))
        indices.extend(rng.choice(group.index.to_numpy(), n, replace=False).tolist())
    return np.array(sorted(indices), dtype=int)


def topic_sensitivity(papers, config, primary_seed):
    results, assignments, reference_models, coherence_rows = [], [], {}, []
    for count in config['counts']:
        reference = fit_text_topics(papers, count, config, primary_seed)
        reference_models[count] = reference
        for i, (terms, coherence) in enumerate(zip(reference['terms'], reference['coherence']), 1):
            coherence_rows.append({'topic_count': count, 'topic_id': i, 'top_terms': terms,
                                   'document_npmi': coherence})
        for kind in ['full', 'year_stratified_refit']:
            for seed in config['seeds']:
                train = None if kind=='full' else stratified_indices(papers, config['sample_fraction'], seed)
                model = reference if kind=='full' and seed==primary_seed else fit_text_topics(papers, count, config, seed, train)
                valid = (reference['labels']>0) & (model['labels']>0)
                ami = float(adjusted_mutual_info_score(reference['labels'][valid], model['labels'][valid])) if valid.sum()>1 else None
                held_out = np.zeros(len(papers),dtype=bool)
                if train is not None:
                    held_out[:] = True
                    held_out[train] = False
                    held_out &= valid
                held_out_ami = float(adjusted_mutual_info_score(reference['labels'][held_out], model['labels'][held_out])) if held_out.sum()>1 else None
                results.append({'topic_count': count, 'kind': kind, 'seed': seed,
                    'ami_vs_full_reference': ami, 'comparison_papers': int(valid.sum()),
                    'held_out_ami_vs_full_reference': held_out_ami, 'held_out_papers':int(held_out.sum()),
                    'matched_top_term_jaccard': matched_term_jaccard(reference['terms'], model['terms']),
                    'mean_document_npmi': float(np.mean(model['coherence'])),
                    'converged': model['converged'], 'iterations': model['iterations'],
                    'assigned_fraction': model['assigned_fraction'], 'training_papers': model['training_papers']})
                assignments.extend({'topic_count': count, 'kind': kind, 'seed': seed,
                                    'paper_id': paper, 'topic_id': int(label)}
                                   for paper, label in zip(papers.paper_id, model['labels']))
    return pd.DataFrame(results), pd.DataFrame(assignments), pd.DataFrame(coherence_rows), reference_models
