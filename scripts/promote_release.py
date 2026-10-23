"""Publish verified atlas assets, deploy free service, restore release pointer on failure."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.restore_release import digest
from scripts.remote_release import REPOSITORY


def promote(parts,report):
    token=os.environ['GH_TOKEN']
    if not os.environ.get('RENDER_API_KEY') or not os.environ.get('RENDER_SERVICE_ID'):raise ValueError('Configure Render deployment credentials before automatic promotion')
    parts=Path(parts);manifest=json.loads((parts/'manifest.json').read_text());gate=json.loads(Path(report).read_text())
    if gate.get('passed') is not True or gate['release_sha256']!=manifest['release_sha256']:raise ValueError('Verification report does not match candidate')
    for part in manifest['parts']:
        if Path(part['file']).name!=part['file'] or digest(parts/part['file'])!=part['sha256']:raise ValueError('Candidate part changed after verification')
    base=f'https://api.github.com/repos/{REPOSITORY}'
    def api(path,payload=None,method=None):
        req=urllib.request.Request(base+path,data=None if payload is None else json.dumps(payload).encode(),method=method,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=90) as response:return json.load(response)
        except urllib.error.HTTPError as exc:raise RuntimeError('GitHub release operation failed with HTTP '+str(exc.code)) from None
    try:previous=api('/releases/latest')
    except RuntimeError as exc:
        if 'HTTP 404' not in str(exc):raise
        previous=None
    # The batch must extend the current production parent, not overwrite a newer run.
    if previous:
        expected='atlas-'+gate['parent_release_sha256'][:16]
        if previous['tag_name']!=expected:raise ValueError('Production release advanced; rebuild the update from its new parent')
    tag='atlas-'+manifest['release_sha256'][:16]
    created=api('/releases',{'tag_name':tag,'target_commitish':os.environ['GITHUB_SHA'],'name':tag,'draft':True,'body':'Verified scheduled atlas. See verification.json for scope and limits.'})
    upload=created['upload_url'].split('{',1)[0]
    for path in [parts/'manifest.json',*[parts/p['file'] for p in manifest['parts']],Path(report)]:
        name='verification.json' if path==Path(report) else path.name
        req=urllib.request.Request(upload+'?name='+name,data=path.read_bytes(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/octet-stream'})
        try:
            with urllib.request.urlopen(req,timeout=180) as response:response.read()
        except urllib.error.HTTPError as exc:raise RuntimeError('Release asset upload failed with HTTP '+str(exc.code)) from None
    api('/releases/'+str(created['id']),{'draft':False,'make_latest':'true'},'PATCH')
    env=dict(os.environ,EXPECTED_RELEASE_SHA256=gate['release_sha256'],EXPECTED_PAPERS=str(gate['papers']))
    result=subprocess.run([sys.executable,str(ROOT/'scripts/deploy_render.py')],env=env)
    if result.returncode:
        api('/releases/'+str(created['id']),{'prerelease':True,'make_latest':'false'},'PATCH')
        if previous:api('/releases/'+str(previous['id']),{'make_latest':'true'},'PATCH')
        # Rebuild using the previous pointer. If it also fails Render retains the last healthy instance.
        rollback=subprocess.run([sys.executable,str(ROOT/'scripts/deploy_render.py')],env=dict(os.environ,EXPECTED_RELEASE_SHA256=gate['parent_release_sha256']))
        raise RuntimeError('Promotion failed; previous release pointer restored. Rollback exit: '+str(rollback.returncode))
    print(json.dumps({'promoted':tag,'release_sha256':gate['release_sha256'],'papers':gate['papers']}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--parts',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args();promote(a.parts,a.report)
