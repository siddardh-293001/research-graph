"""Restore published atlas assets from this project's GitHub releases, with bounds."""
import json
from pathlib import Path
import shutil
import sys
import urllib.error
import urllib.request
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.restore_release import restore,digest
REPOSITORY='siddardh-293001/research-graph'


def download(url,path,limit):
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'ResearchGraph/0.7'}),timeout=90) as response, Path(path).open('wb') as output:
        total=0
        while chunk:=response.read(1024*1024):
            total+=len(chunk)
            if total>limit:raise ValueError('Remote release exceeds size bound')
            output.write(chunk)


def latest_release():
    request=urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/releases/latest',headers={'Accept':'application/vnd.github+json','User-Agent':'ResearchGraph/0.7'})
    try:
        with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code==404:return None
        if exc.code not in (403,429):raise
    # Public web redirects do not share the anonymous REST API rate quota.
    request=urllib.request.Request(f'https://github.com/{REPOSITORY}/releases/latest',headers={'User-Agent':'ResearchGraph/0.7'})
    with urllib.request.urlopen(request,timeout=30) as response:
        url=response.geturl()
    prefix=f'https://github.com/{REPOSITORY}/releases/tag/'
    if not url.startswith(prefix):raise ValueError('Unexpected latest release redirect')
    tag=url[len(prefix):]
    import re
    if not re.fullmatch(r'atlas-[0-9a-f]{16}',tag):raise ValueError('Invalid public atlas tag')
    return {'tag_name':tag,'draft':False,'prerelease':False,'assets':None}


def fetch(parts,output,model_source):
    release=latest_release()
    if release is None:return None
    if not str(release.get('tag_name','')).startswith('atlas-') or release.get('draft') or release.get('prerelease'):raise ValueError('Not a production atlas release')
    assets=None if release['assets'] is None else {a['name']:a for a in release['assets']};parts=Path(parts);output=Path(output);parts.mkdir(parents=True)
    def asset(name,limit):
        if assets is None:
            url=f'https://github.com/{REPOSITORY}/releases/download/{release["tag_name"]}/{name}'
        else:
            record=assets.get(name)
            if not record or record['size']>limit:raise ValueError('Missing or oversized atlas asset')
            url=record['browser_download_url']
        if not url.startswith(f'https://github.com/{REPOSITORY}/releases/download/'):raise ValueError('Unexpected asset host or repository')
        download(url,parts/name,limit)
    asset('manifest.json',65536);manifest=json.loads((parts/'manifest.json').read_text())
    if not 1<=len(manifest['parts'])<=16 or sum(p['bytes'] for p in manifest['parts'])>256*1024*1024:raise ValueError('Invalid atlas size')
    for part in manifest['parts']:
        if Path(part['file']).name!=part['file'] or not part['file'].startswith('release-'):raise ValueError('Unsafe asset name')
        asset(part['file'],24*1024*1024)
    restore(parts,output)
    if release['tag_name']!='atlas-'+digest(output/'release.json')[:16]:raise ValueError('Atlas tag does not match release hash')
    expected=json.loads((output/'release.json').read_text())['artifacts']['model.onnx']
    if digest(model_source)!=expected:raise ValueError('Published model is incompatible with this app')
    shutil.copyfile(model_source,output/'model.onnx')
    return {'tag':release['tag_name'],'release_sha256':digest(output/'release.json')}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--parts',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--model',type=Path,required=True);a=p.parse_args();print(json.dumps(fetch(a.parts,a.output,a.model)))
