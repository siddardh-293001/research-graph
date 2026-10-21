# Section 2 Reproducible baseline

Run `python -m src.pipeline` from the repository root with the project virtual
environment active. The default run uses the already cached, pinned embedding
model revision and writes all results into a fresh `data/runs/<run-id>/` folder.

## Input recovery

The missing original OpenAlex snapshot has been explicitly replaced with
`data/source/baseline_metadata.parquet`: the 876 surviving cleaned metadata
records with three notebook-derived fields removed. `data/source/provenance.json`
records the source and replacement hashes and the removed columns. This is a
recovered input, not a reconstruction of discarded API records. The historical
cleaning process before these 876 records cannot be independently reproduced.

## Pipeline stages

1. Validate input IDs and required columns; reproduce legacy title classification,
   abstract length, normalized-title sorting and deduplication.
2. Exclude 109 records without abstracts; preserve the resulting 767-paper order.
3. Generate normalized 384-dimensional embeddings on CPU with a pinned model
   revision and fixed seed, using the title plus abstract.
4. Fit TF-IDF and seeded 10-topic NMF with the notebook's final stopwords,
   year removal and settings. Export vocabulary, IDF, components and top terms.
5. Build the legacy cosine threshold graph at 0.65, run seeded Louvain, and
   compute degree, weighted betweenness and PageRank.
6. Join topics and graph statistics by unique paper ID with one-to-one validation;
   recompute year-normalized citation values and verify embedding row alignment.
7. Save node and edge Parquet tables, analysis tables, embeddings and safe IDs,
   audit and comparison metrics. Record configuration, code hashes, model revision,
   dependency versions, source provenance and artifact hashes in the manifest.

Every run has a distinct ID and keeps original baseline artifacts intact. A
processing exception marks the run manifest failed. There is no implicit promotion
into the analyst dashboard; its existing baseline remains available.

## Verification results

The full baseline was regenerated twice with identical output hashes across those
two runs. The rebuilt result contains 767 papers, 11,064 edges, 124 communities
and 10 topics. Topic and community assignments have AMI 1.0 against the saved
baseline. Paper IDs and ordering match exactly. Regenerated embeddings have a
maximum absolute difference of about 2.35e-7 from the saved matrix. The baseline
topic-community ARI is 0.2390973 and NMI is 0.3933807.

Unit and integration tests cover deterministic cleaning, blank abstract exclusion,
duplicate ID rejection, graph size guards, joining duplicate titles by ID, a
small offline end-to-end rebuild, input preservation, output hashes, repeated
builds and failed-run manifests. Synthetic embeddings are injected only for the
small integration fixture; the full verification regenerates real embeddings.

## Boundaries before the next section

These results reproduce exploratory methods; they do not validate the scientific
claims or search quality. Legacy title-based deduplication is retained only for
baseline compatibility. Future ingestion uses the shared identity layer.

Louvain is retained for this comparison. Leiden, sparse kNN graphs and sensitivity
studies belong to Section 4. Weighted betweenness also retains the notebook's use
of similarity as path distance, a known methodological limitation to correct and
measure there. The graph stage rejects corpora over 2,000 papers before embedding
to prevent accidental use of this dense baseline at scale.

Manual topic labels are inherited from the notebook; inspect exported top terms
after changing the corpus or model. Exact floating-point reproducibility across
different hardware and dependency versions is not promised. Each manifest records
the tested environment, and model cache availability is checked by the model
loader. No network ingestion, cloud resources or deployment are involved.
