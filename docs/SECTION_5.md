# Section 5: Tier S corpus and ANN retrieval

This section adds a replayable OpenAlex snapshot, shared identity and metadata
transforms, a 20,000-paper corpus, a content-addressed embedding cache, and FAISS
HNSW retrieval. The original 767-paper baseline remains available for comparisons.
The verified run contains 20,000 papers. Its complete self-verification report
is [here](../data/verification/20261021T222919Z-ceedbb86/report.json).

## Collection and replay

```sh
cp .env.example .env  # only if .env does not already exist
# Set OPENALEX_API_KEY in .env, or export it in the environment.
python -m src.ingestion.snapshot
python -m src.tier_s
python -m src.verify
streamlit run app.py
```

The dashboard selects the newest completed Tier S run with passing build gates,
falling back to the baseline when no such run exists. `RESEARCHGRAPH_RUN_DIR`
overrides selection. Search and evaluation CLIs accept `--artifacts /path/to/run`;
their default remains the baseline for reproducible comparisons.

Collection uses a bounded keyword search for retrieval-augmented generation,
large language models and dense retrieval, publication dates 2020-01-01 through
2026-10-22, abstracts present and retractions excluded. Results are citation
sorted. This is a selective API snapshot, not the complete OpenAlex database or
a representative random sample. The complete snapshot alternative is quarterly
and much larger than this tier needs.

The collector freezes up to 30,000 raw records in gzip JSON pages and retains
source cursors, timestamps, counts and SHA-256 checksums. Interrupted collection
resumes from its last committed page. Configuration changes require a new
snapshot directory; changed cached pages fail integrity checks. Retry attempts
count toward both the 400-request and conservative $0.40 cost ceilings. The
estimate is $0.001 per keyword-search call, including failed attempts; actual
account billing is external. No credits are purchased. Requests use a bearer
header, never a key in the saved URL, config or manifest. `.env`, raw snapshots,
run outputs and the embedding cache are ignored by version control.

