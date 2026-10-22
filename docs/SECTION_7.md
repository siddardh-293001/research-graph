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
