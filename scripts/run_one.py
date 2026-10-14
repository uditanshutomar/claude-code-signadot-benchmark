#!/usr/bin/env python3
"""One initial session and at most three resumes. Preparation defaults to no execution."""
import argparse, csv, fcntl, hashlib, json, os, pathlib, subprocess, sys, time, uuid
from contextlib import contextmanager
from reset_worker import ROOT, PINS, prepare, run, baseline_state, run_workspace
sys.path.insert(0,str(ROOT/'grader'))
from classify import classify
import collection
from run_evidence import ARCHIVE_SCRIPT, cost_delta, export_summary, inspect_stream, telemetry_problem, verify_archive

FIELDS='run_id task arm rep started_utc ended_utc duration_ms cost_usd num_turns model effort claude_code_version permission_mode hotrod_sha skills_sha session_id declared_done initial_verdict rework_rounds rework_duration_ms rework_cost_usd final_verdict skill_invoked cli_fallback services_touched first_break_seen_utc notes'.split()

def utc(): return time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())

def boot_id(worker):
    return run(['sbx','exec',worker,'cat','/proc/sys/kernel/random/boot_id'],capture_output=True,text=True).stdout.strip()

@contextmanager
def keep_worker(worker):
    # sbx v0.48 auto-stops 30 seconds after the last attached command exits.
    proc=subprocess.Popen(['sbx','exec',worker,'sleep','infinity'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        initial=boot_id(worker)
        if proc.poll() is not None: raise RuntimeError('Could not keep the worker attached')
        yield initial
        if proc.poll() is not None or boot_id(worker)!=initial:
            raise RuntimeError('Worker restarted during the run; retain as HARNESS_ERROR')
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill();proc.wait()

def agent_argv(prompt, session, resume=False):
    return ['/home/agent/ctbench-tools/node_modules/.bin/claude','-p',prompt,
            '--model',PINS['model'],'--effort',PINS['effort'],
            '--permission-mode','bypassPermissions','--output-format','stream-json','--verbose',
            '--settings','/tmp/ctbench-model-settings.json','--setting-sources','user',
            '--strict-mcp-config','--mcp-config','/tmp/ctbench-mcp.json',
            '--resume' if resume else '--session-id',session]

def rework_prompt(grade, timed_out=False):
    # Only what failed and why. Host paths, grader internals and sandbox details stay out.
    import re
    def clean(value):
        if isinstance(value,str):
            value=re.sub(r'\x1b\[[0-9;]*m','',value)
            return value.replace(str(ROOT/'work/grading-source')+'/','').replace(str(ROOT)+'/','')
        if isinstance(value,list): return [clean(v) for v in value]
        if isinstance(value,dict): return {k:clean(v) for k,v in value.items()}
        return value
    feedback={'status':grade.get('grade_status'),'error':grade.get('error'),
              'checks':[{k:c[k] for k in ('mode','status','checks','error','httpFailure') if k in c} for c in grade.get('checks',[])]}
    if grade.get('diagnostics'): feedback['diagnostics']=grade['diagnostics'][-8000:]
    # A run that hit the cap gets rework even if its diff passed; say why, or "CI failed" reads as a contradiction.
    if timed_out: feedback['note']='Your previous session was stopped at the 60-minute limit.'
    return 'CI failed on your change: '+json.dumps(clean(feedback),sort_keys=True)+'. Fix it.'

def rounds(backend, prompt, session):
    """The same loop is exercised by deterministic fixtures and the real backend."""
    records=[]
    for number in range(4):
        agent=backend.agent(prompt,session,number)
        # Retain the diff even on a timeout or model/API failure.
        backend.capture(number)
        # Infrastructure trouble is logged, excluded and rerun; grading it would only spend a sandbox.
        grade=({'grade_status':'HARNESS_ERROR','error':'not graded: '+agent['harness_error']}
               if agent.get('harness_error') else backend.grade(number))
        graded_utc=utc()
        status=grade['grade_status']
        if agent.get('harness_error'): status='HARNESS_ERROR'
        verdict=classify(status,timed_out=agent['timed_out'])
        record={'round':number,'agent':agent,'grade':grade,'verdict':verdict,'graded_utc':graded_utc}
        records.append(record);backend.save(record)
        if verdict in ('VERIFIED_CORRECT','HARNESS_ERROR'): break
        if not agent.get('resumable'):
            record['resume_blocked']='No saved session available';backend.save(record);break
        prompt=rework_prompt(grade,timed_out=agent['timed_out'])
    return records

def capture_diff(work):
    # A temporary index captures commits and new files without changing the agent's index.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        env=dict(os.environ,GIT_INDEX_FILE=str(pathlib.Path(tmp)/'index'))
        subprocess.run(['git','-C',str(work),'read-tree',PINS['hotrod_sha']],env=env,check=True)
        subprocess.run(['git','-C',str(work),'add','-A','--','.'],env=env,check=True)
        return subprocess.check_output(['git','-C',str(work),'diff','--cached','--binary',PINS['hotrod_sha']],env=env)

class LiveBackend:
    def __init__(self,state,out,task,mode="offline-smoke"): self.state=state;self.out=out;self.task=task;self.previous_cost=None;self.mode=mode
    def agent(self,prompt,session,number):
        worker=self.state['worker'];work=self.state['workspace']
        # Reapply after any VM restart, including Docker-injected MCP configuration.
        run(['sbx','exec','-i',worker,'bash','-s'],input=(ROOT/'scripts/configure-worker.sh').read_bytes())
        if self.state['arm']=='b': run(['bash',ROOT/'scripts/connect-worker.sh',worker])
        settings=json.loads((ROOT/'config/model-settings.json').read_text())
        run(['sbx','exec','-i',worker,'bash','-c','umask 077; cat > /tmp/ctbench-model-settings.json'],input=json.dumps(settings).encode())
        run(['sbx','exec',worker,'python3','-c',
             'import json,pathlib; h=pathlib.Path.home(); p=pathlib.Path("/tmp/ctbench-mcp.json"); p.write_text(json.dumps({"mcpServers":json.loads((h/".claude.json").read_text())["mcpServers"]}))'])
        folder=self.out/f'round-{number}';folder.mkdir(mode=0o700,exist_ok=False)
        (folder/'prompt.txt').write_text(prompt)
        run(['sbx','cp',ROOT/'scripts/worker-command.py',f'{worker}:/tmp/ctbench-command.py'])
        marker=f'/tmp/ctbench-round-{number}.json'
        debug_path=f'/tmp/ctbench-round-{number}-debug.log'
        seconds=PINS['rework_timeout_seconds' if number else 'initial_timeout_seconds']
        if self.mode!="offline-smoke":
            collection.activate(worker,collection.environment(self.state["arm"],self.task,"initial" if number==0 else "rework",collection.credentials()))
        start=time.monotonic();started=utc();host_timeout=False
        with (folder/'transcript.jsonl').open('wb') as transcript,(folder/'stderr.log').open('wb') as errors:
            try:
                cp=subprocess.run(['python3',str(ROOT/'scripts/setup-only.py'),'sbx','exec',
                                   '--env-file',str(ROOT/'private/claude-subscription.env'),'-w',work,worker,
                                   'env','-u','ANTHROPIC_API_KEY','-u','ANTHROPIC_AUTH_TOKEN','-u','ANTHROPIC_BASE_URL',
                                   'python3','/tmp/ctbench-command.py','--seconds',str(seconds),'--record',marker,
                                   *agent_argv(prompt,session,number>0),'--debug-file',debug_path],stdout=transcript,stderr=errors,timeout=seconds+90)
                exit_code=cp.returncode
            except subprocess.TimeoutExpired:
                host_timeout=True;exit_code=None
                run(['sbx','stop',worker],check=False,timeout=30,stdout=subprocess.DEVNULL)
            finally:
                duration_ms=round((time.monotonic()-start)*1000);ended=utc()
                if self.mode!='offline-smoke': collection.deactivate(worker)
        termination={}
        if not host_timeout:
            run(['sbx','cp',f'{worker}:{debug_path}',folder/'claude-debug.log'],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
            if self.mode!='offline-smoke':
                run(['sbx','cp',f'{worker}:{collection.RELAY_LOG}',folder/'telemetry-exports.jsonl'],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
            marker_result=run(['sbx','exec',worker,'cat',marker],check=False,capture_output=True,timeout=30)
            if marker_result.returncode==0: termination=json.loads(marker_result.stdout)
        if termination.get('duration_ms') is not None: duration_ms=termination['duration_ms']
        (folder/'termination.json').write_text(json.dumps(termination,indent=2)+'\n')
        result,timed_out,error=inspect_stream((folder/'transcript.jsonl').read_text(errors='replace'),session,PINS['model'],exit_code,termination)
        resumable=False
        if not host_timeout:
            try:
                archive=folder/'claude-session.tar.gz'
                with archive.open('wb') as output:
                    run(['sbx','exec','-i',worker,'python3','-',session],input=ARCHIVE_SCRIPT.encode(),stdout=output,timeout=60)
                manifest=verify_archive(archive,session)
                (folder/'session-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
                resumable=True
            except Exception as failure:
                error='Session evidence export failed: '+str(failure)
        if host_timeout: error='Host connection exceeded deadline allowance; worker retained'
        telemetry=export_summary(folder/'telemetry-exports.jsonl')
        if self.mode!='offline-smoke' and not error and telemetry_problem(telemetry):
            # Incomplete telemetry invalidates the measurement, not the code: log, exclude and rerun.
            error='Telemetry incomplete: '+telemetry_problem(telemetry)
        if error:
            diagnostic=run(['sbx','inspect',worker],capture_output=True,check=False,timeout=30)
            (folder/'worker-diagnostic.json').write_bytes(diagnostic.stdout)
        total=result.get('total_cost_usd')
        delta=cost_delta(total,self.previous_cost,initial=number==0)
        self.previous_cost=total
        record={'started_utc':started,'ended_utc':ended,'duration_ms':duration_ms,
                'exit_code':exit_code,'timed_out':timed_out,'resumable':resumable,
                'cost_usd':delta,'cumulative_cost_usd':total,'num_turns':result.get('num_turns'),
                'raw_usage':result.get('usage'),'model_usage':result.get('modelUsage'),
                'cost_convention':'cumulative result totals; per-round delta (verified on a resumed session)',
                'response_models':sorted(result.get('modelUsage',{})),'harness_error':error,
                'telemetry_exports':telemetry}
        (folder/'agent.json').write_text(json.dumps(record,indent=2)+'\n');return record
    def capture(self,number):
        patch=capture_diff(self.state['workspace'])
        (self.out/f'round-{number}'/'submission.diff').write_bytes(patch)
        (self.out/'submission.diff').write_bytes(patch)
        (self.out/'submission.json').write_text(json.dumps({'task':self.task,'base_sha':PINS['hotrod_sha']})+'\n')
    def grade(self,number):
        # Preserve the agent VM and session for rework. Its services may still be running.
        before=boot_id(self.state['worker'])
        pointer=self.out/'latest-grade.json'
        previous=pointer.read_bytes() if pointer.exists() else None
        cp=subprocess.run([str(ROOT/'grade.sh'),self.out.name],stdout=subprocess.DEVNULL)
        after=boot_id(self.state['worker'])
        (self.out/f'round-{number}'/'worker-continuity.json').write_text(json.dumps({'before':before,'after':after,'unchanged':before==after})+'\n')
        if before!=after: return {'grade_status':'HARNESS_ERROR','error':'Worker restarted during grading'}
        if not pointer.exists() or pointer.read_bytes()==previous:
            return {'grade_status':'HARNESS_ERROR','error':'Grader did not write a new result','exit_code':cp.returncode}
        path=ROOT/json.loads(pointer.read_text())['path']/'result.json'
        grade=json.loads(path.read_text())
        if self.state.get('baseline'):
            current=baseline_state()
            (self.out/f'round-{number}'/'baseline-after-grade.json').write_text(json.dumps(current,indent=2)+'\n')
            if current!=self.state['baseline']:
                return {'grade_status':'HARNESS_ERROR','error':'Baseline health changed during the run; inspect pod identities and restart counts'}
        patch=self.out/'submission.diff'
        if grade.get('patch_sha256')!=hashlib.sha256(patch.read_bytes()).hexdigest():
            return {'grade_status':'HARNESS_ERROR','error':'Grader result does not match this submission'}
        # A compiler error must reach the agent, not just a host-only log filename.
        import re
        match=re.search(r'see (\d+\.log)',grade.get('error',''))
        if match:
            diagnostic=path.parent/match[1]
            if diagnostic.exists(): grade['diagnostics']=diagnostic.read_text(errors='replace')
        return grade
    def save(self,record):
        (self.out/f'round-{record["round"]}'/'outcome.json').write_text(json.dumps(record,indent=2)+'\n')

def append_ledger(row):
    path=ROOT/'ledger.csv';exists=path.exists()
    with path.open('a',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS); 
        if not exists: writer.writeheader()
        writer.writerow({key:row.get(key,'') for key in FIELDS})

def summarize(row,records):
    if not records: return
    first=records[0];last=records[-1]
    row.update(started_utc=first['agent']['started_utc'],initial_verdict=first['verdict'],
               final_verdict=last['verdict'],rework_rounds=len(records)-1,
               duration_ms=first['agent']['duration_ms'],cost_usd=first['agent']['cost_usd'],
               num_turns=first['agent']['num_turns'],
               rework_duration_ms=sum(r['agent']['duration_ms'] for r in records[1:]))
    costs=[r['agent']['cost_usd'] for r in records[1:]]
    row['rework_cost_usd']=sum(costs) if all(c is not None for c in costs) else ''

def release_completed_worker(state,out):
    # Only remove a completed run's VM after its final source diff is saved.
    work=pathlib.Path(state['workspace']).resolve()
    expected=run_workspace(state['run_id']).resolve()
    if work!=expected or not (out/'submission.diff').is_file():
        raise RuntimeError('Cannot release a worker without its saved submission')
    if capture_diff(work)!=(out/'submission.diff').read_bytes():
        raise RuntimeError('Worker changed after capture; retain it for inspection')
    manifests=sorted(out.glob('round-*/session-manifest.json'))
    outcomes=sorted(out.glob('round-*/outcome.json'))
    if not manifests or len(manifests)!=len(outcomes):
        raise RuntimeError('Session evidence incomplete; retain worker')
    for manifest in manifests:
        expected_manifest=json.loads(manifest.read_text())
        actual=verify_archive(manifest.parent/'claude-session.tar.gz',state['session_id'])
        if actual!=expected_manifest: raise RuntimeError('Session archive changed; retain worker')
    if state.get('devbox_id'):
        from reset_worker import signadot_env
        run(['signadot','devbox','delete',state['devbox_id']],stdout=subprocess.DEVNULL,env=signadot_env())
    run(['sbx','rm','--force',state['worker']],stdout=subprocess.DEVNULL)
    # These two generated directories dominate disk use. Keep the checkout and evidence.
    import shutil
    for relative in ('services/frontend/react_app/node_modules','dist'):
        path=work/relative
        if path.is_symlink(): path.unlink()
        elif path.is_dir(): shutil.rmtree(path)

def main():
    p=argparse.ArgumentParser();p.add_argument('task',choices=['t1','t2']);p.add_argument('arm',choices=['a','b']);p.add_argument('rep',type=int)
    p.add_argument('--execute',action='store_true');p.add_argument('--mode',choices=collection.MODES,default='offline-smoke');args=p.parse_args()
    if not 1<=args.rep<=10: p.error('rep must be 1..10')
    prompt=(ROOT/'prompts'/f'{args.task}-{args.arm}.txt').read_text()
    if not args.execute:
        print(json.dumps({'execute':False,'task':args.task,'arm':args.arm,'rep':args.rep,
                          'initial':agent_argv(prompt,'<fresh UUID>'),'max_rework_rounds':3,
                          'initial_timeout_seconds':PINS['initial_timeout_seconds'],
                          'rework_timeout_seconds':PINS['rework_timeout_seconds'],'mode':args.mode,'telemetry':'disabled' if args.mode=='offline-smoke' else 'requires explicit approval'},indent=2));return
    approval=ROOT/'private/model-run-approval.json'
    expected={'mode':args.mode,'task':args.task,'arm':args.arm,'rep':args.rep,'approved':True}
    if not approval.exists() or json.loads(approval.read_text()) != expected:
        sys.exit('Model execution is locked. This command needs explicit approval for this run and collection mode. No model call was made.')
    if args.mode!='offline-smoke': collection.credentials()
    if args.mode=='primary':
        freeze=ROOT/'private/protocol-freeze.json'
        if not freeze.exists(): sys.exit('Primary collection locked: smoke evidence and protocol freeze required')
        from protocol import verify_freeze
        verify_freeze(json.loads(freeze.read_text()))
    credentials=ROOT/'private/claude-subscription.env'
    if not credentials.exists() or credentials.stat().st_mode & 0o077:
        sys.exit('A private (0600) Claude subscription token file is required. No model call was made.')
    lines=credentials.read_text().strip().splitlines()
    if len(lines)!=1 or not lines[0].startswith('CLAUDE_CODE_OAUTH_TOKEN=') or not lines[0].split('=',1)[1]:
        sys.exit('Use only CLAUDE_CODE_OAUTH_TOKEN from the existing subscription.')
    with (ROOT/'private/runner.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        run_id='r'+uuid.uuid4().hex[:12];session=str(uuid.uuid4())
        out=ROOT/'runs'/run_id;out.mkdir(mode=0o700)
        row=dict(run_id=run_id,task=args.task,arm=args.arm,rep=args.rep,started_utc=utc(),
                 model=PINS['model'],effort=PINS['effort'],claude_code_version=PINS['worker_claude_code_version'],
                 permission_mode=PINS['permission_mode'],hotrod_sha=PINS['hotrod_sha'],
                 skills_sha=PINS['agent-skills_sha'] if args.arm=='b' else '',session_id=session,
                 initial_verdict='HARNESS_ERROR',final_verdict='HARNESS_ERROR',notes=('primary' if args.mode=='primary' else args.mode+'; excluded from primary results'))
        state=None
        try:
            with (ROOT/'private/grader.lock').open('w') as grade_lock:
                fcntl.flock(grade_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                state=prepare(run_id,args.arm)
                state['session_id']=session
            auth=run(['sbx','exec','--env-file',credentials,state['worker'],
                      'env','-u','ANTHROPIC_API_KEY','-u','ANTHROPIC_AUTH_TOKEN','-u','ANTHROPIC_BASE_URL',
                      '/home/agent/ctbench-tools/node_modules/.bin/claude','auth','status','--json'],capture_output=True)
            if not json.loads(auth.stdout).get('loggedIn'): raise RuntimeError('Claude subscription authentication is unavailable')
            approval.unlink() # One approval permits one model session, including prescribed rework.
            with keep_worker(state['worker']):
                records=rounds(LiveBackend(state,out,args.task,args.mode),prompt,session)
            row['notes']+='; costs are API-equivalent; transcript observations require review'
        except BaseException as error:
            (out/'harness-error.txt').write_text(str(error)+'\n')
            row['notes']+='; '+str(error)
            raise
        finally:
            completed=[json.loads(path.read_text()) for path in sorted(out.glob('round-*/outcome.json'))]
            summarize(row,completed)
            if (out/'harness-error.txt').exists(): row['final_verdict']='HARNESS_ERROR'
            if state:
                if args.mode!='offline-smoke':
                    try: collection.deactivate(state['worker'])
                    except Exception as error:
                        row['final_verdict']='HARNESS_ERROR';row['notes']+='; collection cleanup failed: '+str(error)
                if args.arm=='b': subprocess.run(['sbx','exec',state['worker'],'signadot','local','disconnect'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                subprocess.run(['sbx','stop',state['worker']],stdout=subprocess.DEVNULL)
                if row['final_verdict']!='HARNESS_ERROR' and completed:
                    try: release_completed_worker(state,out)
                    except Exception as error:
                        row['final_verdict']='HARNESS_ERROR';row['notes']+='; cleanup failed: '+str(error)
            from datetime import datetime
            passed=next((r for r in completed if r['verdict']=='VERIFIED_CORRECT'),None)
            timings={'time_to_verified_ms':None,'includes':'agent rounds and grading; excludes preparation and cleanup'}
            if passed and completed:
                timings['time_to_verified_ms']=round((datetime.fromisoformat(passed['graded_utc'])-datetime.fromisoformat(completed[0]['agent']['started_utc'])).total_seconds()*1000)
            (out/'timing.json').write_text(json.dumps(timings,indent=2)+'\n')
            row['ended_utc']=utc();append_ledger(row)
            (out/'run.json').write_text(json.dumps(row,indent=2)+'\n')

if __name__=='__main__': main()