As checked during implementation, OpenAlex requires a verified free key for
cursor paging after the first page and supports at most 100 records per page.
See [authentication](https://help.openalex.org/api/authentication/),
[paging](https://help.openalex.org/api/paging/), and
[example costs](https://help.openalex.org/access/example-costs/). Collection
requires network access; replay and verification use saved source pages.
Supplied local OpenAlex JSONL/gzip shards can instead be imported with
`python -m src.ingestion.snapshot --snapshot /path/to/shard --output /new/directory`.
Local import uses documented phrase matching rather than reproducing API search.

## Identity, coverage and provenance

The same OpenAlex normalizer feeds raw-page replay. Records without an identity,
title, valid year or nonnegative citation count are rejected, as are retracted
records and new abstracts shorter than 30 words. Nonempty baseline abstracts are
retained to preserve the fixed evaluation corpus; the audit reports short seed
abstracts separately. Legacy seeds without fresh API metadata can have unknown
retraction status; coverage reports that count rather than treating it as a
verified non-retraction.

Union-find merges transitive paper-ID, normalized DOI and recognized arXiv-ID
matches. Recognized arXiv versions collapse to the base identifier. Similar
paper titles and high embedding similarity do not establish identity. A baseline
ID takes precedence as the canonical identifier; otherwise IDs sort
lexicographically. Latest available metadata wins, the longest nonempty abstract
is retained, and missing fields are filled from other versions. Reference lists
are unioned, canonical aliases replace internal version IDs, and self references
are removed. External references are retained. Citation counts are not summed.

All usable baseline identities are selected first, followed by citation-ranked
new identities until 20,000. Coverage tables report exclusions, identifier,
abstract and reference availability, year counts and internal citation coverage.
`identity_aliases.parquet` preserves original-to-canonical IDs. The fixed 50 query
texts remain unchanged; any aliased judgments are mapped to canonical IDs with
the maximum original grade, and the original benchmark hash is retained. Missing
judgment identities fail the build rather than being discarded.

Each run saves source and seed hashes, configuration, source-code hashes, package
versions, model revision, ordered IDs, content hashes and artifact checksums. A
changed source page or misaligned corpus/index fails verification. The embedding
cache key covers exact title/abstract text, model ID, pinned revision and
normalization. Cached vectors must be finite, normalized and 384-dimensional.
Only text and model matches can reuse baseline embeddings; missing embeddings
are encoded locally in resumable batches. The pinned MiniLM model truncates
texts to its supported input length; these are title/abstract embeddings, not
full-paper representations.

## ANN, graph and topics

FAISS `IndexHNSWFlat` uses inner product over normalized 384-dimensional vectors
for cosine retrieval, M=32, efConstruction=200, efSearch=128, seed 42 and one
construction/search thread. Its measured gate is mean strict Recall@10 >=0.95
against exact cosine for both 200 seeded document probes (excluding themselves)
and the 50 natural-language benchmark queries. Curves at efSearch 32, 64 and 128
include tie-aware recall and index-only p50/p95 timings. Exact ties break by row
index; tie-aware recall accepts scores within 1e-6 of the exact boundary.

Search uses a fixed 100 ANN candidates for unfiltered dense ranking; hybrid
fusion uses 100 candidates from each channel. Restrictive year/topic filters
use exact eligible-subset dense search, preserving prefilter correctness.
Evaluation reports warm application search latency including model inference,
BM25 and result explanations, separately from index-only timings. MRR uses at
most 1,000 returned results (100 for unfiltered ANN dense, up to 200 for hybrid).
The 50-query judgments remain provisional and incomplete; new unjudged relevant
papers are not evidence of retrieval failure. Independent review is pending.

The graph is positive-cosine union kNN with k=15, obtained through the ANN index;
no full N-by-N matrix is allocated. Leiden uses seed 42, resolution 1 and four
iterations. PageRank, degree and core numbers are computed on this graph;
weighted betweenness samples 64 sources with distance max(1e-6, 1-cosine).
Near-duplicate candidates with cosine >=0.99 are retained for review; this
neighbor-based list is not an exhaustive semantic duplicate search.

NMF fits 10 topics on a deterministic sample of about 5,000 papers stratified by
year, then transforms the full corpus. Saved vocabulary, IDF, components and fit
IDs make that distinction inspectable. Topic labels show leading terms, rather
than copying baseline human labels. Documents with no fitted vocabulary are
explicitly unassigned. The dashboard's relative citations retain the legacy
citation_count/(year median+1) definition and must not be interpreted as
field-normalized impact. Section 4's full scientific sensitivity study continues
to run on the baseline; those findings are not transferred to Tier S.

FAISS method references: [index types](https://github.com/facebookresearch/faiss/wiki/Faiss-indexes)
and [cosine metrics](https://github.com/facebookresearch/faiss/wiki/MetricType-and-distances).

## Self-verification scope

`python -m src.verify` checks Sections 1–4 again, then verifies every Tier S
artifact and raw-page checksum, identity uniqueness, all benchmark identities,
200 document probes, 50 query vectors and exact-versus-ANN retrieval differences.
It reconstructs the entire ANN index and requires byte-identical serialization,
and cold-encodes eight spread-out paper texts using the pinned model. It repeats
the full 50-query benchmark, tests dashboard interactions and checks localhost
HTTP health for both baseline and Tier S. Legacy files must remain unchanged.
Source/configuration changes during verification fail the run.

Verification does not recollect the changing external source, re-embed all
20,000 documents, re-execute historical notebooks, assess concurrent production
load, inspect the browser canvas visually, deploy publicly or perform Sections
6–8. These limits are explicit in its saved report.

## Measured Tier S run

Run `20261021T222745Z-c7ae235e` was built from 30,000 frozen OpenAlex records
(300 requests; estimated request cost $0.315 under the configured estimate).
The selected 20,000 papers contain 766 of the 876 seed rows as usable unique
identities; the other seed rows were missing abstracts or merged into duplicate
identities. DOI coverage is 99.94%, recognized arXiv coverage 38.73%, and
reference-list coverage 83.53%. Retraction status is unknown for 335 papers,
mostly because their identity came from the recovered seed corpus. The selected
corpus is citation-ranked and strongly concentrated in 2023–2025, so its scores
do not estimate performance on all AI research.

At the configured `efSearch=128`, HNSW achieved Recall@10 of 1.000 on 200
document probes and 0.996 on the 50 benchmark query vectors. The index is
36,158,306 bytes; construction took 3.47 seconds. Repeated verification measured
index-only p50/p95 search at 0.21/0.34 ms for document probes and 0.21/0.31 ms
for query vectors. These are single-thread local index timings, not service
latency. The exact and ANN top-20 benchmark rankings had zero mean difference in
nDCG@10 and Recall@20 for dense and hybrid retrieval in this run.

The repeated provisional benchmark scored BM25 nDCG@10 0.708 (95% bootstrap
interval 0.604–0.809), dense 0.618 (0.516–0.712), and hybrid 0.772
(0.679–0.855). Known-positive Recall@20 was 0.84, 0.84, and 0.86 respectively.
Only 9.6–10.6% of top-ten results were judged. These results remain provisional
until independent relevance review. Warm application p95 latency was 8.3 ms for
BM25, 16.4 ms dense, and 13.3 ms hybrid over 50 queries; it excludes concurrent
load and network service overhead.

The graph contains 232,552 union-kNN edges and 23 Leiden communities. Ten NMF
topics were fitted on 5,001 year-stratified papers and assigned across the full
corpus. The run has 83 near-neighbor pairs at cosine >=0.99; these are review
candidates, not confirmed duplicates. All 22 run artifacts passed checksums,
the FAISS index rebuilt byte-identically, eight cold embedding checks matched
the stored vectors, filtered dense results matched exact search, and both Tier S
dashboard and HTTP checks passed. The full verification passed all 17 recorded
checks and preserved all 16 legacy processed artifacts.
