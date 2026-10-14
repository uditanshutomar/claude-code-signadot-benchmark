#!/usr/bin/env python3
"""Prepare one fresh worker. Never starts Claude or enables telemetry."""
import argparse, hashlib, json, os, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PINS = json.loads((ROOT/'config/pins.json').read_text())
KUBE = ['kubectl','--context','minikube','-n','ctbench-hotrod']
# Workers mount host paths unchanged, so agents see these paths. Keep them neutral.
SKILLS = pathlib.Path.home()/'src/agent-skills'

SIGNADOT_KEY = ROOT/'private/signadot-api-key'

def signadot_env(key_file=SIGNADOT_KEY):
    # Host Signadot calls use the pinned org and the benchmark's own key, not the user's global CLI login.
    return dict(os.environ,SIGNADOT_ORG=PINS['signadot_org'],SIGNADOT_API_KEY=key_file.read_text().strip())

def worker_config(key_file=SIGNADOT_KEY):
    return 'org: '+PINS['signadot_org']+'\napi_key: '+key_file.read_text().strip()+'\n'

def run_workspace(run_id):
    return pathlib.Path.home()/'src'/run_id/'hotrod'

def run(argv, **kw):
    kw.setdefault('check',True)
    return subprocess.run(['python3',str(ROOT/'scripts/setup-only.py'),*map(str,argv)],**kw)

def namespaces(value):
    if isinstance(value,dict):
        result={value['namespace']} if isinstance(value.get('namespace'),str) else set()
        for item in value.values(): result |= namespaces(item)
        return result
    if isinstance(value,list):
        return set().union(*(namespaces(item) for item in value)) if value else set()
    return set()

def cleanup_sandboxes():
    # The dedicated namespace is the ownership boundary. Never delete another namespace's sandbox.
    items=json.loads(run(['signadot','sandbox','list','-o','json'],capture_output=True,env=signadot_env()).stdout)
    deleted=[]
    for item in items:
        spec=item.get('spec',{}); spaces=namespaces(spec)
        if spec.get('cluster')=='minikube' and spaces=={'ctbench-hotrod'}:
            run(['signadot','sandbox','delete',item['name']],stdout=subprocess.DEVNULL,env=signadot_env())
            deleted.append(item['name'])
        elif 'ctbench-hotrod' in spaces:
            raise RuntimeError('Sandbox spans the benchmark and another namespace; inspect before reset')
    remaining=json.loads(run(['signadot','sandbox','list','-o','json'],capture_output=True,env=signadot_env()).stdout)
    if any('ctbench-hotrod' in namespaces(item.get('spec',{})) for item in remaining):
        raise RuntimeError('Benchmark sandbox cleanup is incomplete')
    pods=json.loads(run(KUBE+['get','pods','-l','signadot.com/sandbox-id','-o','json'],capture_output=True).stdout)
    if pods['items']:
        run(KUBE+['wait','--for=delete','pod','-l','signadot.com/sandbox-id','--timeout=120s'])
    return deleted

def baseline_state():
    pods=json.loads(run(KUBE+['get','pods','-o','json'],capture_output=True,timeout=30).stdout)
    baseline=[p for p in pods['items'] if not p['metadata'].get('labels',{}).get('signadot.com/sandbox-id')]
    if len(baseline)!=7 or any(not p['status'].get('containerStatuses') or
       not all(c.get('ready') for c in p['status']['containerStatuses']) for p in baseline):
        raise RuntimeError('Benchmark baseline is not ready')
    expected="1\tMy Home\t231,773\n123\tRachel's Floral Designs\t115,277\n392\tTrom Chocolatier\t577,322\n567\tAmazing Coffee Roasters\t211,653\n731\tJapanese Desserts\t728,326"
    locations=run(KUBE+['exec','mysql-0','--','mariadb','-uroot','-pabc','-N','location','-e',
                       'SELECT id,name,coordinates FROM locations ORDER BY id'],capture_output=True,text=True,timeout=30).stdout.strip()
    if locations!=expected: raise RuntimeError('Seeded locations changed; inspect before resetting or running')
    return {'locations_verified':True,'pods':[{'name':p['metadata']['name'],'uid':p['metadata']['uid'],
            'containers':[{'name':c['name'],'restarts':c['restartCount'],'image_id':c.get('imageID')}
                          for c in p['status']['containerStatuses']]} for p in sorted(baseline,key=lambda p:p['metadata']['name'])]}

