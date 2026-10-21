# ResearchGraph section by section build plan

The v3 project profile is the requirements reference. Targets in it are goals to
measure, not achieved performance. The active workspace was restored from
`/Users/siddhu/Desktop/Projects/researchgraph`; the source copy is untouched.

| Section | Deliverable | Completion gate | Status |
| --- | --- | --- | --- |
| 1. Local foundation | Restore baseline, configuration, identity helpers, corpus audit, tests, setup instructions | Existing corpus passes offline integrity checks; tests pass | Initial foundation implemented |
| 2. Reproducible baseline | Move notebook cleaning, embeddings, topics and graph steps into pipeline modules; record seeds and model/run provenance | One command rebuilds the baseline from source metadata; recover the missing raw snapshot or explicitly establish a replacement | Complete using recovered metadata; see SECTION_2.md |
| 3. Search and evaluation | Fixed 50-query labelled benchmark, BM25 and dense baselines, hybrid ranking and filters | nDCG@10, MRR and Recall@20 with bootstrap intervals; measured latency | Implemented and measured; independent relevance review pending |
| 4. Research methods | Sparse kNN graph, seeded Leiden resolution sweeps, topic stability, matched-granularity AMI with permutation null, age-normalized citation analysis | Reproducible metrics and sensitivity checks; exploratory baseline numbers re-tested | Implemented; see SECTION_4.md for measured limitations |
| 5. Tier S corpus | Shared ingestion transforms, DOI/arXiv identity, reference retention, source snapshots, ANN at about 20k papers | Provenance, coverage, ANN recall and latency measured; benchmark repeated | Complete; 20k run and Sections 1–5 self-verification passed; independent relevance review pending |
| 6. Public demo | FastAPI, public interface, analyst dashboard, containers, Terraform, CI/CD, free-plan quota alerts | Working public URL, reproducible Tier S results and measured operating cost | Implemented locally; free Render publication and hosted checks in progress; see SECTION_6.md |
| 7. Live updates and Tier M | Scheduled ingestion, incremental assignments, live feed, drift monitoring, about 200k papers | Measure freshness, p95 latency, cost and incremental-vs-full AMI | Pending |
| 8. Tier L and report | 1M+ papers, sampled analyses, aggregate maps, scaling curves and technical report | Prior tier gates pass; quality and cost justify expansion | Pending |

Grounded Q&A, accounts and research-gap maps remain stretch work after the core
sections. The immediate milestone is a validated baseline, followed by a measured
Tier S demo. Each section ends with evidence and a review before proceeding.

The user requested self-verification at the end of Section 6 and every subsequent
section. Extend `src.verify` for each new section, run the relevant full checks,
record limitations, and update the repository after verified additions. The
repository is `https://github.com/siddardh-293001/research-graph`. The user's
hosting policy is free plans only, with no paid credits or plan upgrades.

## Section 1 scope and remaining limits

The audit verifies schema, unique IDs, nonempty titles/abstracts, valid citation
counts, finite nonzero embeddings, embedding ID order and analysis ID order. It
records input hashes and the configured model name. The model name comes from
the existing notebook and is not independent proof of embedding provenance.

Identity helpers normalize DOI URLs and collapse transitive paper-ID/DOI matches,
keeping the first input record. They do not merge metadata, resolve arXiv
versions, or infer identity from titles. Original stored data is not rewritten.
The legacy embedding-ID NumPy object array was converted once from the trusted
local baseline to `embedded_paper_ids_safe.npy`, a string array. The audit loads
this copy with pickle disabled and preserves the original artifact.

The restored clean table and embedded table have different sizes; that difference
must be explained by the extracted preprocessing pipeline in section 2. The raw
`data/processed/papers.parquet` expected by the ingestion notebook was not in the
previous project copy. Existing graph pickle files are trusted local legacy
artifacts; replace them with explicit edge tables during pipeline extraction.
No cloud deployment, API ingestion or model download is performed in section 1.

Section 2 now provides an explicit replacement input and a one-command rebuild;
the original raw snapshot remains unavailable. See [Section 2](SECTION_2.md).
