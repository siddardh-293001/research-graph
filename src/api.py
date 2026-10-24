"""Public frozen-corpus API: uvicorn src.api:app --host 0.0.0.0 --port 8000."""
import asyncio
from collections import deque
from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import sys
from time import perf_counter, monotonic
from typing import Literal
import uuid

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool
from src.public_engine import PublicEngine

ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger('researchgraph.http')
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler(sys.stdout))
logger.propagate = False


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    query: str = Field(min_length=1, max_length=2000)
    mode: Literal['bm25','dense','hybrid'] = 'hybrid'
    top_k: int = Field(default=10, ge=1, le=50)
    year_min: int | None = Field(default=None, ge=1900, le=2100)
    year_max: int | None = Field(default=None, ge=1900, le=2100)
    topic_ids: list[int] | None = Field(default=None, max_length=20)
    research_topic: str | None = Field(default=None, pattern=r'^T[0-9]{1,12}$')

    @model_validator(mode='after')
    def valid_filters(self):
        if not self.query.strip():
            raise ValueError('Query must contain text')
        if self.year_min is not None and self.year_max is not None and self.year_min > self.year_max:
            raise ValueError('Minimum year exceeds maximum year')
        if self.topic_ids is not None and any(t < 0 or t > 100 for t in self.topic_ids):
            raise ValueError('Invalid topic identifier')
        return self


def create_app(engine_factory=None, web_root=None, requests_per_minute=120):
    factory = engine_factory or (lambda: PublicEngine(os.environ.get('RESEARCHGRAPH_RELEASE', ROOT/'build/release')))
    web_root = Path(web_root or ROOT/'web/dist')

    @asynccontextmanager
    async def lifespan(app):
        app.state.engine = await run_in_threadpool(factory)
        # One model call at a time keeps peak memory bounded on free instances.
        app.state.search_slot = asyncio.Semaphore(1)
        app.state.recent_requests = deque()
        yield

    app = FastAPI(title='ResearchGraph API', version='0.6.0', lifespan=lifespan,
                  docs_url='/api/docs', redoc_url=None, openapi_url='/api/openapi.json',
                  description='Search a frozen Tier S snapshot. Provisional judgments; no live ingestion.')

    @app.middleware('http')
    async def limits_and_logs(request: Request, call_next):
        start = perf_counter(); request_id = uuid.uuid4().hex
        if len(request.scope.get('query_string', b'')) > 8192:
            return JSONResponse({'detail': 'URL too long'}, status_code=414)
        # Count streaming chunks too: Content-Length alone is not a body limit.
        if request.method in {'POST','PUT','PATCH'}:
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 16384:
                    return JSONResponse({'detail': 'Request body exceeds 16 KiB'}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers['X-Request-ID'] = request_id
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        # Swagger uses its own CDN scripts; the public React app is entirely self hosted.
        if not request.url.path.startswith('/api/docs'):
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'"
        route = request.scope.get('route')
        logger.info(json.dumps({'severity': 'ERROR' if response.status_code >= 500 else 'INFO',
                    'request_id': request_id, 'route': getattr(route, 'path', 'unmatched'),
                    'method': request.method, 'status': response.status_code,
                    'duration_ms': round((perf_counter()-start)*1000, 2)}))
        return response

    @app.get('/healthz')
    def health():
        return {'status': 'ok'}

    @app.get('/readyz')
    def ready():
        return {'status': 'ready', 'papers': app.state.engine.manifest['papers'], 'release_sha256':getattr(app.state.engine,'release_sha256',None)}

    @app.get('/api/status')
    def status():
        manifest = app.state.engine.manifest
        result={key: manifest[key] for key in ['run_id','papers','source_finished_at','topics','year_min','year_max','limitations']}
        result.update(research_topics=manifest.get('research_topics',[]),feed=manifest.get('feed',{}),release_schema=manifest.get('schema_version',1))
        return result

    @app.get('/api/feed')
    def feed(limit: int = Query(default=12,ge=1,le=30)):
        return app.state.engine.feed(limit)

    @app.post('/api/search')
    async def search(payload: SearchRequest):
        recent = app.state.recent_requests
        now = monotonic()
        while recent and recent[0] < now-60:
            recent.popleft()
        if len(recent) >= requests_per_minute:
            raise HTTPException(429, 'Demo request limit reached; try again shortly.', headers={'Retry-After':'60'})
        recent.append(now)
        try:
            await asyncio.wait_for(app.state.search_slot.acquire(), timeout=2)
        except TimeoutError:
            raise HTTPException(503, 'Search is busy; try again shortly.', headers={'Retry-After':'2'}) from None
        start = perf_counter()
        try:
            results, cached = await run_in_threadpool(app.state.engine.search, **payload.model_dump())
        finally:
            app.state.search_slot.release()
        return {'run_id': app.state.engine.manifest['run_id'], 'query': payload.query, 'mode': payload.mode,
                'count': len(results), 'results': results, 'cached': cached,
                'search_ms': round((perf_counter()-start)*1000, 3)}

    @app.get('/api/paper')
    def paper(paper_id: str = Query(min_length=1, max_length=200)):
        result = app.state.engine.paper(paper_id)
        if result is None:
            raise HTTPException(404, 'Paper not found')
        return result

    @app.get('/api/graph')
    def graph(paper_id: str = Query(min_length=1, max_length=200), limit: int = Query(default=20, ge=1, le=30)):
        result = app.state.engine.neighborhood(paper_id, limit)
        if result is None:
            raise HTTPException(404, 'Paper not found')
        return result

    @app.get('/api/browse')
    def browse(query: str = Query(default='',max_length=300), field: Literal['title','abstract','author','doi']='title', sort: Literal['newest','citations','title']='newest', page: int=Query(default=1,ge=1,le=1250), year_min: int|None=None, year_max: int|None=None):
        from src.exploration import browse
        return browse(app.state.engine,query,field,sort,page,year_min,year_max)

    @app.get('/api/author')
    def author(name: str=Query(min_length=1,max_length=300),page: int=Query(default=1,ge=1,le=1250)):
        from src.exploration import author_profile
        return author_profile(app.state.engine,name,page)

    @app.get('/api/evidence')
    def evidence(paper_id: str=Query(min_length=1,max_length=200),question: str=Query(default='',max_length=500)):
        from src.exploration import evidence
        result=evidence(app.state.engine,paper_id,question)
        if result is None:raise HTTPException(404,'Paper not found')
        return result

    @app.get('/api/source-metadata')
    def source_metadata(paper_id: str=Query(min_length=1,max_length=200)):
        from src.exploration import source_metadata
        try:return source_metadata(paper_id)
        except Exception:raise HTTPException(503,'Source metadata is unavailable; retry later.') from None

    @app.get('/api/trends')
    def trends():
        from src.exploration import trends
        return trends(app.state.engine)

    @app.get('/', include_in_schema=False)
    def home():
        if not (web_root/'index.html').exists():
            raise HTTPException(503, 'Build the public interface with npm ci && npm run build in web/.')
        return FileResponse(web_root/'index.html')

    if (web_root/'assets').exists():
        app.mount('/assets', StaticFiles(directory=web_root/'assets'), name='assets')
    return app


app = create_app()
