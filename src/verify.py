"""Verify implemented sections end to end: python -m src.verify."""
import ast
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

from src.artifacts import load_run, resolve_run, latest_tier_s_run
from src.pipeline import ROOT, sha256


def http_smoke(output, env, log_name='http_server.log'):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    with (output/log_name).open('w') as log:
        process = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', str(ROOT/'app.py'),
            '--server.address', '127.0.0.1', '--server.port', str(port), '--server.headless', 'true',
            '--browser.gatherUsageStats', 'false'], cwd=ROOT, env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError('Streamlit exited before becoming ready')
                try:
                    with urllib.request.urlopen(url+'/_stcore/health', timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(.2)
            else:
                raise RuntimeError('Streamlit did not become healthy')
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status != 200 or 'streamlit' not in response.read().decode().lower():
                    raise AssertionError('Unexpected app response')
            return {'passed': True, 'health_status': 200, 'page_status': 200}
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


@contextmanager
def public_server(output, env):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port=sock.getsockname()[1]
    url=f'http://127.0.0.1:{port}'
    with (output/'public_api_server.log').open('w') as log:
        process=subprocess.Popen([sys.executable,'-m','uvicorn','src.api:app','--host','127.0.0.1',
                                  '--port',str(port),'--no-access-log'],cwd=ROOT,env=env,stdout=log,stderr=log)
        try:
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                if process.poll() is not None:raise RuntimeError('Public API exited during startup')
                try:
                    with urllib.request.urlopen(url+'/readyz',timeout=1) as response:
                        if response.status==200:break
                except OSError:time.sleep(.2)
            else:raise RuntimeError('Public API did not become ready')
            yield url
        finally:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()


def verify():
    output = ROOT/'data/verification'/(
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    output.mkdir(parents=True)
    report = {'scope': 'Implemented sections 1 through 6 and Section 7A; local checks plus recorded public deployment', 'status': 'running', 'checks': {},
        'limitations': ['Independent benchmark relevance review is pending.',
            'Cached Tier S provenance is verified; no fresh API recollection, full Tier S re-embedding, deployment or future section validation.',
            'Notebook cells are syntax-checked; historical notebook experiments are not re-executed.',
            'Local serving memory is measured on the host OS; Linux container and hosted resource limits need separate evidence.']}
    env = dict(os.environ, STREAMLIT_BROWSER_GATHER_USAGE_STATS='false')
    before = {p.name: sha256(p) for p in (ROOT/'data/processed').iterdir() if p.is_file()}
    code_paths = [ROOT/'app.py', *(ROOT/'src').rglob('*.py'), *(ROOT/'tests').glob('*.py'),
                  *(ROOT/'scripts').glob('*.py'), *(ROOT/'web/src').glob('*'), *(ROOT/'web/tests').glob('*.js')]
    code_before = {str(p.relative_to(ROOT)): sha256(p) for p in code_paths}
    config_paths = [ROOT/'requirements.txt', ROOT/'requirements-serving.txt', *(ROOT/'config').glob('*.yaml'),
                    ROOT/'web/package.json',ROOT/'web/package-lock.json',ROOT/'web/playwright.config.js',
                    ROOT/'web/vite.config.js',ROOT/'web/index.html',ROOT/'Start ResearchGraph.command',ROOT/'Dockerfile',ROOT/'.dockerignore',
                    ROOT/'render.yaml',ROOT/'infra/render/main.tf',ROOT/'infra/render/.terraform.lock.hcl',
                    ROOT/'.github/workflows/scheduled-atlas.yml', ROOT/'data/benchmark/effective.json', ROOT/'.github/workflows/public-demo.yml', ROOT/'.github/workflows/recent-candidates.yml', ROOT/'infra/render/render.schema.json',
                    *(ROOT/'deploy/release-parts').glob('*')]
    config_before = {str(p.relative_to(ROOT)): sha256(p) for p in config_paths}

    def save():
        (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')

    def command(name, args, timeout=300, executable=None, cwd=ROOT):
        start = time.perf_counter()
        result = subprocess.run([executable or sys.executable, *args], cwd=cwd, env=env,
                                capture_output=True, text=True, timeout=timeout)
        (output/f'{name}.log').write_text(result.stdout+'\n'+result.stderr)
        report['checks'][name] = {'passed': result.returncode == 0,
            'return_code': result.returncode, 'seconds': time.perf_counter()-start,
            'command': [executable or sys.executable, *args]}
        save()
        print(f'{name}: {"PASS" if result.returncode == 0 else "FAIL"}', flush=True)
        if result.returncode:
            raise RuntimeError(f'{name} failed; see {output / (name+".log")}')

    save()
    try:
        command('dependencies', ['-m', 'pip', 'check'])
        command('tests', ['-m', 'unittest', 'discover', '-s', 'tests', '-v'])
        cells = 0
        for notebook in sorted((ROOT/'notebooks').glob('*.ipynb')):
            for cell in json.loads(notebook.read_text())['cells']:
                if cell['cell_type'] == 'code':
                    ast.parse(''.join(cell['source']), filename=str(notebook))
                    cells += 1
        for path in [ROOT/'app.py', *(ROOT/'src').rglob('*.py')]:
            ast.parse(path.read_text(), filename=str(path))
        report['checks']['python_and_notebook_syntax'] = {'passed': True, 'notebook_code_cells': cells}
        command('legacy_corpus_audit', ['-m', 'src.audit'])
        previous, _ = resolve_run()
        command('baseline_rebuild', ['-m', 'src.pipeline'])
        directory, manifest, papers, embeddings, graph = load_run()
        for name in ['paper_embeddings.npy', 'graph_nodes.parquet', 'graph_edges.parquet',
                     'nlp_topic_assignments.parquet', 'research_analysis_dataset.parquet']:
            if sha256(previous/name) != sha256(directory/name):
                raise AssertionError(f'Baseline reproduction mismatch: {name}')
        report['checks']['baseline_reproduction_and_artifact_integrity'] = {
            'passed': True, 'baseline_run': str(directory), 'paper_count': len(papers),
            'edges': graph.number_of_edges(), 'communities': int(papers.community.nunique()),
            'embedding_shape': list(embeddings.shape), 'comparison_run': str(previous)}
        env['RESEARCHGRAPH_RUN_DIR'] = str(directory)
        command('retrieval_evaluation', ['-m', 'src.evaluation', '--artifacts', str(directory),
                                       '--output-root', str(output/'evaluation')])
        evaluation_path = next((output/'evaluation').glob('*/report.json'))
        evaluation = json.loads(evaluation_path.read_text())
        report['evaluation_report'] = str(evaluation_path)
        report['retrieval_results'] = evaluation['results']
        command('research_methods', ['-m', 'src.research', '--artifacts', str(directory),
                                    '--output-root', str(output/'research')])
        research_manifest_path = next((output/'research').glob('*/manifest.json'))
        research_manifest = json.loads(research_manifest_path.read_text())
        if research_manifest['status'] != 'complete':
            raise AssertionError('Research methods run did not complete')
        for name, expected in research_manifest['artifacts'].items():
            if sha256(research_manifest_path.parent/name) != expected:
                raise AssertionError(f'Research artifact integrity failure: {name}')
        research = json.loads((research_manifest_path.parent/'report.json').read_text())
        report['research_report'] = str(research_manifest_path.parent/'report.json')
        report['research_primary_graph'] = research['primary_graph']
        report['checks']['research_artifact_integrity'] = {
            'passed': True, 'artifacts': len(research_manifest['artifacts']),
            'papers': research['papers'], 'nonconverged_topic_fits': research['nonconverged_topic_fits']}
        command('dashboard_interactions', ['-m', 'src.dashboard_check'])
        report['checks']['http_serving'] = http_smoke(output, env)
        tier_directory=latest_tier_s_run()
        if tier_directory is None:raise ValueError('Build Tier S with python -m src.tier_s before full verification')
        command('tier_s_integrity_ann', ['-m','src.tier_s_check','--artifacts',str(tier_directory),'--output',str(output/'tier_s_check.json')],timeout=600)
        report['tier_s_checks']=json.loads((output/'tier_s_check.json').read_text())
        report['tier_s_run']=str(tier_directory)
        command('tier_s_retrieval_evaluation',['-m','src.evaluation','--artifacts',str(tier_directory),'--output-root',str(output/'tier_s_evaluation')],timeout=600)
        tier_evaluation=next((output/'tier_s_evaluation').glob('*/report.json'))
        report['tier_s_evaluation_report']=str(tier_evaluation)
        report['tier_s_retrieval_results']=json.loads(tier_evaluation.read_text())['results']
        env['RESEARCHGRAPH_RUN_DIR']=str(tier_directory)
        command('tier_s_dashboard_interactions',['-m','src.dashboard_check'],timeout=600)
        report['checks']['tier_s_http_serving']=http_smoke(output,env,'tier_s_http_server.log')

        release=ROOT/'build/release'
        if not (release/'release.json').exists():raise ValueError('Prepare the public release with scripts/prepare_release.py first')
        release_hash=sha256(release/'release.json')
        command('section7_insights_incremental',['scripts/check_section7.py','--release',str(release),'--output',str(output/'section7.json')],timeout=600)
        report['section7']=json.loads((output/'section7.json').read_text())
        command('scheduled_update_lifecycle',['scripts/check_update_pipeline.py','--source',str(release),'--output',str(output/'update_lifecycle.json')],timeout=600)
        report['update_lifecycle']=json.loads((output/'update_lifecycle.json').read_text())
        command('deployment_config',['scripts/check_infra.py',str(output/'infrastructure.json')])
        report['infrastructure']=json.loads((output/'infrastructure.json').read_text())
        command('public_frontend_build',['run','build'],executable='npm',cwd=ROOT/'web')
        env['RESEARCHGRAPH_RELEASE']=str(release)
        with public_server(output,env) as url:
            command('public_serving_parity_memory_http',['scripts/check_public.py','--release',str(release),
                        '--base-url',url,'--output',str(output/'public_app.json')],timeout=600)
            report['public_app']=json.loads((output/'public_app.json').read_text())
            env['PUBLIC_BASE_URL']=url
            env['PLAYWRIGHT_OUTPUT_DIR']=str(output/'browser')
            command('public_browser_interactions',['run','test:e2e'],executable='npm',cwd=ROOT/'web')
        if release_hash!=sha256(release/'release.json'):raise ValueError('Public release changed during verification')
        report['public_release_sha256']=release_hash
        deployment_path=ROOT/'data/reports/public_deployment.json'
        if deployment_path.exists():
            deployment=json.loads(deployment_path.read_text())
            if deployment.get('verified_live') and deployment.get('release_sha256')==release_hash:
                report['public_deployment']=deployment
            else:report['limitations'].append('Saved public deployment does not match this release or is not verified live.')
        else:report['limitations'].append('No verified public deployment is recorded; a passing local check does not complete Section 6.')

        after = {p.name: sha256(p) for p in (ROOT/'data/processed').iterdir() if p.is_file()}
        if before != after:
            raise AssertionError('Legacy baseline artifacts were modified')
        report['checks']['legacy_artifacts_preserved'] = {'passed': True, 'files': len(before)}
        code_after = {str(p.relative_to(ROOT)): sha256(p) for p in code_paths}
        config_after = {str(p.relative_to(ROOT)): sha256(p) for p in config_paths}
        if code_before != code_after or config_before != config_after:
            raise AssertionError('Source or configuration changed during verification; rerun against the finished files')
        report['code_sha256'] = code_after
        report['config_sha256'] = config_after
        report['checks']['verification_inputs_unchanged'] = {'passed':True}
        report['status'] = 'passed'
    except Exception as exc:
        report.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        save()
        print(f'Verification report: {output / "report.json"}', flush=True)
    return output


if __name__ == '__main__':
    verify()
