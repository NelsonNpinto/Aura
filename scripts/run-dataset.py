"""Run a saved AURA dataset in CI and propagate its quality-gate decision."""
import argparse
import json
import os
import sys
import urllib.request

parser=argparse.ArgumentParser()
parser.add_argument('dataset_id')
parser.add_argument('--base-url',default='http://localhost:8200')
parser.add_argument('--model',default='')
parser.add_argument('--mode',choices=['stored','generate','rag'],default='stored')
args=parser.parse_args()
headers={'Content-Type':'application/json'}
if os.getenv('API_KEY'):
    headers['Authorization']='Bearer '+os.environ['API_KEY']
request=urllib.request.Request(args.base_url+'/api/v1/datasets/'+args.dataset_id+'/run',
    data=json.dumps({'mode':args.mode,'model':args.model}).encode(),headers=headers)
try:
    with urllib.request.urlopen(request,timeout=3600) as response:
        result=json.load(response)
    print(json.dumps(result,indent=2))
    sys.exit(0 if result['passed'] else 1)
except Exception as exc:
    print(f'Dataset run failed: {type(exc).__name__}: {exc}',file=sys.stderr)
    sys.exit(1)
