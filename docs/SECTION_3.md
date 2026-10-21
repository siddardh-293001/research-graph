# Section 3 Search and evaluation

The search engine and evaluation runner are implemented and connected to the
analyst dashboard. Run `python -m src.search "your query"`,
`python -m src.evaluation`, or `streamlit run app.py` after a baseline rebuild.

## Retrieval

BM25 indexes title plus abstract, using Unicode word tokens, English stopword
removal, k1=1.5 and b=0.75. IDF uses the positive log1p variant. Query terms are
deduplicated and sorted. There is no stemming or query expansion. The method
accounts for term frequency and document length, following the
[BM25 formulation](https://nlp.stanford.edu/IR-book/html/htmledition/okapi-bm25-a-non-binary-model-1.html).

Dense retrieval uses the baseline run's pinned MiniLM model and exact cosine
similarity over the 767 vectors. Hybrid retrieval combines up to 100 candidates
per channel using `1 / (60 + rank)`, following the
[reciprocal rank fusion paper](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf).
This small-corpus baseline does not use ANN or a cross-encoder reranker.

Both channels rank within the eligible year/topic subset before truncating.
BM25 excludes zero-match papers; hybrid falls back to dense ranking when there
are no lexical matches. Equal scores break ties by paper ID. Dense search can
still return papers for an out-of-domain query; its scores are not calibrated
probabilities of relevance. Requested result count does not change the ranking.

Search results expose BM25 and dense ranks, shared query terms and a short
abstract sentence chosen by lexical overlap. A missing overlap produces no
snippet. These are grounded, deterministic explanations; the sentence is not
claimed to be the best semantic match. Graph neighborhoods remain contextual
visualization rather than an additional ranking signal.

## Benchmark and metrics

The fixed 50-query benchmark contains 77 assistant-authored metadata judgments.
It is provisional and has not received independent relevance review. Its
known-paper construction and incomplete judgments limit what scores establish.
See [benchmark provenance and review instructions](../data/benchmark/README.md).

The evaluator computes nDCG@10 with exponential gain `2^grade - 1` and log2 rank
discount; MRR over each retriever's full returned ranking; and Recall@20 over
known positives. These ranked evaluation measures are described in the
[IR evaluation reference](https://nlp.stanford.edu/IR-book/html/htmledition/evaluation-of-ranked-retrieval-results-1.html).
Hybrid's returned ranking is limited to the union of its two candidate lists.

Unjudged results contribute zero gain for scoring but remain unjudged. Recall is
therefore known-positive recovery, not recall of all relevant literature.
Reports expose the judged fraction of the top 10 so this limitation is visible.
The mean scores have seeded, query-level 95% percentile bootstrap intervals
using 2,000 resamples. Paired bootstrap differences compare hybrid with each
baseline. These intervals do not account for uncertainty or bias in the labels.

Latency measures warm top-20 searches, including query encoding when needed,
ranking, DataFrame materialization and snippets. Index construction and model
loading are excluded and warmup is reported separately. There are 50 latency
observations per method in one local process. This is neither an HTTP latency
measurement nor a concurrent load test. Tier M targets remain untested.

## Measured local results

The successful full verification passed all 37 unit/integration tests, nine
automated dashboard scenarios and the localhost health/page checks. The baseline
rebuild retained 767 papers, 11,064 edges and 124 communities, matching the
previous key artifact hashes. All 16 original processed files were preserved.

These scores use provisional, incomplete seed labels:

| Method | nDCG@10 | MRR | Known-positive Recall@20 | Warm p95 ms |
| --- | --- | --- | --- | --- |
| bm25 | 0.781 | 0.764 | 0.890 | 6.3 |
| dense | 0.763 | 0.739 | 0.900 | 12.6 |
| hybrid | 0.887 | 0.879 | 0.930 | 11.5 |

The machine-readable report includes all confidence intervals and paired
differences. Only about 11–12% of top-10 results have judgments, so the values
are preliminary retrieval diagnostics rather than validated literature-search
performance.

## Outputs and reproduction

Each evaluation writes `data/evaluation/<id>/` containing `report.json`,
`per_query.csv`, `rankings.parquet` and `review_pool.csv`. Reports record the
benchmark hash/version, exact baseline manifest hash, settings, code hashes,
quality metrics, confidence intervals, paired differences and p50/p95 latency.
The CSV review pool preserves unknown labels for later independent assessment.

`python -m src.verify` runs the full implemented project checks and saves a
separate evidence directory under `data/verification/`. It rebuilds the real
baseline, compares key artifacts with the previous run, reruns evaluation,
exercises Streamlit through AppTest and checks a temporary HTTP server. The
HTTP portion requires permission to open a localhost port. A restricted run
that cannot bind a port is marked failed rather than silently skipping it.

## Verification scope and fixes

The dashboard now reads only completed runs with validated checksums and row
alignment. It uses graph node/edge tables instead of legacy pickle files. Its
three ranking modes, topic/year filters, example buttons, paper detail selection,
empty results and graph HTML generation are exercised by automated interactions.
Actual browser canvas interaction is not covered by AppTest.

The broader checks also validate dependency consistency, Python sources and 136
notebook code cells. A missing `embedded_df` definition in the historical
embedding notebook was repaired, and its paper IDs now save as string arrays.
The manual OpenAlex probe no longer issues a request when imported. Audits reject
nonfinite citations and invalid years and flag 12 short abstract fields for
source-quality review without rewriting the baseline.

The GitHub Actions workflow is configured for offline tests and corpus auditing;
it has not been run on GitHub from this workspace. Historical notebook experiments
are preserved and syntax-checked, not re-executed. External ingestion, cloud
deployment, scientific method corrections, ANN scale testing and subsequent
sections remain outside this verification. The original raw source snapshot is
still missing, and independent benchmark review remains the quality gate before
making validated retrieval claims.
