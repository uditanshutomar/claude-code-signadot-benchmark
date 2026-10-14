import json, pathlib, tempfile, unittest
import export_results

class ExportTests(unittest.TestCase):
    def test_secrets_and_local_root_are_removed(self):
        text='key=abc123SECRET token sk-ant-oat01-XYZ_9 ingest cot_Q1w2E3 Authorization: Bearer eyJhbGciOi.x-y /bench/runs/r1'
        out=export_results.redact(text,['abc123SECRET'],'/bench')
        for leaked in ('abc123SECRET','sk-ant-oat01-XYZ_9','cot_Q1w2E3','eyJhbGciOi','/bench/'):
            self.assertNotIn(leaked,out)
        self.assertIn('[REDACTED]',out)

    def test_export_copies_round_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);run=root/'runs/r001000000099';(run/'round-0').mkdir(parents=True)
            (run/'round-0/transcript.jsonl').write_text('{"type":"result","note":"abc123SECRET"}\n')
            (run/'round-0/prompt.txt').write_text('task')
            (run/'round-0/outcome.json').write_text('{}')
            (run/'submission.diff').write_text('diff')
            (run/'run.json').write_text(json.dumps({'run_id':'r001000000099'}))
            export_results.export(root,'r001000000099',['abc123SECRET'])
            out=root/'results/r001000000099'
            self.assertEqual((out/'submission.diff').read_text(),'diff')
            self.assertNotIn('abc123SECRET',(out/'round-0/transcript.jsonl').read_text())
            self.assertTrue((out/'run.json').exists())

class ExportEvidenceTests(unittest.TestCase):
    def test_failure_evidence_and_home_paths(self):
        home=str(pathlib.Path.home())
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);run=root/'runs/r001000000098';run.mkdir(parents=True)
            (run/'run.json').write_text('{}')
            (run/'harness-error.txt').write_text('failed at '+home+'/src/r001000000098/hotrod/file.go')
            export_results.export(root,'r001000000098',[])
            out=root/'results/r001000000098'
            self.assertTrue((out/'harness-error.txt').exists())
            self.assertNotIn(home,(out/'harness-error.txt').read_text())
            manifest=json.loads((out/'manifest.json').read_text())
            self.assertIn('submission.diff',manifest['missing'])

if __name__=='__main__': unittest.main()
