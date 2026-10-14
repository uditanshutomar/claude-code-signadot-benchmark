import importlib.util, io, json, pathlib, subprocess, sys, tarfile, tempfile, unittest
from run_evidence import ARCHIVE_SCRIPT, cost_delta, inspect_stream, verify_archive

spec=importlib.util.spec_from_file_location('worker_command',pathlib.Path(__file__).with_name('worker-command.py'))
worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)

class EvidenceTests(unittest.TestCase):
    def test_resume_cost_is_delta(self):
        self.assertEqual(cost_delta(1,None,True),1)
        self.assertEqual(cost_delta(1.25,1),.25)
        self.assertEqual(cost_delta(1.5,1.25),.25)
    def test_missing_or_reset_cost_stays_unknown(self):
        for total,previous in [(None,1),(1,None),(.1,1),(float('nan'),1),(-1,1)]:
            self.assertIsNone(cost_delta(total,previous))
    def test_crash_does_not_become_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=pathlib.Path(tmp)/'exit.json'
            code=worker.execute([sys.executable,'-c','import os,signal; os.kill(os.getpid(),signal.SIGKILL)'],2,p,grace=.1)
            data=json.loads(p.read_text());self.assertEqual(code,137)
            self.assertFalse(data['deadline_expired']);self.assertEqual(data['termination_reason'],'signal')
    def test_recorded_deadline_and_kill_after_grace(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=pathlib.Path(tmp)/'exit.json'
            code=worker.execute([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(10)'],.2,p,grace=.1)
            self.assertEqual(code,124);self.assertTrue(json.loads(p.read_text())['deadline_expired'])
    def test_model_and_session_required_on_success(self):
        term={'deadline_expired':False}
        for event in [{'type':'result','session_id':'s'}, {'type':'result','modelUsage':{'m':{}}}]:
            self.assertIsNotNone(inspect_stream(json.dumps(event),'s','m',0,term)[2])
        event={'type':'result','session_id':'s','modelUsage':{'m':{}}}
        self.assertIsNone(inspect_stream(json.dumps(event),'s','m',0,term)[2])
    def test_early_137_and_missing_marker_are_errors(self):
        self.assertFalse(inspect_stream('','s','m',137,{'deadline_expired':False})[1])
        self.assertIsNotNone(inspect_stream('','s','m',137,{'deadline_expired':False})[2])
        self.assertIsNotNone(inspect_stream('','s','m',124,{})[2])
    def test_archive_preserves_nested_tool_results_and_excludes_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);project=root/'.claude/projects/project';project.mkdir(parents=True)
            (project/'s.jsonl').write_text('{"sessionId":"s"}\n')
            nested=project/'s/tool-results';nested.mkdir(parents=True);(nested/'output.txt').write_text('complete result')
            (root/'.claude/.credentials.json').write_text('must not leave home')
            archive=root/'session.tar.gz'
            import os
            with archive.open('wb') as out:
                subprocess.run([sys.executable,'-','s'],input=ARCHIVE_SCRIPT.encode(),env=dict(os.environ,HOME=tmp),stdout=out,check=True)
            manifest=verify_archive(archive,'s')
            self.assertEqual(len(manifest['files']),2)
            self.assertTrue(any(f['path'].endswith('output.txt') for f in manifest['files']))
            with self.assertRaises(RuntimeError):verify_archive(archive,'other')
    def test_deadline_allows_truncated_final_event(self):
        text='{"type":"system","session_id":"s"}\n{"type":"result"'
        result,expired,error=inspect_stream(text,'s','m',124,{'deadline_expired':True})
        self.assertTrue(expired);self.assertIsNone(error)
        self.assertIsNotNone(inspect_stream(text,'s','m',0,{'deadline_expired':False})[2])

    def test_archive_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=pathlib.Path(tmp)/'bad.tar.gz'
            with tarfile.open(p,'w:gz') as archive:
                info=tarfile.TarInfo('../s.jsonl');info.size=1;archive.addfile(info,io.BytesIO(b'x'))
            with self.assertRaises(RuntimeError):verify_archive(p,'s')

class ExportSummaryTests(unittest.TestCase):
    def test_counts_requests_and_failures(self):
        import tempfile, json
        from run_evidence import export_summary
        with tempfile.TemporaryDirectory() as tmp:
            p=pathlib.Path(tmp)/'exports.jsonl'
            p.write_text('\n'.join(json.dumps({'path':'/v1/logs','status':s}) for s in (200,200,503))+'\n')
            self.assertEqual(export_summary(p),{'requests':3,'failed':1,'foreign':0})
            self.assertIsNone(export_summary(pathlib.Path(tmp)/'missing.jsonl'))
            p.write_text('\n'.join(json.dumps({'path':'/v1/traces','status':s}) for s in (200,'foreign','foreign'))+'\n')
            self.assertEqual(export_summary(p),{'requests':1,'failed':0,'foreign':2})

class TelemetryProblemTests(unittest.TestCase):
    def test_missing_empty_or_failed_exports_are_problems(self):
        from run_evidence import telemetry_problem
        self.assertIsNone(telemetry_problem({'requests':12,'failed':0}))
        for summary in (None,{'requests':0,'failed':0},{'requests':3,'failed':1}):
            self.assertTrue(telemetry_problem(summary))

if __name__=='__main__': unittest.main()
