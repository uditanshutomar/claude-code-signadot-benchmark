import json, unittest
from unittest.mock import patch
from types import SimpleNamespace
import collection, protocol
from annotate import review

class CollectionTests(unittest.TestCase):
    def test_attributes_and_brief_capture(self):
        env=collection.environment('b','t2','rework','fake-fixture-key')
        # CodeTelemetry's replay shows the arm from 'env'; the brief's deployment.environment carries the same value.
        self.assertEqual(env['OTEL_RESOURCE_ATTRIBUTES'],'deployment.environment=ctbench-arm-b,env=ctbench-arm-b,ctbench.task=t2,ctbench.phase=rework')
        self.assertEqual(env['OTEL_EXPORTER_OTLP_PROTOCOL'],'http/protobuf')
        self.assertNotIn('OTEL_LOG_RAW_API_BODIES',env)
    def test_exports_are_small_and_patient(self):
        # Ingest answered every request up to 300 KB but dropped or stalled some at 600 KB and above;
        # single tool results reach ~380 KB. Small batches keep each request in the reliable range.
        env=collection.environment('a','t1','initial','fake-fixture-key')
        self.assertLessEqual(int(env['OTEL_BSP_MAX_EXPORT_BATCH_SIZE']),4)
        self.assertLessEqual(int(env['OTEL_BLRP_MAX_EXPORT_BATCH_SIZE']),8)
        # The client waits longer than the relay's worst case (3 attempts x 20 s + backoff), so the status the
        # relay records is final and the client never retries a request the relay is still delivering.
        self.assertGreaterEqual(int(env['OTEL_EXPORTER_OTLP_TIMEOUT']),90000)
        for key in ('OTEL_BLRP_EXPORT_TIMEOUT','OTEL_BSP_EXPORT_TIMEOUT'):
            self.assertGreater(int(env[key]),int(env['OTEL_EXPORTER_OTLP_TIMEOUT']))
        self.assertGreaterEqual(int(env['CLAUDE_CODE_OTEL_SHUTDOWN_TIMEOUT_MS']),60000)
        # Metrics exported every 60 s reused idle connections; the reader clamps its timeout to the interval.
        self.assertLess(int(env['OTEL_METRIC_EXPORT_INTERVAL']),60000)
        self.assertLessEqual(int(env['OTEL_METRIC_EXPORT_TIMEOUT']),int(env['OTEL_METRIC_EXPORT_INTERVAL']))
    def test_activation_is_scoped_and_secret_sent_over_stdin(self):
        worker='ctbench-r001000000099';env=collection.environment('a','t1','initial','fixture-key')
        rules=[{'id':'owned-all-ports','scope':'sandbox:'+worker,'resource_type':'network','decision':'deny','resources':['**.codetelemetry.com']},
               {'id':'owned-443','scope':'sandbox:'+worker,'resource_type':'network','decision':'deny','resources':['codetelemetry.com:443']},
               {'id':'global-deny','scope':'global','resource_type':'network','decision':'deny','resources':['**.codetelemetry.com']},
               {'id':'other-worker','scope':'sandbox:other','resource_type':'network','decision':'deny','resources':['**.codetelemetry.com']},
               {'id':'unrelated','scope':'sandbox:'+worker,'resource_type':'network','decision':'deny','resources':['example.com']}]
        def response(argv,**kwargs):
            return SimpleNamespace(stdout=json.dumps({'rules':rules} if argv[:3]==['sbx','policy','ls'] else {'allowed':True}).encode())
        with patch.object(collection,'run',side_effect=response) as run:
            collection.activate(worker,env)
            for call in run.call_args_list:
                command=' '.join(map(str,call.args[0]))
                self.assertIn(worker,command);self.assertNotIn('fixture-key',command)
            self.assertIn(b'fixture-key',run.call_args.kwargs['input'])
            removed=[call.args[0][call.args[0].index('--id')+1] for call in run.call_args_list if '--id' in call.args[0]]
            self.assertEqual(removed,['owned-all-ports','owned-443'])
    def test_exports_go_through_the_local_relay(self):
        env=collection.environment('a','t1','initial','fake-fixture-key')
        # Not the standard OTLP port 4318, which the app under test exports its own traces to by default.
        self.assertEqual(env['OTEL_EXPORTER_OTLP_ENDPOINT'],'http://127.0.0.1:14318')
        worker='ctbench-r001000000099'
        def response(argv,**kwargs):
            return SimpleNamespace(stdout=json.dumps({'rules':[]} if argv[:3]==['sbx','policy','ls'] else {'allowed':True}).encode())
        with patch.object(collection,'run',side_effect=response) as run:
            collection.activate(worker,env)
            started=[c.args[0] for c in run.call_args_list if 'otlp-relay' in ' '.join(map(str,c.args[0]))]
            self.assertTrue(started)
        with patch.object(collection,'run') as run:
            collection.deactivate(worker)
            self.assertTrue(any('pkill' in ' '.join(map(str,c.args[0])) for c in run.call_args_list))
    def test_relay_stop_does_not_kill_its_own_shell(self):
        # Linux pkill -f matches full command lines, including the bash -c that runs it.
        import re, shlex
        pattern=shlex.split(collection.RELAY_STOP)[2]
        self.assertTrue(re.search(pattern,'python3 /tmp/ctbench-otlp-relay.py '+collection.RELAY_LOG))
        self.assertFalse(re.search(pattern,'bash -c '+collection.RELAY_STOP+' || true'))
        self.assertNotIn('pkill',collection.RELAY_START)
    def test_existing_setup_worker_cannot_enable_collection(self):
        with patch.object(collection,'run') as run:
            with self.assertRaises(ValueError):collection.activate('ctbench-setup-a',{})
            run.assert_not_called()
    def test_primary_refuses_unfrozen_source(self):
        with self.assertRaises(RuntimeError):protocol.verify_freeze({})
    def test_annotation_resolves_without_changing_grade(self):
        records=[{'round':0,'grade':{'grade_status':'FAIL'},'agent':{'timed_out':False},'verdict':'NEEDS_TRANSCRIPT_REVIEW'}]
        note=dict(task_present=True,declared_done=True,reported_unfixed_break=False,skill_invoked=False,cli_fallback=False,services_touched=['location'],evidence='round-0/transcript.jsonl:5')
        self.assertEqual(review(records,{'0':note})[0]['verdict'],'BROKEN_UNDETECTED')
        self.assertEqual(records[0]['verdict'],'NEEDS_TRANSCRIPT_REVIEW')
        note['evidence']=''
        with self.assertRaises(ValueError):review(records,{'0':note})

if __name__=='__main__':unittest.main()