def prepare(run_id, arm):
    if not re.fullmatch(r'r[a-f0-9]{12}',run_id): raise ValueError('Use an opaque r + 12 hex run ID')
    templates=json.loads(run(['sbx','template','ls','--json'],capture_output=True).stdout)
    assert any(t['id']==PINS['common_worker_template_short_id'] and
               t['repository'].endswith('/ctbench-common') and t['tag']=='20261013' for t in templates), 'Pinned common template is missing'
    workers=json.loads(run(['sbx','ls','--json'],capture_output=True).stdout)
    if any(w['name'].startswith('ctbench-') and w['status']=='running' for w in workers):
        raise RuntimeError('Stop the previous benchmark worker before resetting shared benchmark data')
    out=ROOT/'private/workers'/run_id
    out.mkdir(parents=True,exist_ok=False)
    worker='ctbench-'+run_id
    work=run_workspace(run_id)
    state={'run_id':run_id,'worker':worker,'workspace':str(work),'arm':arm,'ready':False}
    state_path=out/'state.json'
    def save(): state_path.write_text(json.dumps(state,indent=2)+'\n')
    save()
    try:
        state['deleted_sandboxes']=cleanup_sandboxes()
        state['baseline']=baseline_state();save()
        run(KUBE+['exec','-i','mysql-0','--','mariadb','-uroot','-pabc','location'],
            input=b'DROP TABLE IF EXISTS ride_history;\n',stdout=subprocess.DEVNULL)
        work.parent.mkdir(parents=True,exist_ok=False)
        run(['git','clone','--quiet','--no-hardlinks',ROOT/'work/hotrod',work])
        run(['git','-C',work,'checkout','--quiet','--detach',PINS['hotrod_sha']])
        run(['git','-C',work,'remote','set-url','origin','https://github.com/signadot/hotrod.git'])
        run(['git','-C',work,'remote','set-url','--push','origin','disabled://human-approval-required'])
        args=['sbx','create','--name',worker,'--template',PINS['common_worker_template'],
              '--cpus','2','--memory','4g','--skills','off',
              '--deny-network','codetelemetry.com:443','--deny-network','**.codetelemetry.com:443',
              'claude',str(work)]
        if arm=='b': args.append(str(SKILLS)+':ro')
        run(args)
        for host in json.loads((ROOT/'config/browser-hosts.json').read_text()):
            run(['sbx','policy','allow','network','--sandbox',worker,host,'--method','GET'],stdout=subprocess.DEVNULL)
        # A template may contain CLI caches. Keep package caches, remove all agent state.
        run(['sbx','exec','-i',worker,'python3','-'],input=b'''import pathlib,shutil,os
h=pathlib.Path.home()
def clear(p):
    if p.is_dir() and not p.is_symlink():
        if os.path.ismount(p):
            for child in p.iterdir():
                if child.name != 'lost+found': clear(child)
        else: shutil.rmtree(p)
    else: p.unlink()
p=h/'.claude'
if p.exists():
    for child in p.iterdir(): clear(child)
else: p.mkdir()
(h/'.claude.json').unlink(missing_ok=True)
assert not (h/'.signadot/config.yaml').exists()
assert not (h/'.kube/config').exists()
assert not list(p.rglob('*.jsonl'))
''')
        if arm=='b':
            skills=SKILLS
            assert run(['git','-C',skills,'rev-parse','HEAD'],capture_output=True,text=True).stdout.strip()==PINS['agent-skills_sha']
            assert not run(['git','-C',skills,'status','--porcelain'],capture_output=True,text=True).stdout.strip()
            archive=ROOT/'artifacts/downloads/signadot-cli_mcp_linux_arm64.tar.gz'
            assert hashlib.sha256(archive.read_bytes()).hexdigest()==PINS['signadot_linux_arm64_archive_sha256']
            run(['sbx','cp',archive,f'{worker}:/tmp/signadot.tar.gz'])
            run(['sbx','exec',worker,'bash','-c','set -eu; sudo tar -xzf /tmp/signadot.tar.gz -C /usr/local/bin signadot; sudo rm /tmp/signadot.tar.gz'])
            # Only the benchmark's Signadot API key is copied, never browser auth or unrelated config.
            config=worker_config()
            run(['sbx','exec','-i',worker,'bash','-c','mkdir -p "$HOME/.signadot"; umask 077; cat > "$HOME/.signadot/config.yaml"'],input=config.encode())
            for host in ('api.signadot.com:443','mcp.signadot.com:443'):
                run(['sbx','policy','allow','network','--sandbox',worker,host],stdout=subprocess.DEVNULL)
            run(['sbx','exec',worker,'ln','-s',str(skills/'skills'),'/home/agent/.claude/skills'])
        else:
            run(['sbx','exec',worker,'bash','-c','! command -v signadot && test ! -e "$HOME/.claude/skills"'])
        run(['sbx','exec','-i',worker,'bash','-s'],input=(ROOT/'scripts/configure-worker.sh').read_bytes())
        # Apply the same package prewarming to both arms, outside the agent clock.
        with (out/'prewarm.log').open('wb') as log:
            run(['sbx','exec','-w',work,worker,'bash','-c',
                 'export PATH="$HOME/ctbench-tools/node_modules/.bin:$PATH" GOTOOLCHAIN=go1.27.1 GOTELEMETRY=off; '
                 'go mod download && cd services/frontend/react_app && yarn install --frozen-lockfile --non-interactive'],
                stdout=log,stderr=subprocess.STDOUT,timeout=600)
        for domain in ('codetelemetry.com:443','ingest.codetelemetry.com:443'):
            result=json.loads(run(['sbx','policy','check','network','--sandbox',worker,'--json',domain],capture_output=True,check=False).stdout)
            assert result['allowed'] is False and result['deny_kind']=='explicit'
        if arm=='b':
            run(['bash',ROOT/'scripts/connect-worker.sh',worker])
            status=json.loads(run(['sbx','exec',worker,'signadot','local','status','-o','json'],capture_output=True).stdout)
            state['devbox_id']=status['devboxSession']['devboxId']
        run(['sbx','exec',worker,'bash','-c','export PATH="$HOME/ctbench-tools/node_modules/.bin:$PATH"; timeout 40 claude mcp list'])
        state['ready']=True;save();return state
    except BaseException as error:
        state['error']=str(error);save()
        # Retain the failed worker and checkout for diagnosis; do not erase evidence.
        subprocess.run(['sbx','stop',worker],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        raise

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run_id');p.add_argument('arm',choices=['a','b']);a=p.parse_args()
    import fcntl
    with (ROOT/'private/runner.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with (ROOT/'private/grader.lock').open('w') as grade_lock:
            fcntl.flock(grade_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            print(json.dumps(prepare(a.run_id,a.arm),indent=2))
