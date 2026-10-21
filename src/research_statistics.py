"""Exploratory statistical analyses with explicit resampling and cohort rules."""
from itertools import combinations
import warnings
import numpy as np
import pandas as pd
from scipy.stats import bootstrap, kruskal, spearmanr
from sklearn.metrics import adjusted_mutual_info_score


def percentile_interval(values, confidence=.95):
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    alpha = (1-confidence)/2
    return np.quantile(values, [alpha, 1-alpha]).tolist() if len(values) else [None, None]


def alignment_test(a, b, permutations=199, bootstraps=300, seed=42, confidence=.95):
    a, b = np.asarray(a), np.asarray(b)
    if a.ndim != 1 or a.shape != b.shape or len(a) < 2 or permutations < 1 or bootstraps < 1:
        raise ValueError('Alignment requires equal nonempty label arrays and resamples')
    rng = np.random.default_rng(seed)
    observed = float(adjusted_mutual_info_score(a, b))
    null = np.array([adjusted_mutual_info_score(a, rng.permutation(b)) for _ in range(permutations)])
    # AMI can have appreciable finite-sample bootstrap bias. BCa adjusts for
    # bias and jackknife acceleration; this remains conditional on fitted labels.
    with warnings.catch_warnings(record=True) as notices:
        result = bootstrap((a,b), lambda x,y: adjusted_mutual_info_score(x,y),
            paired=True, vectorized=False, method='BCa', n_resamples=bootstraps,
            confidence_level=confidence, rng=rng, batch=32)
    interval = [float(result.confidence_interval.low), float(result.confidence_interval.high)]
    ci_method = 'paired paper BCa bootstrap conditional on fitted partitions'
    if not np.isfinite(interval).all():
        if np.ptp(result.bootstrap_distribution)<1e-12:
            interval = [float(result.bootstrap_distribution[0])]*2
            ci_method = 'degenerate empirical bootstrap; no measured conditional variation'
        else:
            interval = [None,None]
            ci_method = 'BCa interval undefined; inspect the saved warnings'
    return {'ami': observed, 'conditional_paper_bootstrap_ci95': interval, 'ci_method': ci_method,
        'interval_excludes_point_estimate': bool(interval[0] is not None and not interval[0]<=observed<=interval[1]),
        'bootstrap_warnings': sorted(set(str(n.message) for n in notices)),
        'null_mean': float(null.mean()), 'null_interval95': percentile_interval(null, confidence),
        'excess_over_null_mean': observed-float(null.mean()),
        'permutation_p_one_sided': float((1+np.count_nonzero(null >= observed))/(permutations+1)),
        'permutations': permutations, 'bootstraps': bootstraps, 'n': len(a)}, null


def source_topic(topics):
    valid = [t for t in topics if t and t.get('id')] if topics is not None else []
    if not valid:
        return 'unknown'
    return str(max(valid, key=lambda t: (float(t.get('score') or 0), str(t['id'])))['id'])


def normalize_citations(papers, minimum=5):
    """Citations / mean in source-topic x year; fall back to year, then corpus."""
    if minimum < 1:
        raise ValueError('Minimum cohort must be positive')
    result = papers[['paper_id', 'year', 'citation_count']].copy()
    if result.citation_count.lt(0).any() or not np.isfinite(result.citation_count).all():
        raise ValueError('Citation counts must be finite and nonnegative')
    result['source_topic_id'] = papers.topics.map(source_topic).to_numpy()
    detailed = result.groupby(['year', 'source_topic_id']).citation_count
    result['cohort_size'] = detailed.transform('size')
    result['cohort_mean_citations'] = detailed.transform('mean')
    result['normalization_level'] = 'source_topic_year'
    year_stats = result.groupby('year').citation_count
    fallback = result.cohort_size.lt(minimum) | result.source_topic_id.eq('unknown')
    result.loc[fallback, 'cohort_size'] = year_stats.transform('size')[fallback]
    result.loc[fallback, 'cohort_mean_citations'] = year_stats.transform('mean')[fallback]
    result.loc[fallback, 'normalization_level'] = 'year'
    small = result.cohort_size.lt(minimum)
    result.loc[small, 'cohort_size'] = len(result)
    result.loc[small, 'cohort_mean_citations'] = result.citation_count.mean()
    result.loc[small, 'normalization_level'] = 'corpus'
    denominator = result.cohort_mean_citations.to_numpy()
    result['normalized_citations'] = np.divide(result.citation_count.to_numpy(dtype=float), denominator,
        out=np.zeros(len(result)), where=denominator > 0)
    return result


