import json
import pathlib, subprocess, tempfile, unittest
from unittest.mock import patch
import run_one
from reset_worker import namespaces

class FakeBackend:
    """A deterministic stand-in. Never calls Claude, sbx or Signadot."""
    def __init__(self,statuses,timed_out=False):
        self.statuses=iter(statuses);self.calls=[];self.records=[];self.timed_out=timed_out
    def agent(self,prompt,session,number):
        self.calls.append((prompt,session,number))
        return {'timed_out':self.timed_out and number==0,'resumable':True}
    def capture(self,number): self.calls.append(('capture',number))
    def grade(self,number): return {'grade_status':next(self.statuses),'checks':['exact grader output']}
    def save(self,record): self.records.append(record)

class OrchestrationTests(unittest.TestCase):
    def test_success_does_not_request_rework(self):
        b=FakeBackend(['PASS']);r=run_one.rounds(b,'task','session')
        self.assertEqual(len(r),1);self.assertEqual(r[0]['verdict'],'VERIFIED_CORRECT')
    def test_failure_resumes_same_session_with_only_grade(self):
        b=FakeBackend(['FAIL','PASS']);r=run_one.rounds(b,'task','session')
        self.assertEqual(b.calls[2],(run_one.rework_prompt(r[0]['grade']),'session',1))
        self.assertEqual(r[-1]['verdict'],'VERIFIED_CORRECT')
    def test_max_three_reworks(self):
        b=FakeBackend(['FAIL']*4);self.assertEqual(len(run_one.rounds(b,'task','session')),4)
    def test_infrastructure_failure_is_retained_and_stops(self):
        b=FakeBackend(['HARNESS_ERROR']);self.assertEqual(run_one.rounds(b,'task','session')[0]['verdict'],'HARNESS_ERROR')
        self.assertIn(('capture',0),b.calls)
    def test_timeout_reworks_even_when_partial_diff_passes(self):
        b=FakeBackend(['PASS','PASS'],timed_out=True);r=run_one.rounds(b,'task','session')
        self.assertEqual(r[0]['verdict'],'DID_NOT_FINISH');self.assertEqual(len(r),2)
    def test_rework_prompt_carries_only_failure_content(self):
        root=str(run_one.ROOT)
        grade={'grade_status':'FAIL','error':'\x1b[2mfare mismatch\x1b[22m','run_id':'r001000000099',
               'sandbox':'ctg-abc','routing_key':'k123','database':'ctg_abc','grader_sha256':{'grader/grade.py':'00'},
               'diagnostics':root+'/work/grading-source/services/driver/fare.go:3: undefined: x',
               'checks':[{'mode':'normal','status':'FAIL','checks':['location endpoint responds'],'error':'fare mismatch',
                          'stack':'Error at file://'+root+'/runs/x/check.mjs:7','network':[{'path':'/dispatch'}],'browserVersion':'1'}]}
        prompt=run_one.rework_prompt(grade)
        self.assertTrue(prompt.startswith('CI failed on your change: ') and prompt.endswith('. Fix it.'))
        for leaked in ('/Users','Signadot','codetelemetry','ctbench','ctg-','k123','grader_sha256','routing','\x1b','check.mjs','r001000000099'):
            self.assertNotIn(leaked,prompt)
        for kept in ('fare mismatch','location endpoint responds','services/driver/fare.go:3: undefined: x'):
            self.assertIn(kept,prompt)
    def test_run_paths_do_not_name_the_experiment(self):
        from reset_worker import run_workspace, SKILLS
        for path in (run_workspace('r001000000099'),SKILLS):
            for word in ('signadot/codetelemetry','codetelemetry','benchmark','ctbench'):
                self.assertNotIn(word,str(path).lower())
        self.assertEqual(run_workspace('r001000000099').name,'hotrod')
    def test_signadot_calls_use_the_pinned_org_and_private_key(self):
        from reset_worker import signadot_env, worker_config, PINS
        with tempfile.TemporaryDirectory() as tmp:
            key=pathlib.Path(tmp)/'key';key.write_text('fixture-key\n')
            env=signadot_env(key)
            self.assertEqual((env['SIGNADOT_ORG'],env['SIGNADOT_API_KEY']),(PINS['signadot_org'],'fixture-key'))
            self.assertEqual(worker_config(key),'org: '+PINS['signadot_org']+'\napi_key: fixture-key\n')
    def test_rework_after_timeout_says_so(self):
        prompt=run_one.rework_prompt({'grade_status':'PASS','checks':[]},timed_out=True)
        self.assertIn('60-minute',prompt)
        self.assertNotIn('60-minute',run_one.rework_prompt({'grade_status':'FAIL','checks':[]}))
    def test_extension_uses_clean_rerun_of_a_contaminated_attempt(self):
        import csv
        with tempfile.TemporaryDirectory() as tmp:
            path=pathlib.Path(tmp)/'ledger.csv'
            fields=['task','arm','rep','initial_verdict','final_verdict','notes']
            with path.open('w') as f:
                w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
                for task in ('t1','t2'):
                    for arm in ('a','b'):
                        for rep in range(1,6):
                            w.writerow(dict(task=task,arm=arm,rep=rep,initial_verdict='VERIFIED_CORRECT',final_verdict='VERIFIED_CORRECT',notes='primary'))
                w.writerow(dict(task='t1',arm='a',rep=2,initial_verdict='VERIFIED_CORRECT',final_verdict='VERIFIED_CORRECT',notes='primary; contaminated: used Signadot'))
            result=subprocess.run(['python3',str(run_one.ROOT/'scripts/run-order.py'),'--ledger',str(path)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['extensions'],{'t1':True,'t2':True})
    def test_freeze_covers_the_protocol(self):
        import protocol
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            for name in ('PROTOCOL.md','grade.sh','run-one.sh'): (root/name).write_text('v1')
            with patch.object(protocol,'ROOT',root):
                record={'source_hashes':protocol.source_hashes()}
                (root/'PROTOCOL.md').write_text('v2')
                with self.assertRaises(RuntimeError): protocol.verify_freeze(record)
    def test_harness_error_round_is_not_graded(self):
        b=FakeBackend(['PASS'])
        b.agent=lambda *args: {'timed_out':False,'resumable':True,'harness_error':'Telemetry incomplete: 1 of 9 exports not delivered'}
        b.grade=lambda number: self.fail('a harness-error round must not spend a grading sandbox')
        r=run_one.rounds(b,'task','session')
        self.assertEqual(r[0]['verdict'],'HARNESS_ERROR');self.assertIn(('capture',0),b.calls)
    def test_initial_and_resume_flags(self):
        self.assertIn('--session-id',run_one.agent_argv('task','id'))
        argv=run_one.agent_argv('grade','id',True)
        self.assertIn('--resume',argv);self.assertNotIn('--session-id',argv)
    def test_namespace_scope(self):
        self.assertEqual(namespaces({'forks':[{'forkOf':{'namespace':'ctbench-hotrod'}},{'forkOf':{'namespace':'other'}}]}),{'ctbench-hotrod','other'})
    def test_new_files_and_agent_commits_in_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            def git(*args): return subprocess.check_output(['git','-C',tmp,*args])
            git('init','-q');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid')
            p=pathlib.Path(tmp);(p/'base.txt').write_text('base\n');git('add','.');git('commit','-qm','base')
            sha=git('rev-parse','HEAD').decode().strip()
            (p/'base.txt').write_text('changed\n');git('add','.');git('commit','-qm','agent commit')
            (p/'new.txt').write_text('new\n');before=git('status','--porcelain')
            with patch.dict(run_one.PINS,{'hotrod_sha':sha}): diff=run_one.capture_diff(tmp)
            self.assertIn(b'new.txt',diff);self.assertIn(b'+changed',diff)
            self.assertEqual(before,git('status','--porcelain'))
    def test_execute_is_locked_without_approval(self):
        result=subprocess.run(['python3',str(run_one.ROOT/'scripts/run_one.py'),'t1','a','1','--execute'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('No model call',result.stderr)
    def test_missing_session_stops_rework(self):
        b=FakeBackend(['FAIL'])
        b.agent=lambda *args: {'timed_out':False,'resumable':False}
        r=run_one.rounds(b,'task','session')
        self.assertEqual(len(r),1);self.assertIn('resume_blocked',r[0])
    def test_model_error_is_not_counted_as_failed_code(self):
        b=FakeBackend(['FAIL'])
        b.agent=lambda *args: {'timed_out':False,'resumable':True,'harness_error':'authentication failed'}
        self.assertEqual(run_one.rounds(b,'task','session')[0]['verdict'],'HARNESS_ERROR')
    def test_setup_wrapper_preserves_termination(self):
        import signal,time
        process=subprocess.Popen(['python3',str(run_one.ROOT/'scripts/setup-only.py'),'python3','-c','import time; time.sleep(30)'])
        time.sleep(.15);process.send_signal(signal.SIGTERM)
        self.assertEqual(process.wait(timeout=3),-signal.SIGTERM)
    def test_ledger_keeps_initial_failure_and_final_success(self):
        row={}
        first={'verdict':'DID_NOT_FINISH','agent':{'started_utc':'2026-10-13T00:00:00Z','duration_ms':3600000,'cost_usd':None,'num_turns':None}}
        final={'verdict':'VERIFIED_CORRECT','agent':{'duration_ms':1000,'cost_usd':.25}}
        run_one.summarize(row,[first,final])
        self.assertEqual(row['initial_verdict'],'DID_NOT_FINISH')
        self.assertEqual(row['final_verdict'],'VERIFIED_CORRECT')
        self.assertEqual(row['rework_rounds'],1)
        self.assertIsNone(row['cost_usd']);self.assertEqual(row['rework_cost_usd'],.25)
    def test_extension_decision_excludes_cleanup_infrastructure_error(self):
        import csv
        with tempfile.TemporaryDirectory() as tmp:
            path=pathlib.Path(tmp)/'ledger.csv'
            fields=['task','arm','rep','initial_verdict','final_verdict','notes']
            with path.open('w') as f:
                w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
                for task in ('t1','t2'):
                    for arm in ('a','b'):
                        for rep in range(1,6):
                            w.writerow(dict(task=task,arm=arm,rep=rep,initial_verdict='VERIFIED_CORRECT',
                                final_verdict='HARNESS_ERROR' if (task,arm,rep)==('t1','a',1) else 'VERIFIED_CORRECT',notes='primary'))
            result=subprocess.run(['python3',str(run_one.ROOT/'scripts/run-order.py'),'--ledger',str(path)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertIn('uncontaminated',result.stderr)

    def test_cleanup_refuses_a_workspace_outside_run_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                run_one.release_completed_worker({'run_id':'r001000000099','workspace':tmp},pathlib.Path(tmp))

if __name__=='__main__': unittest.main()
