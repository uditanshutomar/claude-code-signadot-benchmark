#!/usr/bin/env python3
"""Grade one opaque submission ID. No arm or agent transcript enters this process."""
import fcntl, hashlib, json, os, pathlib, re, shutil, subprocess, sys, time, traceback

ROOT = pathlib.Path(__file__).resolve().parents[1]
PINS = json.loads((ROOT / 'config/pins.json').read_text())
SOURCE = ROOT / 'work/grading-source'
BUILDER = 'ctbench-grader-build'
WORKER = 'ctbench-setup-b'
KUBE = ['kubectl', '--context', PINS['cluster'], '-n', PINS['namespace']]

class CandidateFailure(Exception): pass

def apply_failure(output):
    # The sandbox spec comes from the grader, so an HTTP error from the Signadot API (auth, quota, outage) is
    # infrastructure. A sandbox that never becomes ready means the candidate's build does not start.
    return 'harness' if re.search(r'Error: [45]\d\d ', output) else 'candidate'

def history_count_failure(output):
    # The prompt asks for a ride_history table; its absence is the candidate's, other errors are infrastructure.
    return 'candidate' if re.search(r"ERROR 1146|ride_history' doesn't exist", output) else 'harness'

def main(run_id):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,35}', run_id): raise ValueError('Invalid opaque run ID')
    run = ROOT / 'runs' / run_id
    submission = json.loads((run / 'submission.json').read_text())
    if set(submission) != {'task', 'base_sha'} or submission['task'] not in ('t1','t2'):
        raise ValueError('Submission metadata must contain only task and base_sha; no arm')
    if submission['base_sha'] != PINS['hotrod_sha']: raise ValueError('Wrong base SHA')
    patch = (run / 'submission.diff').read_bytes()
    out = run / ('grade-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))
    out.mkdir(parents=True, exist_ok=False)
    suffix = hashlib.sha256((run_id + str(time.time_ns())).encode()).hexdigest()[:12]
    sandbox = 'ctg-' + suffix
    database = 'ctg_' + suffix
    image = 'ctbench-grade:' + suffix
    result = {'run_id':run_id, 'task':submission['task'], 'base_sha':PINS['hotrod_sha'],
              'patch_sha256':hashlib.sha256(patch).hexdigest(), 'grade_status':'HARNESS_ERROR',
              'checks':[], 'sandbox':sandbox, 'database':database, 'cleanup':{},
              'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
    test_script=(ROOT/'grader/check.mjs').read_bytes()
    parse_script=(ROOT/'grader/parse.mjs').read_bytes()
    result['grader_sha256']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('grade.sh','grader/grade.py','grader/check.mjs','grader/parse.mjs','config/pins.json','scripts/setup-only.py','scripts/start-setup-worker.sh','scripts/configure-worker.sh','config/known-browser-errors.json')}
    (out/'check.mjs').write_bytes(test_script)
    (out/'parse.mjs').write_bytes(parse_script)
    step_no = 0
    def command(args, *, data=None, timeout=180, check=True, candidate=False):
        nonlocal step_no
        step_no += 1
        log = out / f'{step_no:02d}.log'
        with (out/'commands.jsonl').open('a') as ledger:
            ledger.write(json.dumps({'step':step_no,'argv':[str(x) for x in args],'timeout_seconds':timeout})+'\n')
        try:
            cp=subprocess.run([str(x) for x in args],input=data,capture_output=True,timeout=timeout)
        except subprocess.TimeoutExpired as e:
            log.write_bytes((e.stdout or b'')+(e.stderr or b''))
            raise (CandidateFailure if candidate else RuntimeError)(f'Timeout in {args[0]}; see {log.name}')
        log.write_bytes((f'git archive: {len(cp.stdout)} bytes\n'.encode() if 'archive' in [str(a) for a in args] else cp.stdout)+b'\n'+cp.stderr)
        if check and cp.returncode:
            raise (CandidateFailure if candidate else RuntimeError)(f'{args[0]} exited {cp.returncode}; see {log.name}')
        return cp
    def sql(statement):
        return command(KUBE+['exec','-i','mysql-0','--','mariadb','-uroot','-pabc','-N'],data=statement.encode())
    def sd(args, **kw):
        return command(['sbx','exec',WORKER,'signadot']+args,**kw)
    def apply(spec):
        cp=command(['sbx','exec','-i',WORKER,'bash','-c',
                 'cat > /tmp/ctbench-grade.json; signadot sandbox apply -f /tmp/ctbench-grade.json --wait-timeout 120s -o json'],
                data=json.dumps(spec).encode(),timeout=145,check=False,candidate=True)
        if cp.returncode:
            kind=apply_failure((cp.stdout+cp.stderr).decode(errors='replace'))
            raise (CandidateFailure if kind=='candidate' else RuntimeError)(f'sandbox apply failed ({kind}); see {step_no:02d}.log')
        return json.loads(sd(['sandbox','get',sandbox,'-o','json']).stdout)
    forwards=[]
    def forward(target, port):
        path=out/f'port-forward-{len(forwards)}.log'
        log=path.open('wb')
        proc=subprocess.Popen(KUBE+['port-forward','--address','127.0.0.1',target,f':{port}'],stdout=log,stderr=subprocess.STDOUT)
        forwards.append((proc,log))
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            content=path.read_text()
            match=re.search(r'Forwarding from 127\.0\.0\.1:(\d+)',content)
            if match:return 'http://127.0.0.1:'+match[1]
            if proc.poll() is not None:raise RuntimeError('Port-forward failed: '+path.name)
            time.sleep(.2)
        raise RuntimeError('Port-forward startup timed out')
    made_db=False
    attempted_sandbox=False
    try:
        # A lock prevents concurrent graders from replacing the shared build checkout.
        command([ROOT/'scripts/start-setup-worker.sh','b'],timeout=180)
        baseline=json.loads(command(['sbx','exec',WORKER,'curl','--noproxy','*','-fsS','--max-time','20',
                         f'http://frontend.{PINS["namespace"]}.svc:8080/splash']).stdout)
        if len(baseline.get('Locations',[])) != 5: raise RuntimeError('Baseline unavailable before grading')
        command(KUBE+['get','pod','mysql-0'])
        command(['sbx','exec',WORKER,'signadot','local','disconnect'])
        command(['sbx','stop',WORKER])
        # Only this fixed, dedicated scratch checkout is replaced. Reference repos are never edited.
        for entry in SOURCE.iterdir():
            if entry.is_dir() and not entry.is_symlink(): shutil.rmtree(entry)
            else: entry.unlink()
        archive=command(['git','-C',ROOT/'work/hotrod','archive',PINS['hotrod_sha']]).stdout
        command(['tar','-xf','-','-C',SOURCE],data=archive)
        command(['git','init','-q',SOURCE])
        command(['git','-C',SOURCE,'add','.'])
        # Temporary index is only a base for patch application; no commit or author is needed.
        if patch:
            command(['git','-C',SOURCE,'apply','--check','-'],data=patch,candidate=True)
            command(['git','-C',SOURCE,'apply','-'],data=patch,candidate=True)
        build="""set -eu
export PATH="$HOME/ctbench-tools/node_modules/.bin:$HOME/go/bin:$PATH"
export GOTOOLCHAIN=go1.27.1 GOTELEMETRY=off OTEL_SDK_DISABLED=true
export OTEL_METRICS_EXPORTER=none OTEL_LOGS_EXPORTER=none OTEL_TRACES_EXPORTER=none CLAUDE_CODE_ENABLE_TELEMETRY=0
make build GOOS=linux GOARCH=arm64
"""
        command(['sbx','exec','-i',BUILDER,'bash','-s'],data=build.encode(),timeout=900,candidate=True)
        # Building a patch is untrusted execution. Builder has no host credentials or cluster access.
        command(['sbx','stop',BUILDER])
        binary=SOURCE/'dist/linux/arm64/bin/hotrod'
        if not binary.is_file() or binary.is_symlink(): raise CandidateFailure('Build produced no regular hotrod binary')
        build_context=out/'image';build_context.mkdir()
        shutil.copyfile(binary,build_context/'hotrod')
        current=command(['docker','image','inspect',PINS['hotrod_image'],'--format','{{.Id}}']).stdout.decode().strip()
        if current!=PINS['hotrod_image_id']:raise RuntimeError('Baseline runtime image changed')
        (build_context/'Dockerfile').write_text(f'FROM {PINS["hotrod_image"]}\nCOPY --chmod=755 hotrod /app/hotrod\n')
        command(['docker','build','--pull=false','-t',image,build_context],timeout=180)
        command(['minikube','-p',PINS['cluster'],'image','load',image],timeout=180)
        shutil.rmtree(build_context)
        command([ROOT/'scripts/start-setup-worker.sh','b'],timeout=100)
        sql(f'CREATE DATABASE `{database}`;');made_db=True
        # Fork all four services: shared Go packages and the embedded UI can affect any of them.
        forks=[]
        for service in ('frontend','location','driver','route'):
            env=[{'name':'MYSQL_DBNAME','value':database}]
            if service=='route':env.append({'name':'FAST_ROUTE','value':'1'})
            forks.append({'forkOf':{'kind':'Deployment','namespace':PINS['namespace'],'name':service},
                          'customizations':{'images':[{'container':'hotrod','image':image}],'env':env}})
        spec={'name':sandbox,'spec':{'cluster':PINS['cluster'],'description':'Blind benchmark grading',
              'ttl':{'duration':'20m','offsetFrom':'createdAt'},'forks':forks}}
        attempted_sandbox=True
        sb=apply(spec); key=sb['routingKey']; result['routing_key']=key
        # Forward directly to the sandbox's entry pods. Service-to-service calls
        # still use Signadot baggage routing, including the asynchronous driver.
        pods=json.loads(command(KUBE+['get','pods','-o','json']).stdout)['items']
        urls={}
        for service,port in [('frontend',8080),('location',8081)]:
            matches=[]
            for pod in pods:
                for container in pod['spec']['containers']:
                    env={v['name']:v.get('value') for v in container.get('env',[])}
                    if container.get('image')==image and env.get('SIGNADOT_BASELINE_NAME')==service:
                        matches.append(pod['metadata']['name'])
            if len(matches)!=1:raise RuntimeError('Cannot identify the sandbox '+service+' pod')
            urls[service]=forward('pod/'+matches[0],port)
        baseline_url=forward('svc/frontend',8080)
        for mode in (['fast','normal'] if submission['task']=='t2' else ['fast']):
            if mode=='normal':
                spec['spec']['forks'][-1]['customizations']['env'][-1]['value']=''
                apply(spec)
            args=['env',f'CTBENCH_ROOT={ROOT}','node',out/'check.mjs',submission['task'],PINS['namespace'],key,mode,
                  urls['frontend'],urls['location'],baseline_url,out]
            cp=command(args,timeout=180,check=False)
            try: checks=json.loads(cp.stdout)
            except ValueError: raise RuntimeError('Grader produced invalid output')
            (out/f'checks-{mode}.json').write_text(json.dumps(checks,indent=2)+'\n')
            result['checks'].append(checks)
            if checks.get('status')=='HARNESS_ERROR': raise RuntimeError(checks.get('error','Unsupported candidate representation'))
            if checks.get('status')!='PASS': raise CandidateFailure(checks.get('error','Behavior checks failed'))
        # Verify MySQL persistence, not only a browser-local history table.
        if submission['task']=='t2':
            cp=command(KUBE+['exec','-i','mysql-0','--','mariadb','-uroot','-pabc','-N'],
                       data=f'SELECT COUNT(*) FROM `{database}`.ride_history;'.encode(),check=False)
            if cp.returncode:
                kind=history_count_failure((cp.stdout+cp.stderr).decode(errors='replace'))
                raise (CandidateFailure if kind=='candidate' else RuntimeError)(f'ride_history count failed ({kind}); see {step_no:02d}.log')
            count=int(cp.stdout.strip())
            expected_rows=result['checks'][-1]['historyBefore']+2
            if count!=expected_rows:raise CandidateFailure('MySQL row count does not match the API history')
            result['mysql_history_rows']=count
        result['grade_status']='PASS'
    except CandidateFailure as exc:
        result['grade_status']='FAIL';result['error']=str(exc)
    except Exception as exc:
        result['error']=str(exc);(out/'harness-error.txt').write_text(traceback.format_exc())
    finally:
        for proc,log in forwards:
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
            log.close()
        # Cleanup errors must not prevent writing an auditable result.
        def cleanup_command(args, **kw):
            try:
                cp=command(args,check=False,**kw)
                return cp.returncode == 0
            except Exception as exc:
                result['cleanup'].setdefault('errors',[]).append(str(exc))
                return False
        cleanup_command(['sbx','stop',BUILDER])
        if attempted_sandbox:
            
            try:
                pods=json.loads(command(KUBE+['get','pods','-o','json']).stdout)['items']
                for pod in pods:
                    if any(c.get('image')==image for c in pod['spec']['containers']):
                        cleanup_command(KUBE+['logs',pod['metadata']['name'],'-c','hotrod','--tail=80'],timeout=30)
            except Exception as exc:result['cleanup']['diagnostic_error']=str(exc)
        try:
            if attempted_sandbox:
                existing=json.loads(sd(['sandbox','list','-o','json']).stdout)
                if any(x['name']==sandbox for x in existing): sd(['sandbox','delete',sandbox],timeout=180)
                remaining=json.loads(sd(['sandbox','list','-o','json']).stdout)
                result['cleanup']['sandbox_deleted']=not any(x['name']==sandbox for x in remaining)
            else:
                result['cleanup']['sandbox_deleted']=True
        except Exception as exc:result['cleanup']['sandbox_error']=str(exc)
        if made_db:
            try:sql(f'DROP DATABASE IF EXISTS `{database}`;');result['cleanup']['database_dropped']=True
            except Exception as exc:result['cleanup']['database_error']=str(exc)
        cleanup_command(['docker','image','rm',image])
        cleanup_command(['minikube','-p',PINS['cluster'],'image','rm',image])
        # Release the devbox claim before stopping the VM. Reconnect on the next grade.
        cleanup_command(['sbx','exec',WORKER,'signadot','local','disconnect'],timeout=30)
        result['cleanup']['verifier_stopped']=cleanup_command(['sbx','stop',WORKER])
        if not result['cleanup'].get('sandbox_deleted') or (made_db and not result['cleanup'].get('database_dropped')) or result['cleanup'].get('errors'):
            result['grade_status']='HARNESS_ERROR';result['error']='Cleanup failed; do not start another run'
        result['ended_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        (run/'latest-grade.json').write_text(json.dumps({'path':str(out.relative_to(ROOT))})+'\n')
        print(json.dumps(result,indent=2),flush=True)
    return {'PASS':0,'FAIL':1,'HARNESS_ERROR':2}[result['grade_status']]

if __name__=='__main__':
    if len(sys.argv)!=2:sys.exit('Usage: grade.sh <run_id>')
    with (ROOT/'private/grader.lock').open('w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:sys.exit('Another grade is running')
        sys.exit(main(sys.argv[1]))
