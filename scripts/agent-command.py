#!/usr/bin/env python3
"""Print the planned argument vector. This command never starts Claude."""
import argparse,json,pathlib
from run_one import agent_argv
root=pathlib.Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('task',choices=['t1','t2']);p.add_argument('arm',choices=['a','b']);args=p.parse_args()
pins=json.loads((root/'config/pins.json').read_text())
settings=json.loads((root/'config/model-settings.json').read_text())
assert pins['model']==settings['model'] and pins['effort']==settings['effortLevel']
# Deployment paths are inside the future fresh run worker.
command=agent_argv((root/'prompts'/f'{args.task}-{args.arm}.txt').read_text(),'<fresh UUID>')
print(json.dumps({'execute':False,'argv':command,'timeout_seconds':pins['initial_timeout_seconds'],'billing':'existing Claude subscription','telemetry':'disabled during preparation'},indent=2))
