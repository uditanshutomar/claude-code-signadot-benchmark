#!/usr/bin/env python3
"""Own one loopback-only port-forward to the local Signadot tunnel service."""
import fcntl, json, pathlib, re, signal, socket, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE = ROOT / 'private/local-tunnel.json'
LOG = ROOT / 'artifacts/local-tunnel.log'
ARGV = ['kubectl', '--context', 'minikube', '-n', 'signadot', 'port-forward',
        '--address', '127.0.0.1', 'service/tunnel-proxy', ':1080']

def healthy(port, timeout=3):
    # A kubectl port-forward can stay alive but stop carrying streams; check it answers a SOCKS5 greeting.
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=timeout) as conn:
            conn.settimeout(timeout); conn.sendall(b'\x05\x01\x00')
            return conn.recv(2) == b'\x05\x00'
    except OSError:
        return False

def owned(state):
    current = subprocess.run(['ps', '-p', str(state['pid']), '-o', 'command='], capture_output=True, text=True)
    return current.returncode == 0 and ' '.join(ARGV) in current.stdout

def main(action):
    with (ROOT/'private/local-tunnel.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(STATE.read_text()) if STATE.exists() else None
        if state and owned(state):
            if action == 'start' and healthy(state['port']):
                print(state['port']); return
            # Verify process identity before terminating a PID from an old file.
            import os
            os.kill(state['pid'], signal.SIGTERM)
        STATE.unlink(missing_ok=True)
        if action == 'stop': return
        with LOG.open('wb') as output:
            proc = subprocess.Popen(ARGV, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            for _ in range(100):
                match = re.search(r'Forwarding from 127\.0\.0\.1:(\d+)', LOG.read_text())
                if match:
                    state = {'pid': proc.pid, 'port': int(match[1]), 'argv': ARGV}
                    STATE.write_text(json.dumps(state)+'\n'); STATE.chmod(0o600)
                    print(state['port']); return
                if proc.poll() is not None: raise RuntimeError('Local port-forward failed; see artifacts/local-tunnel.log')
                time.sleep(.1)
            raise RuntimeError('Local port-forward startup timed out')
        except BaseException:
            proc.terminate(); proc.wait(timeout=5); raise

if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ('start','stop'): sys.exit('Usage: local-tunnel.py start|stop')
    main(sys.argv[1])
