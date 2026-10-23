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
    import time
    url='https://researchgraph-sdu4.onrender.com'
    success=False
    for _ in range(42):
        try:
            with urllib.request.urlopen(url+'/readyz',timeout=45) as response:ready=json.load(response)
            if ready.get('release_sha256')==gate['release_sha256'] and ready.get('papers')==gate['papers']:
                req=urllib.request.Request(url+'/api/search',data=json.dumps({'query':'graph retrieval','mode':'hybrid','top_k':5}).encode(),headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(req,timeout=45) as response:success=bool(json.load(response)['results'])
                if success:break
        except (OSError,ValueError):pass
        time.sleep(10)
    if not success:
        api('/releases/'+str(created['id']),{'prerelease':True,'make_latest':'false'},'PATCH')
        if previous:api('/releases/'+str(previous['id']),{'make_latest':'true'},'PATCH')
        raise RuntimeError('Hosted refresh verification failed; previous release pointer restored')
    print(json.dumps({'promoted':tag,'release_sha256':gate['release_sha256'],'papers':gate['papers']}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--parts',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args();promote(a.parts,a.report)
