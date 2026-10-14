#!/usr/bin/env bash
# Use the native Signadot proxy via a host loopback port-forward. No kubeconfig enters the worker.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
worker=${1:?worker name required}
[[ "$worker" == ctbench-* ]] || exit 2
port=$(python3 "$root/scripts/local-tunnel.py" start)
python3 "$root/scripts/setup-only.py" sbx policy allow network --sandbox "$worker" "localhost:$port" >/dev/null
python3 "$root/scripts/setup-only.py" sbx policy allow network --sandbox "$worker" "host.docker.internal:$port" >/dev/null
python3 "$root/scripts/setup-only.py" sbx exec -i "$worker" python3 - "$port" <<'PY'
import pathlib,re,subprocess,sys
p=pathlib.Path.home()/'.signadot/config.yaml'
s=p.read_text()
new=re.sub(r'\nlocal:\n[\s\S]*', '', s).rstrip()+f'\nlocal:\n  connections:\n    - cluster: minikube\n      type: ProxyAddress\n      proxyAddress: host.docker.internal:{int(sys.argv[1])}\n'
if new != s:
    if re.search(r'^local:',s,re.M):
        result=subprocess.run(['signadot','local','disconnect'],capture_output=True,text=True)
        if result.returncode and 'not connected' not in result.stderr:
            raise RuntimeError('Could not disconnect the previous worker connection: '+result.stderr)
    p.write_text(new);p.chmod(0o600)
PY
python3 "$root/scripts/setup-only.py" sbx exec "$worker" bash -c 'signadot local status >/dev/null 2>&1 || signadot local connect --wait-timeout 60s'
