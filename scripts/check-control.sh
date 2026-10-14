#!/usr/bin/env bash
# Disposable dependency check inside the preparation worker. No app solution or model.
set -euo pipefail
name=ctbench-redis-preflight
cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; docker image rm ctbench-network-preflight >/dev/null 2>&1 || true; }
trap cleanup EXIT
claude_bin="$HOME/ctbench-tools/node_modules/.bin/claude"
"$claude_bin" --version
"$claude_bin" auth status --json || test "$?" -eq 1
! command -v signadot
! test -f "$HOME/.signadot/config.yaml"
docker version --format '{{.Server.Version}}'
docker pull redis:7-alpine
docker run -d --name "$name" -p 127.0.0.1:16379:6379 redis:7-alpine
for i in $(seq 1 20); do
  if docker exec "$name" redis-cli ping | grep -q PONG; then break; fi
  sleep 1
done
python3 - <<'PY'
import socket
with socket.create_connection(('127.0.0.1',16379),timeout=5) as s:
    s.sendall(b'*1\r\n$4\r\nPING\r\n');assert s.recv(100)==b'+PONG\r\n'
print('PASS: dependency reachable from worker loopback')
PY
# Exercise downloads from a build container, not just the parent VM.
printf 'FROM redis:7-alpine\nRUN apk update && apk add --no-cache curl && curl -fsS https://registry.npmjs.org/playwright/latest > /tmp/package.json\n' | docker build --no-cache -t ctbench-network-preflight -
docker image inspect redis:7-alpine --format '{{json .RepoDigests}}'
echo 'PASS: container pull, build networking, package access and dependency service'
