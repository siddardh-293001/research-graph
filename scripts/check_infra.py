"""Offline checks of deployment configuration; never provision cloud resources."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import hcl2
from hcl2.utils import SerializationOptions
import jsonschema
import yaml

ROOT=Path(__file__).resolve().parents[1]


def check():
    config=yaml.safe_load((ROOT/'render.yaml').read_text())
    services=config['services']
    if len(services)!=1 or services[0]['plan']!='free' or config.get('databases'):
        raise ValueError('Deployment must use one free web service and no paid database')
    if services[0]['healthCheckPath']!='/readyz' or services[0]['autoDeployTrigger']!='off':
        raise ValueError('Readiness or verification-before-deploy policy changed')
    schema=ROOT/'infra/render/render.schema.json'
    jsonschema.validate(config,json.loads(schema.read_text()))
    with (ROOT/'infra/render/main.tf').open() as source:
        infra=hcl2.load(source, serialization_options=SerializationOptions(strip_string_quotes=True))
    resources=infra['resource']
    service=next(row['render_web_service']['demo'] for row in resources if 'render_web_service' in row)
    if service['plan']!='free' or service['num_instances']!=1 or service.get('disk'):
        raise ValueError('Terraform violates the free-plan policy')
    terraform=shutil.which('terraform') or str(ROOT/'build/tooling/terraform')
    result=subprocess.run([terraform,'validate','-json'],cwd=ROOT/'infra/render',capture_output=True,text=True,timeout=60)
    if result.returncode:raise ValueError('Terraform validation failed: '+result.stdout)
    return {'passed':True,'blueprint_schema_valid':True,'terraform_valid':json.loads(result.stdout)['valid'],
            'plan':'free','instances':1,'hosted_database':False,'cloud_mutations':False,
            'container_runtime_available':shutil.which('docker') is not None}


if __name__=='__main__':
    result=check()
    if len(sys.argv)>1:Path(sys.argv[1]).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