def spearman_interval(x, y, bootstraps=300, seed=42, confidence=.95):
    x, y = np.asarray(x), np.asarray(y)
    if x.shape != y.shape or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('Correlation requires paired finite arrays')
    if len(x) < 3 or len(np.unique(x)) < 2 or len(np.unique(y)) < 2:
        return {'rho': None, 'ci95': [None, None], 'n': len(x), 'reason': 'constant or insufficient data'}
    rho = float(spearmanr(x, y).statistic)
    rng = np.random.default_rng(seed)
    boot = []
    for _ in range(bootstraps):
        idx = rng.integers(len(x), size=len(x))
        if len(np.unique(x[idx])) > 1 and len(np.unique(y[idx])) > 1:
            boot.append(float(spearmanr(x[idx], y[idx]).statistic))
    return {'rho': rho, 'ci95': percentile_interval(boot, confidence), 'n': len(x),
            'valid_bootstraps': len(boot)}


def cliffs_delta(a, b):
    a, b = np.asarray(a), np.sort(np.asarray(b))
    if not len(a) or not len(b):
        raise ValueError('Cliff delta requires two nonempty groups')
    return float(np.sum(np.searchsorted(b, a, side='left') -
                        (len(b)-np.searchsorted(b, a, side='right')))/(len(a)*len(b)))


def eta_squared_h(groups):
    if len(groups) < 2 or sum(map(len, groups)) <= len(groups):
        return None, None, None
    if len(np.unique(np.concatenate(groups))) == 1:
        return 0., 1., 0.
    h, p = kruskal(*groups)
    effect = max(0., min(1., (float(h)-len(groups)+1)/(sum(map(len, groups))-len(groups))))
    return float(h), float(p), effect


def topic_citation_tests(frame, value='normalized_citations', bootstraps=300, seed=42, confidence=.95):
    import scikit_posthocs as sp
    grouped = {int(label): group[value].to_numpy(dtype=float) for label, group in frame.groupby('topic_id')}
    h, p, effect = eta_squared_h(list(grouped.values()))
    rng = np.random.default_rng(seed)
    effect_boot = [eta_squared_h([rng.choice(v, len(v), replace=True) for v in grouped.values()])[2]
                   for _ in range(bootstraps)] if effect is not None else []
    summary = {'value': value, 'kruskal_h': h, 'p_secondary': p, 'eta_squared_h': effect,
        'effect_formula': 'max(0, min(1, (H - k + 1)/(N - k)))',
        'eta_squared_h_ci95': percentile_interval(effect_boot, confidence),
        'group_sizes': {str(k): len(v) for k, v in grouped.items()},
        'small_groups_under_5': [k for k, v in grouped.items() if len(v)<5]}
    if len(grouped) < 2:
        return summary, pd.DataFrame()
    if len(np.unique(frame[value])) == 1:
        adjusted = pd.DataFrame(1., index=grouped, columns=grouped)
    else:
        adjusted = sp.posthoc_dunn(frame, val_col=value, group_col='topic_id', p_adjust='holm')
    pairs = []
    for a, b in combinations(sorted(grouped), 2):
        x, y = grouped[a], grouped[b]
        delta_boot = [cliffs_delta(rng.choice(x, len(x), replace=True), rng.choice(y, len(y), replace=True))
                      for _ in range(bootstraps)]
        lower, upper = percentile_interval(delta_boot, confidence)
        pairs.append({'topic_a': a, 'topic_b': b, 'dunn_p_holm': float(adjusted.loc[a, b]),
            'cliffs_delta_a_minus_b': cliffs_delta(x, y), 'delta_ci_lower': lower, 'delta_ci_upper': upper,
            'n_a': len(x), 'n_b': len(y)})
    return summary, pd.DataFrame(pairs)


def temporal_prevalence(frame):
    counts = frame.groupby(['year', 'topic_id']).size()
    years = sorted(frame.year.unique())
    topics = sorted(frame.topic_id.unique())
    rows = []
    z = 1.959963984540054
    for year in years:
        n = int(frame.year.eq(year).sum())
        for topic in topics:
            count = int(counts.get((year, topic), 0))
            p = count/n
            center = (p+z*z/(2*n))/(1+z*z/n)
            half = z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
            rows.append({'year': int(year), 'topic_id': int(topic), 'paper_count': count,
                'year_total': n, 'topic_share': p, 'wilson_lower': max(0., center-half),
                'wilson_upper': min(1., center+half)})
    return pd.DataFrame(rows)
