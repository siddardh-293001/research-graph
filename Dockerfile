FROM node:22-alpine AS frontend
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/index.html web/vite.config.js ./
COPY web/src ./src
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    RESEARCHGRAPH_RELEASE=/app/release OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
    TOKENIZERS_PARALLELISM=false
WORKDIR /app
RUN useradd --create-home --uid 1000 app
COPY requirements-serving.txt ./
RUN pip install --no-cache-dir -r requirements-serving.txt
COPY --chown=app:app src/__init__.py src/api.py src/public_engine.py src/paper_insights.py ./src/
COPY --chown=app:app deploy/release-parts ./deploy/release-parts
COPY scripts/fetch_model.py scripts/restore_release.py ./scripts/
RUN python scripts/restore_release.py && python scripts/fetch_model.py && rm -rf ./deploy/release-parts
COPY --from=frontend --chown=app:app /web/dist ./web/dist
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:'+__import__('os').environ.get('PORT','8000')+'/readyz', timeout=4)"
CMD ["sh", "-c", "exec uvicorn src.api:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-access-log"]
