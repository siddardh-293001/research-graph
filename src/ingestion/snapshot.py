"""Bounded OpenAlex cursor collection with immutable pages and resumable state."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import time
import requests
import yaml
from src.pipeline import ROOT, sha256

FIELDS = 'id,doi,title,publication_year,publication_date,cited_by_count,abstract_inverted_index,authorships,topics,keywords,referenced_works,related_works,open_access,ids,locations,primary_location,updated_date,created_date,is_retracted,language'


def api_key():
    key = os.environ.get('OPENALEX_API_KEY')
    if key:
        return key
    path = ROOT/'.env'
    if path.exists():
        for line in path.read_text().splitlines():
            name, separator, value = line.partition('=')
            if separator and name.strip().removeprefix('export ').strip()=='OPENALEX_API_KEY':
                return value.strip().strip('\"\'')
    return None


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, indent=2)+'\n')
    temporary.replace(path)


def fingerprint(settings):
    return hashlib.sha256(json.dumps(settings,sort_keys=True).encode()).hexdigest()


def collect(config_path=None, directory=None, session=None, sleeper=time.sleep):
    config = yaml.safe_load(Path(config_path or ROOT/'config/tier_s.yaml').read_text())['source']
    if not 1<=config['per_page']<=100:
        raise ValueError('OpenAlex supports at most 100 records per page')
    key = api_key()
    if not key:
        raise ValueError('Set OPENALEX_API_KEY in .env or the environment before cursor collection')
    directory = Path(directory or ROOT/'data/raw/tier_s_openalex')
    directory.mkdir(parents=True,exist_ok=True)
    manifest_path = directory/'manifest.json'
    if manifest_path.exists():
        state = json.loads(manifest_path.read_text())
        if state['config_fingerprint']!=fingerprint(config):
            raise ValueError('Source configuration changed; use a new snapshot directory')
        for page in state['pages']:
            if sha256(directory/page['file'])!=page['sha256']:
                raise ValueError('Cached raw page checksum mismatch')
        if state['status']=='complete':
            print(f'Using completed snapshot: {directory}',flush=True)
            return directory
    else:
        state = {'status':'running','source':'openalex_api','config':config,
            'config_fingerprint':fingerprint(config),'started_at':datetime.now(timezone.utc).isoformat(),
            'cursor':'*','pages':[],'records':0,'requests':0,'estimated_cost_usd':0.,
            'pricing_basis':'conservative keyword-search estimate; actual account billing is external'}
    http = session or requests.Session()
    http.headers.update({'Authorization':'Bearer '+key,'User-Agent':'ResearchGraph/0.5 (scholarly-metadata research)'})
    state['status']='running'
    atomic_json(manifest_path,state)
    try:
        while state['records']<config['raw_limit']:
            cursor = state['cursor']
            if cursor is None:
                break
            payload = None
            for attempt in range(config['max_retries']+1):
                if (state['requests']>=config['max_requests'] or
                    (state['requests']+1)*config['estimated_request_cost_usd']>config['max_estimated_cost_usd']+1e-12):
                    raise RuntimeError('Collection request/cost cap reached; cached pages are resumable')
                state['requests']+=1
                state['estimated_cost_usd']=round(state['requests']*config['estimated_request_cost_usd'],6)
                atomic_json(manifest_path,state)
                sleeper(config['min_interval_seconds'])
                try:
                    response=http.get('https://api.openalex.org/works',params={
                        'search':config['search'],'filter':config['filter'],'sort':config['sort'],
                        'per_page':min(config['per_page'],config['raw_limit']-state['records']),
                        'cursor':cursor,'select':FIELDS},timeout=config['timeout_seconds'],allow_redirects=False)
                except requests.RequestException:
                    if attempt==config['max_retries']:
                        raise RuntimeError('OpenAlex network request failed; resume this snapshot later') from None
                    sleeper(min(30,2**attempt))
                    continue
                if response.status_code in (429,500,502,503,504):
                    if attempt==config['max_retries']:
                        raise RuntimeError(f'OpenAlex HTTP {response.status_code}; resume later')
                    retry=response.headers.get('Retry-After','')
                    sleeper(min(60,float(retry)) if retry.replace('.','',1).isdigit() else min(30,2**attempt))
                    continue
                if response.status_code!=200:
                    raise RuntimeError(f'OpenAlex HTTP {response.status_code}; check key activation and source parameters')
                payload=response.json()
                if not isinstance(payload.get('results'),list) or not isinstance(payload.get('meta'),dict):
                    raise RuntimeError('Invalid OpenAlex response schema')
                break
            if payload is None:
                raise RuntimeError('OpenAlex did not return a usable page')
            filename=f'page-{len(state["pages"]):05d}.json.gz'
            temporary=directory/(filename+'.tmp')
            with gzip.open(temporary,'wt',encoding='utf8') as f:
                json.dump(payload,f)
            temporary.replace(directory/filename)
            next_cursor=payload['meta'].get('next_cursor')
            if next_cursor==cursor:
                raise RuntimeError('Source returned a repeated cursor')
            state['pages'].append({'file':filename,'sha256':sha256(directory/filename),
                'records':len(payload['results']),'cursor':cursor,'next_cursor':next_cursor,
                'fetched_at':datetime.now(timezone.utc).isoformat(),
                'source_count':payload['meta'].get('count'),'reported_meta_cost':payload['meta'].get('cost')})
            state['records']+=len(payload['results'])
            state['cursor']=next_cursor if payload['results'] else None
            atomic_json(manifest_path,state)
            print(f'Collected {state["records"]} raw records; estimated API cost ${state["estimated_cost_usd"]:.3f}',flush=True)
        state.update(status='complete',finished_at=datetime.now(timezone.utc).isoformat(),
                     source_exhausted=state['cursor'] is None)
    except Exception as exc:
        state.update(status='interrupted',error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        atomic_json(manifest_path,state)
    return directory


def iter_snapshot(directory):
    directory=Path(directory)
    state=json.loads((directory/'manifest.json').read_text())
    if state['status']!='complete':
        raise ValueError('Snapshot is incomplete; resume collection before building')
    for page in state['pages']:
        if sha256(directory/page['file'])!=page['sha256']:
            raise ValueError('Raw page checksum mismatch')
        with gzip.open(directory/page['file'],'rt',encoding='utf8') as f:
            yield from json.load(f)['results']


def import_snapshot_files(paths, directory, source_settings):
    """Import selected records from supplied JSONL/gzip shards, saving raw pages.

    Local selection is explicit phrase matching, not a reproduction of OpenAlex
    search ranking. Frozen selected pages make downstream replay independent of
    the external shard's continued availability.
    """
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=False)
    state={'status':'running','source':'local_openalex_jsonl','input_paths':[str(Path(p).resolve()) for p in paths],
        'config':source_settings,'pages':[],'records':0,'requests':0,'estimated_cost_usd':0.}
    batch=[]
    def flush():
        filename=f'page-{len(state["pages"]):05d}.json.gz'
        with gzip.open(directory/filename,'wt',encoding='utf8') as f:json.dump({'results':batch},f)
        state['pages'].append({'file':filename,'sha256':sha256(directory/filename),'records':len(batch)})
    try:
        from src.ingestion.openalex import reconstruct_abstract
        import re
        for path in paths:
            opener=gzip.open if str(path).endswith('.gz') else open
            with opener(path,'rt',encoding='utf8') as source:
                for line in source:
                    raw=json.loads(line)
                    text=str(raw.get('title') or '')+' '+str(reconstruct_abstract(raw.get('abstract_inverted_index')) or '')
                    if raw.get('is_retracted') or not 2020<=int(raw.get('publication_year') or 0)<=2026:
                        continue
                    if not re.search(r'retrieval[ -]augmented|large language model|dense retrieval|graph.?rag',text,re.I):
                        continue
                    batch.append(raw);state['records']+=1
                    if len(batch)==100:flush();batch=[]
                    if state['records']>=source_settings['raw_limit']:break
            if state['records']>=source_settings['raw_limit']:break
        if batch:flush()
        state['status']='complete'
    finally:
        atomic_json(directory/'manifest.json',state)
    return directory


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--snapshot',type=Path,action='append')
    args=parser.parse_args()
    if args.snapshot:
        config=yaml.safe_load(Path(args.config or ROOT/'config/tier_s.yaml').read_text())
        result=import_snapshot_files(args.snapshot,args.output or ROOT/'data/raw/tier_s_import',config['source'])
    else:result=collect(args.config,args.output)
    print(f'Raw snapshot: {result}')


if __name__=='__main__':main()
