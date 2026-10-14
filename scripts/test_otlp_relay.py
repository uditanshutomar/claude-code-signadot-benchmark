import http.server, json, os, pathlib, subprocess, sys, tempfile, threading, time, unittest, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]

class Upstream(http.server.BaseHTTPRequestHandler):
    seen = []; fail_first = 0
    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        if Upstream.fail_first:
            Upstream.fail_first -= 1; self.send_response(503); self.end_headers(); return
        Upstream.seen.append((self.path, body, self.headers.get('Authorization')))
        self.send_response(200); self.send_header('Content-Length', '2'); self.end_headers(); self.wfile.write(b'{}')
    def log_message(self, *a): pass

class RelayTests(unittest.TestCase):
    def setUp(self):
        Upstream.seen = []; Upstream.fail_first = 0
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.tmp = tempfile.TemporaryDirectory(); self.log = pathlib.Path(self.tmp.name)/'relay.jsonl'
        env = dict(os.environ, CTBENCH_RELAY_UPSTREAM=f'http://127.0.0.1:{self.server.server_port}', CTBENCH_RELAY_PORT='0')
        self.proc = subprocess.Popen([sys.executable, str(ROOT/'scripts/otlp-relay.py'), str(self.log)], env=env, stdout=subprocess.PIPE, text=True)
        self.port = int(self.proc.stdout.readline().split()[-1])
    def tearDown(self):
        self.proc.terminate(); self.proc.wait(); self.server.shutdown(); self.tmp.cleanup()
    def post(self, path, body):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=body,
                                     headers={'Content-Type': 'application/x-protobuf', 'Authorization': 'Bearer k'})
        with urllib.request.urlopen(req, timeout=10) as r: return r.status
    def test_forwards_unchanged_and_records_each_export(self):
        self.assertEqual(self.post('/v1/logs', b'\x01\x02payload'), 200)
        self.assertEqual(Upstream.seen, [('/v1/logs', b'\x01\x02payload', 'Bearer k')])
        row = json.loads(self.log.read_text().splitlines()[-1])
        self.assertEqual((row['path'], row['bytes'], row['status']), ('/v1/logs', 9, 200))
        self.assertNotIn('Bearer', self.log.read_text())
    def test_requests_without_a_key_are_not_forwarded(self):
        # Apps under test (HotROD) export their own traces to the default local OTLP port without a key.
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/v1/traces', data=b'app-trace',
                                     headers={'Content-Type': 'application/x-protobuf'})
        with self.assertRaises(urllib.error.HTTPError) as e: urllib.request.urlopen(req, timeout=5)
        self.assertEqual(e.exception.code, 401)
        self.assertEqual(Upstream.seen, [])
        self.assertEqual(json.loads(self.log.read_text().splitlines()[-1])['status'], 'foreign')
    def test_reports_requests_in_flight(self):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/inflight', timeout=5) as r:
            self.assertEqual(r.read(), b'0')
    def test_retries_a_failed_upstream_response(self):
        Upstream.fail_first = 2
        self.assertEqual(self.post('/v1/traces', b'x'), 200)
        self.assertEqual(len(Upstream.seen), 1)
        self.assertEqual(json.loads(self.log.read_text().splitlines()[-1])['attempts'], 3)

if __name__ == '__main__': unittest.main()
