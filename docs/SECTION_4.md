# Section 4 Research methods and sensitivity

Run `python -m src.research` after the baseline pipeline. The method study reads
one validated, completed baseline run and writes a new `data/research/<run-id>/`
directory. It does not replace the baseline dashboard's graph or original data.
Use `--artifacts PATH` to select a baseline and `--config PATH` for an explicitly
versioned experiment. `config/research.yaml` records the default experiment grid.

## Graph construction and communities

The default study compares k=10, 15 and 20, union and mutual kNN edges, seven
Leiden resolutions and three seeds. This yields 126 partitions. Cosine neighbors
are computed in blocks with deterministic index tie breaking; output edges are
sparse, positive, undirected and have no self loops. Union keeps either direction
of a neighbor relation; mutual requires both. Every paper remains a node,
including isolates. Exact blocked neighbor search still has quadratic compute;
this baseline is guarded at 5,000 papers and is not a claim of ANN scalability.

Communities use weighted Leiden with the RB configuration quality function,
explicit resolution, fixed seeds and four optimization iterations, following the
[Leiden API](https://leidenalg.readthedocs.io/en/stable/reference.html).
Partition IDs are canonicalized by their first node. The primary graph was fixed
at union k=15 before running the experiment.

For each graph, resolution is selected by proximity of the median community
count across seeds to the number of occupied NMF topics. Ties prefer the lower
resolution. Topic/community agreement is never used to choose a resolution.
The achieved count and count gap are reported. In particular, disconnected
mutual graphs can have far more components than ten; they cannot be presented
as matched ten-community comparisons. Tables retain those mismatches.

Saved outputs include all partitions, the resolution/seed sweep, pairwise seed
AMI, edge Jaccard and partition agreement across graph structures, plus primary
node and edge tables. The primary graph's 9,350 edges form one connected component
with 11 communities at resolution 1.5; the target was ten topics, so the gap is one.

## Topic coherence and robustness

The text view remains independently fitted TF-IDF plus NMF. The study compares
8, 10 and 12 topics across seeds 42, 43 and 44. Each count is also refitted on an
80% sample stratified by publication year, with assignments transformed back
onto the full corpus. The observed sample has 611 of 767 papers because each
stratum size is rounded down. The vocabulary is refitted on each training sample.

Stability is measured against the full-corpus reference fit at the same topic
count. Reports include AMI for all jointly assigned papers, assignment coverage,
held-out-paper agreement for the refit runs, and optimally matched top-term
Jaccard using Hungarian matching. Held-out agreement is with the full-corpus
reference partition, not independent ground truth. Seeds use NMF's nndsvda
initialization; this is not a comparison of every initialization method.

Coherence is mean pairwise document-level NPMI for the top ten TF-IDF terms per
component, counting binary occurrence in the full available corpus. Zero joint
occurrence contributes -1 and ubiquitous joint occurrence contributes 0. This is
a corpus-specific document proxy, distinct from sliding-window or external-corpus
coherence. The [topic coherence literature](https://aclanthology.org/E14-1056/)
provides the broader context; no human topic-quality validation is claimed here.

Ten-topic refit AMI ranges from about 0.651 to 0.852. Full-data seed changes also
produce a lower agreement near 0.705 in one run. These are material stability
limits, not evidence that ten topics are uniquely correct. Generic topic IDs
and exported terms avoid assigning inherited human names to changed partitions.

## Alignment and its uncertainty

Alignment uses [adjusted mutual information](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.adjusted_mutual_info_score.html),
which adjusts for chance agreement and is invariant to label renumbering. The
main comparison uses the full-corpus ten-topic reference and the closest-count
Leiden partition. Results also show sensitivity to the text topic count.

Each selected graph receives 199 label permutations that preserve community
sizes. The report includes observed AMI, null mean and interval, excess above
the null and the finite-permutation one-sided p-value `(1 + exceedances)/(B + 1)`.
Holm adjustment covers the six semantic graph comparisons. These p-values are
secondary diagnostics; 199 permutations limit minimum attainable p to 0.005.

The paired, paper-level AMI bootstrap uses 300 resamples with bias correction and
jackknife acceleration through [SciPy BCa](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html).
Warnings and degenerate distributions are recorded; an undefined interval stays
undefined, and intervals excluding the point estimate are explicitly flagged.
They are conditional resampling intervals with fitted labels fixed. They do not
account for graph dependence, vocabulary/model refitting, source sampling bias
or the resolution-selection procedure, so nominal population coverage is not
established. The separate refit study measures one part of model instability.

The primary topic/community AMI is approximately 0.362 with a conditional BCa
interval near 0.316–0.372. The permutation null mean is near zero. This measures
partial agreement, not validation of the topic labels. The legacy threshold
partition is also reported with its own AMI, ARI, NMI and 124 communities; changes
in agreement cannot be attributed to a single algorithm change because graph
structure and partition granularity differ.

## Citation normalization and effect sizes

Source citation counts are normalized by the mean within publication year and
highest-scoring OpenAlex source topic. These source topics are a field proxy,
kept separate from the fitted NMF labels whose citation distributions are tested.
Groups smaller than five, or with unknown topics, fall back to the year cohort;
years smaller than five fall back to the corpus. All-zero cohorts normalize to
zero. Each paper records its cohort mean, size and fallback level. There are
436 source-topic/year normalizations and 331 year-only fallbacks in this corpus.

This is cross-sectional year/cohort adjustment, not a causal age effect or a
longitudinal citation-growth model. The original collection time and discarded
raw source records remain unavailable.

Topic citation differences are reported before and after normalization using
Kruskal–Wallis H and H-based eta-squared, clipped to [0,1]:
`(H - groups + 1)/(papers - groups)`. This is
[eta-squared H, not rank epsilon-squared](https://rpkgs.datanovia.com/rstatix/reference/kruskal_effsize.html).
Its percentile interval resamples within topic groups, holding labels and cohort
normalization fixed. Tiny p-values are secondary to the effect size.

Pairwise comparisons use [Dunn tests with tie correction](https://scikit-posthocs.readthedocs.io/en/latest/generated/scikit_posthocs.posthoc_dunn.html)
and Holm adjustment across all 45 topic pairs within each citation measure.
Cliff's delta and stratified percentile intervals accompany each pair, with the
sign defined as topic A minus topic B. Small groups and constant inputs are
reported explicitly. The raw H reproduces 208.64; after normalization it is
122.57. H-based eta-squared changes from about 0.264 to 0.150. These differences
remain exploratory and do not establish causation.

## Corrected centrality and the citation view

Similarity is retained as edge strength for Leiden and PageRank. Betweenness
uses `max(1e-6, 1 - cosine_similarity)` as distance, correcting the old notebook's
use of similarity as path length. NetworkX defines weighted betweenness weights
as [distances](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.centrality.betweenness_centrality.html).
The current corpus uses exact betweenness; larger permitted experiments can use
seeded sampled estimates with the sample count recorded.

The distance-definition comparison holds the legacy threshold graph topology
fixed to isolate that correction. The primary graph also exports degree,
PageRank and k-core, with raw and normalized citation Spearman correlations and
paired percentile intervals. k-core is constant on this primary kNN graph, so
its correlation is undefined and is not replaced by zero.

The corpus retains 21,112 reference entries. Of these, 1,507 unique directed
internal links remain after excluding self references; most entries point
outside the corpus. The directed edge table is preserved. For Leiden comparison,
the study uses an undirected binary projection on the 536 papers with internal
citation incidence (69.9% coverage). Papers without incidence have no citation
community assignment. Citation/semantic and citation/text alignment are measured
only on the covered subset, with count gaps and permutation results retained.
The primary citation partition has 13 communities against 11 semantic communities.
Incomplete reference coverage prevents claims about the full global citation graph.

Topic/year counts include zero-count cells, corpus shares and Wilson intervals.
These describe the collected corpus and do not establish field-wide emergence.

## Reproduction and verification

The output manifest records the baseline manifest hash, source/configuration
hashes, all source code hashes, Python/dependency versions, seeds and artifact
hashes. Tables, the machine-readable report, `summary.md` and
`research_overview.png` are generated without network access after dependencies
are installed. The baseline and search artifacts are preserved.

`python -m src.verify` now covers Sections 1–4: offline tests, dependency checks,
corpus audit, baseline rebuild, retrieval evaluation, the full research methods
study, research artifact hashes, dashboard interactions and localhost HTTP checks.
It also rejects changes to source or configuration during verification. The HTTP
step requires permission to bind a local port. Full runs and research plots are
saved under the verification directory; the unit fixture reproduces all research
artifacts twice on a small corpus. Original notebook experiments are syntax
checked, not rerun, and browser canvas interaction remains unverified.

ANN construction, Tier S data collection, model-family comparisons and cloud
operations belong to later work. Independent relevance judgments and human topic
interpretation remain open quality limitations.
