# ResearchGraph

ResearchGraph explores AI literature through text topics, semantic similarity
and citation relationships. The restored Streamlit prototype is the starting
point for the staged v3 build. See [the section plan](docs/BUILD_PLAN.md) for
deliverables and completion gates.

## Setup

Use Python 3.11 or newer in a virtual environment:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Section 1 verification

Run from the repository root:

```sh
python -m unittest discover -s tests -v
python -m src.audit
```

The audit reads `config/project.yaml`, checks the existing local corpus and
embedding alignment, writes `data/reports/baseline_audit.json` with SHA-256 hashes,
and exits nonzero on integrity errors. It requires no network or model download.

## Section 2 baseline rebuild

```sh
python -m src.pipeline
```

This rebuilds cleaning, embeddings, NMF topics, threshold graph, seeded Louvain
communities, centralities and integrated analysis from frozen recovered metadata.
Configuration is in `config/baseline.yaml`. Each run writes a new
`data/runs/<run-id>/` directory; legacy dashboard artifacts are preserved.

The pinned embedding revision is loaded from the existing Hugging Face cache on
CPU. On a new machine, populate that model revision's cache first or set
`embedding.local_files_only: false` in the configuration to permit its download.
No OpenAlex request is needed for a baseline rebuild.

Outputs include metadata, embeddings, safe string IDs, graph node/edge Parquet
tables, topic assignments and numerical model state, integrated analysis, audit,
comparison metrics and a manifest. The manifest records source recovery history,
configuration, model revision, code and output hashes, package versions and run
status. See [Section 2 notes](docs/SECTION_2.md) for results and limitations.

## Search and evaluation

```sh
python -m src.search "graph retrieval for multi hop reasoning" --mode hybrid --top-k 10
python -m src.search "clinical question answering" --year-min 2024 --topic 7
python -m src.evaluation
```

BM25, exact dense retrieval and hybrid reciprocal rank fusion share one engine.
Year and topic filters apply before ranking. Results include channel ranks,
shared terms and an abstract sentence selected by lexical overlap. BM25 runs
without loading an embedding model. Search settings live in `config/search.yaml`.

Evaluation uses a fixed 50-query seed benchmark with 77 graded judgments. These
are assistant-authored from local metadata and await independent review. Scores
are provisional; the labels are incomplete. Reports include nDCG@10, MRR,
known-positive Recall@20, bootstrap intervals, paired differences, warm latency,
saved rankings and a CSV review pool. See [Section 3](docs/SECTION_3.md).

## Section 4 research methods

```sh
python -m src.research
```

This studies sparse union/mutual kNN graphs, seeded Leiden resolutions, NMF
coherence and refit stability, near-matched-granularity AMI with permutation nulls,
cohort-normalized citations, effect sizes and Dunn post-hoc tests. It also compares
semantic and internal citation communities and corrects betweenness path distances.
Settings live in `config/research.yaml`. Tables, figures and a provenance manifest
are written to `data/research/<run-id>/`; the dashboard's baseline is preserved.
These are exploratory measurements on the recovered 767-paper corpus. See
[Section 4 methods and limitations](docs/SECTION_4.md).

## Full automated verification

```sh
python -m src.verify
```

This checks dependencies, unit and integration tests, Python and notebook syntax,
the old corpus, a real baseline rebuild, artifact integrity, retrieval evaluation,
Section 4's full research study, Tier S provenance and ANN reconstruction,
the repeated 50-query benchmark, dashboard interactions and temporary localhost
HTTP servers for both corpora. Build Tier S before running full verification. It writes a report
and logs under `data/verification/`. The embedding model must already be cached,
and the HTTP check requires permission to bind a local port. No cloud deployment
or external source collection is performed. Historical notebooks are syntax
checked; their experiments are not re-executed by this command.

## Analyst dashboard

```sh
streamlit run app.py
```

Run the baseline or Tier S pipeline first. The dashboard prefers the newest
completed Tier S run with passing gates, then falls back to the newest baseline. It
verifies its checksums and paper order, and reads graph node/edge Parquet tables.
Set `RESEARCHGRAPH_RUN_DIR` to select a specific run. It offers ranking modes,
year and topic filters, explanations, paper details and a local graph. The query
model uses that run's pinned revision and cache settings. Automated interactions
cover each ranking mode, filters, examples and empty results.

## Layout

- `app.py`: restored Streamlit analyst dashboard.
- `src/ingestion/`: bounded cursor snapshots, replay and shared OpenAlex normalization.
- `src/corpus.py`: shared DOI and paper identity handling.
- `src/audit.py`: offline corpus integrity command.
- `src/search.py`: shared retrieval engine and search CLI.
- `src/evaluation.py`: fixed-query metrics, intervals, timings and review exports.
- `src/artifacts.py`: validated run and graph loading.
- `src/verify.py`: full verification command.
- `data/benchmark/`: fixed provisional queries and graded judgments.
- `config/project.yaml`: baseline paths, seed, tier and configured model.
- `notebooks/`: original exploratory analyses.
- `tests/`: offline foundation tests.
- `data/processed/`: restored baseline artifacts.

The legacy OpenAlex smoke script makes network requests when executed; use
`src.ingestion.snapshot` for the bounded authenticated Section 5 collector. The original raw ingestion snapshot is missing; Section 2 rebuilds from
a frozen replacement recovered from surviving cleaned metadata. A rebuild from
the original raw API responses is unavailable. Existing scientific results remain
exploratory until the evaluation sections are complete.

## Section 5: 20,000-paper Tier S

Store a verified `OPENALEX_API_KEY` in `.env` (see `.env.example`), then run:

```sh
python -m src.ingestion.snapshot
python -m src.tier_s
python -m src.verify
streamlit run app.py
```

The collector saves resumable raw pages with a conservative $0.40 request budget.
The builder preserves benchmark identities, caches pinned embeddings, measures
HNSW recall against exact cosine, and produces a sparse Leiden graph and sampled
NMF topics. The default dashboard adopts a completed Tier S run whose build gates
passed. See [Section 5 methods, commands and limitations](docs/SECTION_5.md).

## Section 6: public app and free hosting

```sh
python scripts/prepare_release.py
cd web && npm ci && npm run build && cd ..
python -m uvicorn src.api:app --host 127.0.0.1 --port 8000 --no-access-log
```

Open http://127.0.0.1:8000 for the React interface or `/api/docs` for the FastAPI
contract. The memory-bounded server uses the same frozen Tier S corpus and
ranking methods, read-only SQLite metadata, FAISS and a verified ONNX copy of
the pinned MiniLM model. The measured 50-query comparison preserved retrieval
results. The research and Streamlit environments remain available separately.

The deployment targets Render's free compute plan; `render.yaml`, `Dockerfile`,
the manual GitHub Actions deployment and `infra/render` implement that policy.
No paid service or inference credits are required. The user confirmed a Render
workspace without a payment method so usage-limit exhaustion suspends instead
of charging overages. Free instances sleep when idle. See
[Section 6](docs/SECTION_6.md) for setup, measured limits and the public-URL gate.

`python -m src.verify` now also checks release parity, serving memory, actual
HTTP, infrastructure configuration and desktop/mobile Chromium behavior. Install
the browser once with `cd web && npx playwright install chromium`. Terraform and
the cached official Render schema are required for infrastructure validation.
Subsequent sections will extend and run self-verification before completion.
