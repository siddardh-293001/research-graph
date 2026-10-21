"""CI deployment: verify free plan, deploy exact commit, wait for live, smoke-test."""
import json
import os
import time
import urllib.error
import urllib.request


def deploy():
    token=os.environ['RENDER_API_KEY'];service=os.environ['RENDER_SERVICE_ID'];commit=os.environ['GITHUB_SHA']
    def request(path,payload=None):
        data=None if payload is None else json.dumps(payload).encode()
        req=urllib.request.Request('https://api.render.com/v1/'+path,data=data,
                                  headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=45) as response:return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f'Render API returned HTTP {error.code}; see the Render dashboard') from None
    info=request('services/'+service)
    if info.get('serviceDetails',{}).get('plan')!='free':raise ValueError('Refusing to deploy a service outside the free plan')
    deployment=request(f'services/{service}/deploys',{'commitId':commit,'clearCache':'do_not_clear'})
    deploy_id=deployment['id']
    for _ in range(100):
        state=request(f'services/{service}/deploys/{deploy_id}')
        status=state['status']
        print('Deployment:',status,flush=True)
        if status=='live':break
        if status in {'build_failed','update_failed','pre_deploy_failed','canceled','deactivated'}:
            raise RuntimeError('Render deployment did not become live')
        time.sleep(10)
    else:raise TimeoutError('Render deployment exceeded the verification window')
    url=info['serviceDetails']['url']
    def get(path):
        with urllib.request.urlopen(url+path,timeout=90) as response:return json.load(response)
    if get('/readyz')['papers']!=20000:raise ValueError('Live corpus differs from the verified release')
    body=json.dumps({'query':'graph retrieval for multi hop reasoning','mode':'hybrid','top_k':10}).encode()
    req=urllib.request.Request(url+'/api/search',data=body,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=90) as response:
        if not json.load(response)['results']:raise ValueError('Live search returned no papers')
    print('Verified live deployment:',url)


if __name__=='__main__':deploy()
