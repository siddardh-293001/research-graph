# Section 7: scheduled research atlas and Tier M

Verified scheduled updates are operational. The first successful production run
40108517452 published atlas-6371c9e9639a6c36 and the free Render host adopted its
exact SHA-256 6371c9e9639a6c362b89bd322ac4463a9cef550499adc5b505ded5d7a2dd0a1f:
20,217 papers, up from the bundled 20,000-paper seed. Repository Actions variable
ENABLE_AUTO_PROMOTION is true. The workflow runs every six hours; provider
scheduling and source indexing delays apply.

The pipeline polls OpenAlex, arXiv and Crossref anonymously, stages bounded
candidates, deduplicates DOI/arXiv/OpenAlex identities, skips inadequate abstracts,
encodes new/changed text and rebuilds BM25, HNSW and sparse neighbors. Frozen
community/topic labels use provisional neighbor votes. Observed corrections and
retractions are supported; publication-window polling misses historical changes.
Missing citation counts are distinct from zero. No paid inference is used.

Promotion requires artifact/SQLite integrity, grounded summaries, a fixed
50-query benchmark against both parent and frozen initial reference (maximum
0.005 metric regression), ANN Recall@10 >=0.95, isolated serving RSS <=460 MiB,
a Linux container limited to 512 MiB and eleven browser scenarios. Batch topic
drift above 0.1 bits is a novelty warning; cumulative corpus drift above 0.1 bits
from the frozen reference blocks promotion. Provisional labels still need
independent relevance review.

The production candidate measured ANN recall 1.0, Linux serving RSS 371.04 MiB,
and no benchmark regression: hybrid nDCG@10 increased about 0.00195. Source
metadata and corpus coverage are selective; these engineering checks do not
establish complete coverage or research quality.

Versioned public GitHub release assets are checksummed and restored into a new
directory. A single-process supervisor polls every five minutes, restarts search
for a new release, and restores its previous local release on failed startup.
GitHub promotion verifies hosted hash/count/search and restores the previous
release pointer on failure. Brief HTTP unavailability during restart was observed;
this is not zero-downtime hosting. Free Render idle sleep still applies.

The first promotion (40107116914) failed hosted adoption and rolled back. The
fetch path now includes a validated public GitHub latest-release redirect when
anonymous REST requests receive 403/429, and HTTP status diagnostics. The second
production run completed successfully, including hosted adoption. No Render API
key is needed for data updates. Code changes still need a normal deployment.

The enriched paper interface includes abstract summaries, source authors and
keywords, global citation counts, corpus citation context, directed references,
semantic connections and 1939 multi-label OpenAlex themes. Review tools and
limits are detailed in FEATURE_EXPANSION.md.

Verification evidence: docs/verification/automatic-updates.json and the release's
verification.json. Ten of eleven hosted browser scenarios passed initially; one
fixture download exceeded 10 seconds despite HTTP 200 and passed unchanged on
recheck. Sampled host memory was about 268 MiB under the 512 MiB limit; this is
not a sustained-load peak. Six sequential warm search requests are recorded in
data/reports/live-update-http.json.

## Remaining Tier M work

The serving cap remains 25,000 papers. The 200,000-paper collection, embedding,
indexing, memory/performance capacity tests and incremental-vs-full comparison
are not complete. No paid compute, disks, subscriptions or API credits are
authorized. The historical 1,200-paper incremental experiment measured overall
AMI 0.65394 and new-paper AMI 0.62739; it does not establish equivalent full and
incremental communities at Tier M. Section 7 as a whole remains incomplete until
those capacity and research gates pass. Preserve the original legacy artifacts.
