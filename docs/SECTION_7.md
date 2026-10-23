# Section 7A: paper evidence and incremental foundations

The local release enriches the existing 20,000-paper snapshot with abstract-only
extractive summaries, authors, keywords, global citation counts, within-corpus
citation context, and directed references/citing-paper navigation. Semantic
neighbors expose cosine similarity, shared terms, community membership and any
recorded citation direction. Similarity is not a citation or evidence of agreement.

Topic discovery now exposes 1,919 positive-score OpenAlex research themes,
separately from the ten fitted NMF topics. These are additional labels on the
existing selective corpus, not evidence of broader collection coverage.

The incremental foundation includes a transactional identity-aware ledger,
idempotent batches, stale-update rejection, retraction handling, bounded neighbor
assignment and Jensen–Shannon distribution drift. A historical 1,200-paper test
used 960 initial and 240 added papers: AMI versus full rebuilding was 0.65394,
new-paper AMI 0.62739 and drift 0.03016 bits. This supports experimentation, not
a claim of equivalent incremental and full communities.

A bounded anonymous candidate collector and daily GitHub workflow are prepared.
They stage at most 500 source rows without credentials or paid fallback. Candidate
collection is not publication: embedding, graph, drift and relevance checks must
pass before promotion. The feed explicitly represents the frozen snapshot.
Scheduling is not operational until the workflow is published and tested.

Tier M (200,000 papers), automatic release promotion and hosted Section 7
verification remain pending. Keep the free hosting plan and original legacy data.
Local targeted evidence is in data/reports/section7.json. Full verification also
runs scripts/check_section7.py and the enriched paper browser scenario.

Full verification passed all 22 checks on the final local implementation.
A real anonymous request staged 100 candidates; first attempt returned HTTP 504.
No live promotion or Tier M claim is made. Portable evidence is under docs/verification/section7-*.json.

## Section 7B: scheduled end-to-end pipeline

The scheduled-atlas workflow polls OpenAlex, arXiv and Crossref every six hours.
It deduplicates observed identities, skips inadequate abstracts, encodes new or
changed text, rebuilds packed BM25 postings and a sparse HNSW neighbor index,
and applies frozen-label topic/community votes. Corrections and observed
retractions are supported; publication-window polling does not discover all
historical corrections or retractions. Supplemental Crossref/arXiv observations
do not overwrite an existing OpenAlex record. arXiv versions share a canonical
ID and unavailable citation counts are distinct from zero.

Each update is an immutable candidate. Promotion requires SQLite and artifact
integrity, grounded summaries, fixed-query relevance within 0.005 of the parent,
ANN recall at least 0.95, isolated serving RSS below 460 MiB, a Linux container
under 512 MiB, and browser tests. Batch drift over 0.1 bits for at least 50 additions is a novelty warning.
Cumulative whole-corpus drift over 0.1 bits from the frozen reference blocks
promotion. Retrieval is checked against both the parent and a frozen initial
reference, preventing small regressions from accumulating across releases. Source failures retain the previous
release. These are engineering gates, not an independent relevance review.

Verified parts are uploaded to a versioned public GitHub release. The serving
supervisor checks the latest release every five minutes, restores and checksums
it in a fresh directory, then restarts one search process. Failed startup restores
the previous local release. GitHub promotion checks the hosted hash, paper count
and search; failure restores the previous release pointer. No Render deployment
secret or paid inference service is needed for data refresh. Code changes still
need a normal verified Render deployment. Free Render idle sleep still applies.

Activation: publish scheduled-atlas.yml, deploy the supervisor, run the workflow
with promotion disabled, inspect its checks, then set the repository Actions
variable ENABLE_AUTO_PROMOTION=true. The workflow uses its short-lived built-in
GitHub token. It retains small verification artifacts for three days. Provider
schedules may be delayed; this is scheduled freshness, not an instant feed.

The live source smoke test returned 236 candidates in three anonymous requests;
218 passed abstract checks. The local 20,218-paper candidate passed 50-query
relevance checks and five browser scenarios; sampled ANN recall was 1.0 and
isolated serving RSS about 284 MiB on macOS. Linux/hosted checks are required
before claiming public activation. Growth is capped at 25,000 served papers
until a separate Tier M capacity evaluation passes. The 200,000-paper tier is
not yet built.

The supervisor path removes the need for a Render deployment credential in
GitHub. GitHub retains its built-in repository token for publishing release
assets. A previously requested RENDER_API_KEY secret is unnecessary for data
refresh. Same-timestamp citation-count changes are accepted without re-encoding
unchanged abstracts; conflicting content at the same timestamp blocks promotion.
