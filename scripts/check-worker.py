#!/usr/bin/env python3
"""Inspect fresh worker parity and, for B, exercise its actual browser tunnel."""
import argparse,json
from reset_worker import SKILLS, ROOT,PINS,run
p=argparse.ArgumentParser();p.add_argument('run_id');args=p.parse_args()
state=json.loads((ROOT/'private/workers'/args.run_id/'state.json').read_text());worker=state['worker']
assert state['ready']
probe='''import json,pathlib,subprocess
h=pathlib.Path.home()
def output(args):return subprocess.check_output(args,text=True).strip()
auth=subprocess.run([str(h/'ctbench-tools/node_modules/.bin/claude'),'auth','status','--json'],capture_output=True,text=True)
a=json.loads(auth.stdout)
print(json.dumps({'claude':output([str(h/'ctbench-tools/node_modules/.bin/claude'),'--version']),
'node':output(['node','--version']), 'go':output(['go','version']),
'mcp':sorted(json.loads((h/'.claude.json').read_text())['mcpServers']),
'session_files':len(list((h/'.claude').rglob('*.jsonl'))),
'signadot_key_present':(h/'.signadot/config.yaml').exists(),
'kubeconfig_present':(h/'.kube/config').exists(),
'skills_link':str((h/'.claude/skills').resolve()) if (h/'.claude/skills').exists() else None,
'claude_authenticated':a.get('loggedIn',False)}))
'''
data=json.loads(run(['sbx','exec','-i',worker,'python3','-'],input=probe.encode(),capture_output=True).stdout)
assert data['claude'].split()[0]==PINS['worker_claude_code_version']
assert data['session_files']==0 and data['kubeconfig_present'] is False
assert data['mcp']==(['playwright'] if state['arm']=='a' else ['playwright','signadot'])
assert data['signadot_key_present']==(state['arm']=='b')
if state['arm']=='b':
    assert data['skills_link']==str(SKILLS/'skills')
    run(['sbx','cp',ROOT/'scripts/check-browser.mjs',f'{worker}:/tmp/check-browser.mjs'])
    browser=run(['sbx','exec',worker,'python3','-c',
                 'import os,json,pathlib; os.environ.update(json.loads((pathlib.Path.home()/".claude/settings.json").read_text())["env"]); os.execvp("node",["node","/tmp/check-browser.mjs"])'],capture_output=True)
    data['browser']=[json.loads(line) for line in browser.stdout.splitlines()]
    run(['sbx','cp',f'{worker}:/tmp/ctbench-browser-check.png',ROOT/'artifacts'/f'{args.run_id}-browser.png'])
(ROOT/'artifacts'/f'{args.run_id}-checks.json').write_text(json.dumps(data,indent=2)+'\n')
print(json.dumps(data,indent=2))
