#!/usr/bin/env bash
# Reapply after startup: Docker may replace config or inject its MCP gateway.
set -euo pipefail
export PATH="$HOME/ctbench-tools/node_modules/.bin:$HOME/go/bin:$PATH"
# The common template predates this CLI pin. Upgrade identically before either arm's clock.
export CLAUDE_CODE_ENABLE_TELEMETRY=0 OTEL_SDK_DISABLED=true DISABLE_AUTOUPDATER=1
export OTEL_METRICS_EXPORTER=none OTEL_LOGS_EXPORTER=none OTEL_TRACES_EXPORTER=none
claude_version=2.1.296
if [ "$(claude --version | cut -d ' ' -f 1)" != "$claude_version" ]; then
  npm install --prefix "$HOME/ctbench-tools" --no-audit --no-fund --save-exact "@anthropic-ai/claude-code@$claude_version"
fi
test "$(claude --version | cut -d ' ' -f 1)" = "$claude_version"
# Chromium uses NSS rather than the system CA bundle used by curl.
# Trust the sandbox's existing Docker proxy CA in both arms.
if ! command -v certutil >/dev/null; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq libnss3-tools=2:3.120-1ubuntu2.1
fi
nss="$HOME/.local/share/pki/nssdb"
if [ -d "$HOME/.pki/nssdb" ]; then nss="$HOME/.pki/nssdb"; fi
mkdir -p "$nss"
if [ ! -f "$nss/cert9.db" ]; then certutil -N --empty-password -d "sql:$nss"; fi
if certutil -L -d "sql:$nss" -n ctbench-docker-proxy >/dev/null 2>&1; then
  certutil -D -d "sql:$nss" -n ctbench-docker-proxy
fi
certutil -A -d "sql:$nss" -n ctbench-docker-proxy -t 'C,,' -i /usr/local/share/ca-certificates/proxy-ca.crt
mkdir -p "$HOME/ctbench-tools" "$HOME/.claude"
python3 - <<'PY'
import json, pathlib
p = pathlib.Path.home() / '.claude/settings.json'
data = json.loads(p.read_text()) if p.exists() else {}
env = {k: v for k, v in data.get('env', {}).items()
       if not k.startswith(('OTEL_', 'CODETELEMETRY_', 'CLAUDE_CODE_ENABLE_TELEMETRY'))}
env.update({
    'CLAUDE_CODE_ENABLE_TELEMETRY': '0', 'OTEL_SDK_DISABLED': 'true',
    'OTEL_METRICS_EXPORTER': 'none', 'OTEL_LOGS_EXPORTER': 'none',
    'OTEL_TRACES_EXPORTER': 'none', 'DISABLE_AUTOUPDATER': '1',
    'NO_PROXY': 'localhost,127.0.0.1,.svc,.svc.cluster,.svc.cluster.local,.ctbench-hotrod',
    'no_proxy': 'localhost,127.0.0.1,.svc,.svc.cluster,.svc.cluster.local,.ctbench-hotrod',
    'GOTOOLCHAIN': 'go1.27.1', 'GOTELEMETRY': 'off',
    'PATH': str(pathlib.Path.home() / 'ctbench-tools/node_modules/.bin') + ':'
            + str(pathlib.Path.home() / 'go/bin') + ':/usr/local/bin:/usr/bin:/bin'
})
data['env'] = env
p.write_text(json.dumps(data, indent=2) + '\n')
p.chmod(0o600)
PY

python3 - <<'PYCONFIG'
import json, pathlib
home = pathlib.Path.home()
p = home / '.claude.json'
data = json.loads(p.read_text()) if p.exists() else {}
servers = {
    'playwright': {
        'type': 'stdio',
        'command': str(home / 'ctbench-tools/node_modules/.bin/playwright-mcp'),
        'args': ['--headless', '--executable-path', str(home / '.cache/ms-playwright/chromium-1248/chrome-linux-arm64/chrome')]
    }
}
if pathlib.Path('/usr/local/bin/signadot').exists():
    servers['signadot'] = {'type': 'stdio', 'command': '/usr/local/bin/signadot', 'args': ['mcp', '--disable-elicitation']}
data['mcpServers'] = servers
p.write_text(json.dumps(data, indent=2) + '\n')
p.chmod(0o600)
print('Configured MCP servers:', ', '.join(servers))
PYCONFIG
