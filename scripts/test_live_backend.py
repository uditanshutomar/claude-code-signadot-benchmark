"""Exercise production evidence/accounting flow with fake sbx responses; no model."""
import io,json,pathlib,tarfile,tempfile,unittest
from types import SimpleNamespace
from unittest.mock import patch
import run_one

class BackendTests(unittest.TestCase):
    def test_two_rounds_save_session_evidence_and_incremental_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);blob=io.BytesIO()
            with tarfile.open(fileobj=blob,mode='w:gz') as archive:
                data=b'{"sessionId":"session"}\n';info=tarfile.TarInfo('project/session.jsonl');info.size=len(data);archive.addfile(info,io.BytesIO(data))
            def sbx(args,**kw):
                if 'cat' in args and str(args[-1]).startswith('/tmp/ctbench-round-'):
                    return SimpleNamespace(returncode=0,stdout=b'{"deadline_expired":false,"duration_ms":100}')
                if kw.get('input')==run_one.ARCHIVE_SCRIPT.encode():kw['stdout'].write(blob.getvalue())
                return SimpleNamespace(returncode=0,stdout=b'{}')
            totals=iter([1,1.25])
            def model(args,**kw):
                self.assertIn('--env-file',args)
                event={'type':'result','session_id':'session','modelUsage':{run_one.PINS['model']:{'inputTokens':10,'cacheReadInputTokens':20}},'total_cost_usd':next(totals),'num_turns':1}
                kw['stdout'].write((json.dumps(event)+'\n').encode())
                return SimpleNamespace(returncode=0)
            state={'worker':'ctbench-r001000000099','workspace':'/fixture','arm':'a'}
            backend=run_one.LiveBackend(state,root,'t1')
            with patch.object(run_one,'run',side_effect=sbx),patch.object(run_one.subprocess,'run',side_effect=model):
                first=backend.agent('task','session',0);second=backend.agent('fix','session',1)
            self.assertEqual(first['cost_usd'],1);self.assertEqual(second['cost_usd'],.25)
            self.assertEqual(second['duration_ms'],100);self.assertTrue(second['resumable'])
            self.assertIsNone(second['harness_error'])
            self.assertTrue((root/'round-1/session-manifest.json').exists())
    def test_cleanup_keeps_worker_when_archive_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);work=root/'work/sessions/r001000000099';work.mkdir(parents=True)
            out=root/'runs/r001000000099';out.mkdir(parents=True);(out/'submission.diff').write_bytes(b'diff')
            with patch.object(run_one,'ROOT',root),patch.object(run_one,'run_workspace',return_value=work),patch.object(run_one,'capture_diff',return_value=b'diff'),patch.object(run_one,'run') as command:
                with self.assertRaisesRegex(RuntimeError,'evidence incomplete'):
                    run_one.release_completed_worker({'run_id':work.name,'workspace':str(work),'worker':'fixture'},out)
                command.assert_not_called()

if __name__=='__main__':unittest.main()
