#!/usr/bin/env bash
# Start an existing setup worker and check tools without starting Claude.
set -euo pipefail
case "${1:-}" in
  a|b) arm=$1 ;;
  *) echo "Usage: $0 a|b" >&2; exit 2 ;;
esac
root=$(cd "$(dirname "$0")/.." && pwd)
worker="ctbench-setup-$arm"
run_sbx() { python3 "$root/scripts/setup-only.py" sbx "$@"; }
# Start before applying configuration: startup may inject Docker's MCP gateway.
run_sbx exec "$worker" true
for host in $(python3 -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1]))))' "$root/config/browser-hosts.json"); do
  run_sbx policy allow network --sandbox "$worker" "$host" --method GET >/dev/null
done
run_sbx exec -i "$worker" bash -s < "$root/scripts/configure-worker.sh"
for domain in codetelemetry.com:443 ingest.codetelemetry.com:443; do
  result=$(run_sbx policy check network --sandbox "$worker" --json "$domain" || true)
  printf '%s' "$result" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["allowed"] is False and d["deny_kind"] == "explicit", "CodeTelemetry must remain explicitly blocked"'
done
if [ "$arm" = b ]; then
  bash "$root/scripts/connect-worker.sh" "$worker"
  run_sbx exec "$worker" bash -c '
    set -eu
    test -f "$HOME/.signadot/config.yaml"
    if ! signadot local status >/dev/null 2>&1; then signadot local connect --wait-timeout 60s; fi
    if ! grep -q "frontend.ctbench-hotrod.svc" /etc/hosts; then
      signadot local disconnect
      signadot local connect --wait-timeout 60s
    fi
    curl --noproxy "*" -fsS --max-time 15 http://frontend.ctbench-hotrod.svc:8080/splash |
      python3 -c '\''import json,sys; d=json.load(sys.stdin); assert len(d["Locations"]) == 5; print("Baseline data check passed")'\''
  '
else
  run_sbx exec "$worker" bash -c '! command -v signadot >/dev/null 2>&1'
fi
run_sbx exec "$worker" bash -c 'export PATH="$HOME/ctbench-tools/node_modules/.bin:$PATH"; timeout 40 claude mcp list'
