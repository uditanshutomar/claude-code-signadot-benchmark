#!/usr/bin/env python3
"""Forward Claude Code's OTLP/HTTP exports to CodeTelemetry unchanged, one line of evidence per export.

Runs inside each worker on 127.0.0.1. Claude Code's own HTTPS export through the sandbox's egress proxy lost
whole batches; forwarding through this relay delivered every event. Usage: otlp-relay.py LOG_FILE
"""
import http.server, json, os, sys, threading, time, urllib.error, urllib.request

UPSTREAM = os.environ.get('CTBENCH_RELAY_UPSTREAM', 'https://ingest.codetelemetry.com')
# Not the standard OTLP port 4318: the app under test exports its own traces there by default.
PORT = int(os.environ.get('CTBENCH_RELAY_PORT', '14318'))
LOG = open(sys.argv[1], 'a', buffering=1)

INFLIGHT = 0
LOCK = threading.Lock()

def forward(path, body, headers):
    # At most 3 attempts x 20 s plus 3 s of backoff, well inside the client's 90 s request timeout.
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(urllib.request.Request(UPSTREAM + path, data=body, headers=headers), timeout=20) as r:
                return r.status, r.read(), attempt
        except urllib.error.HTTPError as e:
            status, reply = e.code, e.read()
            if status < 500 and status != 429: return status, reply, attempt
        except Exception as e:
            status, reply = 599, str(e).encode()
        if attempt < 3: time.sleep(attempt)
    return status, reply, attempt

class Relay(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        # Lets shutdown wait until every accepted export has a final status.
        reply = str(INFLIGHT).encode()
        self.send_response(200); self.send_header('Content-Length', str(len(reply))); self.end_headers(); self.wfile.write(reply)
    def do_POST(self):
        global INFLIGHT
        with LOCK: INFLIGHT += 1
        try: self.relay()
        finally:
            with LOCK: INFLIGHT -= 1
    def relay(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        headers = {k: v for k, v in self.headers.items() if k.lower() in ('content-type', 'content-encoding', 'authorization')}
        if not any(k.lower() == 'authorization' for k in headers):
            # Claude Code always sends the ingest key; anything without it is another process, not its telemetry.
            LOG.write(json.dumps({'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'path': self.path,
                                  'bytes': len(body), 'status': 'foreign'}) + '\n')
            self.send_response(401); self.send_header('Content-Length', '0'); self.end_headers(); return
        start = time.time()
        status, reply, attempts = forward(self.path, body, headers)
        LOG.write(json.dumps({'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'path': self.path, 'bytes': len(body),
                              'status': status, 'attempts': attempts, 'seconds': round(time.time() - start, 2)}) + '\n')
        self.send_response(status if status < 599 else 502)
        self.send_header('Content-Length', str(len(reply))); self.end_headers(); self.wfile.write(reply)
    def log_message(self, *args): pass

server = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), Relay)
print('listening on', server.server_port, flush=True)
server.serve_forever()
