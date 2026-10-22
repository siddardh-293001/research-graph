# Section 6: public interface, API and free hosting

The user changed the deployment requirement to a free plan without paid credits.
The target is Render's `free` web service in the confirmed `My Workspace`
workspace (`tea-dbb5bjnavr4c73fvbs30`). The user confirmed it has no payment
method. No paid compute, database, disk, inference API, subscription or cloud
credit purchase is authorized. The repository is
https://github.com/siddardh-293001/research-graph; subsequent project additions
should be verified and published there as requested by the user.

## Application

FastAPI serves the React interface and API from one origin. `/api/search`
accepts keyword, semantic and hybrid ranking, year ranges, topic IDs and bounded
result counts. `/api/paper` returns one paper, `/api/graph` a bounded neighborhood,
and `/api/status` corpus provenance and limitations. `/healthz` and `/readyz`
support operational checks; `/api/docs` documents the contract. Request bodies
are limited to 16 KiB, query text to 2,000 characters, results to 50, and graph
neighbors to 30. One search runs at a time, waiting requests time out after two
seconds, the process accepts at most 120 searches per minute, and the result
cache holds at most 64 entries. These are demo safeguards, not a distributed
rate limiter or a bandwidth billing cap. Structured logs exclude query text.

The serving process uses read-only SQLite metadata, packed BM25 postings, the
frozen FAISS HNSW index, memory-mapped embeddings and CPU ONNX inference. It
does not import the full PyTorch, pandas, sklearn or NetworkX research stack.
The ONNX model comes from the exact pinned MiniLM revision, uses 256-token
truncation, masked mean pooling and unit normalization. The model card records
Apache-2.0 licensing. It is downloaded at image build and checksum-verified;
search does not call a paid inference provider. SQLite is rebuilt from the
frozen corpus and bundled with the image, so free ephemeral disk does not lose
the published snapshot. Mutable accounts and writes are outside this section.

```sh
python scripts/prepare_release.py
cd web
npm ci
npm run build
cd ..
python -m uvicorn src.api:app --host 127.0.0.1 --port 8000 --no-access-log
```

Then open http://127.0.0.1:8000. The original Streamlit analyst dashboard remains
available with `streamlit run app.py`.

## Deployment and zero-spend policy

`Dockerfile` uses separate frontend and Python serving stages and runs as an
unprivileged user. `requirements-serving.txt` pins the lean direct dependencies;
the npm lock file fixes the frontend dependency graph. The Docker build context
uses an allowlist. The Render Blueprint explicitly selects `plan: free`, one
service and no external database. `infra/render` provides equivalent Terraform
with a pinned official provider; import an existing service before using it to
manage a connector-created service. Do not create duplicate resources through
both configurations. Neither configuration upgrades resources automatically.

Free Render compute currently has 512 MB RAM, fractional CPU, 750 shared monthly
instance hours, idle sleep and an ephemeral filesystem. Render documents that
accounts without a payment method are suspended when free usage is exhausted
instead of being billed. A pipeline spending limit alone does not cap all
bandwidth overages. Keep the workspace without a payment method. Render's own
usage emails provide quota alerts; a custom paid cloud billing-alert resource
is not part of this free deployment. Cold-start and fractional-CPU latency must
be measured on the deployed service before making hosting performance claims.

`.github/workflows/public-demo.yml` runs API tests, builds the container,
starts it under a 512 MB limit, checks actual HTTP responses, and runs Chromium
desktop/mobile tests. Its manual deployment job checks the service is still
free, deploys the exact verified commit and polls until live before smoke tests.
It needs a securely stored `RENDER_API_KEY` secret and `RENDER_SERVICE_ID`
environment variable in GitHub's `free-demo` environment. This environment must
be configured on GitHub before the deployment job can run.

## Verification evidence and completion gate

The 50-query local serving comparison found identical BM25 rankings, dense
top-20 mean overlap 1.0, and no mean nDCG@10 or Recall@20 difference in any mode.
The minimum cosine between the ONNX and original query vectors was
0.9999998808. Filtered rankings matched the full engine. The isolated process
peaked around 315–320 MiB while testing long queries, filtered dense retrieval
and a full cache on macOS. This is not a Linux-container memory measurement.
Real local HTTP tests passed with three concurrent clients; their repeated-query
latencies include cache hits and are not an uncached workload benchmark.

Desktop and 390px mobile Chromium tests cover example queries, all rankings,
topic/year filters, details, graph structure, empty results, clearing and error
recovery. Terraform's provider validation and the current official Render JSON
Schema passed. The full verifier reruns Sections 1–5 and these public-app checks;
future sections must extend and run it before being reported complete.

Section 6 is complete only after the published container is live on the free
plan, its public API/UI checks pass, hosted memory and cold/warm latency are
recorded, and the verification record names the deployed commit and release
hash. A passing local verification alone does not satisfy the public-URL gate.

Sources: [Render free limits](https://render.com/docs/free),
[billing FAQ](https://render.com/docs/faq),
[compute plans](https://render.com/docs/compute-plans),
[Blueprint specification](https://render.com/docs/blueprint-spec),
[official Terraform provider](https://github.com/render-oss/terraform-provider-render),
[ONNX Runtime inference](https://onnxruntime.ai/docs/api/python/api_summary.html),
[FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/).

## Debug verification — 22 October 2026

The blank page was opened through a file URL while the API server was stopped.
Use `Start ResearchGraph.command` or `.venv/bin/python scripts/serve.py`, then
visit http://127.0.0.1:8000. The launcher builds the UI before starting the API.
The HTML now displays startup instructions if React cannot load. A stale paper
detail request is cancelled when a new search starts or the detail panel closes.

Full verification passed all 21 checks, 75 unit/integration tests and four
Chromium scenarios, including the new startup and delayed-detail regressions.
Evidence: [portable verification summary](verification/section6-local.json).
Local peak serving RSS was 355.98 MiB; this is not hosted-container evidence.
The complete serving bundle downloaded from GitHub restored successfully with
all archive and artifact checksums validated. Public deployment remains a
separate completion gate.
