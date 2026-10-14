#!/usr/bin/env bash
# Common Linux tools for both arms. This script never starts an agent session.
set -euo pipefail

export CLAUDE_CODE_ENABLE_TELEMETRY=0 OTEL_SDK_DISABLED=true
export OTEL_METRICS_EXPORTER=none OTEL_LOGS_EXPORTER=none OTEL_TRACES_EXPORTER=none
export GOTELEMETRY=off GOTOOLCHAIN=go1.27.1
export DISABLE_AUTOUPDATER=1
export PATH="$HOME/ctbench-tools/node_modules/.bin:$HOME/go/bin:$PATH"

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
    'NO_PROXY': 'localhost,127.0.0.1,.svc,.svc.cluster,.svc.cluster.local',
    'no_proxy': 'localhost,127.0.0.1,.svc,.svc.cluster,.svc.cluster.local',
    'GOTOOLCHAIN': 'go1.27.1', 'GOTELEMETRY': 'off',
    'PATH': str(pathlib.Path.home() / 'ctbench-tools/node_modules/.bin') + ':'
            + str(pathlib.Path.home() / 'go/bin') + ':/usr/local/bin:/usr/bin:/bin'
})
data['env'] = env
p.write_text(json.dumps(data, indent=2) + '\n')
p.chmod(0o600)
PY

for tool in node npm go python3 timeout; do
  command -v "$tool" >/dev/null || { echo "Missing base tool: $tool" >&2; exit 1; }
done

npm install --prefix "$HOME/ctbench-tools" --no-audit --no-fund --save-exact \
  yarn@1.22.22 playwright@1.64.0 @playwright/mcp@0.0.83 \
  @anthropic-ai/claude-code@2.1.296

sudo "$HOME/ctbench-tools/node_modules/.bin/playwright" install-deps chromium
playwright install chromium
go install github.com/fullstorydev/grpcurl/cmd/grpcurl@v1.9.4

CHROMIUM_PATH=$(node -e 'console.log(require(process.env.HOME + "/ctbench-tools/node_modules/playwright").chromium.executablePath())')
# Docker adds a general MCP gateway. Keep the benchmark's tool set explicit.
python3 - <<'PY'
import json, pathlib
p = pathlib.Path.home() / '.claude.json'
if p.exists():
    data = json.loads(p.read_text())
    data.get('mcpServers', {}).pop('mcp-gateway', None)
    p.write_text(json.dumps(data, indent=2) + '\n')
PY
claude mcp add --scope user --transport stdio playwright -- \
  "$HOME/ctbench-tools/node_modules/.bin/playwright-mcp" \
  --headless --executable-path "$CHROMIUM_PATH"

node --version
go version
yarn --version
playwright --version
grpcurl --version
claude --version
node - <<'JS'
const {chromium} = require(process.env.HOME + '/ctbench-tools/node_modules/playwright');
(async () => {
  const browser = await chromium.launch({headless: true});
  console.log('Chromium launch passed:', browser.version());
  await browser.close();
})().catch(error => { console.error(error.message); process.exit(1); });
JS
