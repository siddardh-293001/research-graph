"""Stage only public serving inputs; never copy the workspace wholesale."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]


def stage(directory):
    directory=Path(directory)
    if directory.exists():raise ValueError('Choose a fresh staging directory')
    directory.mkdir(parents=True)
    paths=['Dockerfile','.dockerignore','requirements-serving.txt','render.yaml',
           'src/__init__.py','src/api.py','src/public_engine.py','scripts/fetch_model.py','scripts/deploy_render.py','scripts/restore_release.py',
           'web/package.json','web/package-lock.json','web/index.html','web/vite.config.js',
           'web/src/main.jsx','web/src/style.css','tests/test_api.py',
           'web/playwright.config.js','web/tests/public.spec.js',
           '.github/workflows/public-demo.yml','infra/render/main.tf','infra/render/README.md',
           'infra/render/terraform.tfvars.example','infra/render/.terraform.lock.hcl']
    for name in paths:
        source=ROOT/name
        if not source.is_file():raise ValueError(f'Missing serving file: {name}')
        target=directory/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    shutil.copytree(ROOT/'deploy/release-parts',directory/'deploy/release-parts')
    (directory/'README.md').write_text('# ResearchGraph public demo\n\nFrozen 20,000-paper Tier S snapshot, FastAPI and React.\n\n'
        'This repository contains only allowlisted public serving artifacts. The Docker image downloads the pinned Apache-2.0 MiniLM ONNX model and verifies its SHA-256. All serving data is frozen and read only. No external database or paid inference service is used.\n\n'
        'Build: `docker build -t researchgraph .`\n\nRun: `docker run --rm -p 8000:8000 --memory=512m researchgraph`\n\n'
        'Render Blueprint: `render.yaml`, explicitly `plan: free`. Free instances sleep when idle; latency and availability depend on that plan. No paid plan is authorized.\n\n'
        'The research benchmark is provisional and awaits independent review. The corpus is selectively collected OpenAlex metadata, not a random sample.\n')
    files=[p for p in directory.rglob('*') if p.is_file()]
    print(json.dumps({'directory':str(directory.resolve()),'files':len(files),'bytes':sum(p.stat().st_size for p in files),'largest_file_bytes':max(p.stat().st_size for p in files)},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    stage(parser.parse_args().output)
