"""Explicit, per-worker collection. Preparation never calls activate()."""
import json, re
from reset_worker import ROOT, run

MODES=('offline-smoke','telemetry-smoke','primary')
DENIED=('codetelemetry.com:443','**.codetelemetry.com:443')
RELAY='127.0.0.1:14318'
RELAY_LOG='/tmp/ctbench-telemetry-exports.jsonl'
# Linux pkill -f matches full command lines; the bracket keeps the pattern from matching the shell running it.
RELAY_STOP="pkill -f '[c]tbench-otlp-relay.py'"
# Before stopping, wait for in-flight exports; any still pending are recorded as failed deliveries.
RELAY_DRAIN=(f'for i in $(seq 150); do n=$(curl -s http://{RELAY}/inflight || echo 0); [ "$n" = 0 ] && break; sleep 1; done; '
             f'[ "$n" = 0 ] || echo "{{\\"status\\":\\"inflight-at-shutdown\\",\\"count\\":$n}}" >> {RELAY_LOG}')
RELAY_START=(f'cd /tmp && : > {RELAY_LOG} && setsid -f python3 ctbench-otlp-relay.py {RELAY_LOG} > ctbench-relay.out 2>&1 < /dev/null; '
             f'for i in $(seq 50); do curl -s -o /dev/null http://{RELAY}/ && exit 0; sleep 0.2; done; exit 1')

def environment(arm,task,phase,key):
    if arm not in ('a','b') or task not in ('t1','t2') or phase not in ('initial','rework'):
        raise ValueError('Invalid experiment attributes')
    if not key or any(c.isspace() for c in key): raise ValueError('Invalid ingest key')
    return {
        'CLAUDE_CODE_ENABLE_TELEMETRY':'1','CLAUDE_CODE_ENHANCED_TELEMETRY_BETA':'1',
        'OTEL_SDK_DISABLED':'false','OTEL_METRICS_EXPORTER':'otlp',
        'OTEL_LOGS_EXPORTER':'otlp','OTEL_TRACES_EXPORTER':'otlp',
        'OTEL_EXPORTER_OTLP_PROTOCOL':'http/protobuf',
        # The in-worker relay (scripts/otlp-relay.py) forwards to https://ingest.codetelemetry.com.
        'OTEL_EXPORTER_OTLP_ENDPOINT':'http://'+RELAY,
        'OTEL_EXPORTER_OTLP_HEADERS':'Authorization=Bearer '+key,
        # Transport only. Ingest answered every request up to 300 KB but dropped or stalled some larger ones
        # (it rejects bodies over 4 MiB). Small batches keep requests in the reliable range; the client waits
        # longer than the relay's worst case, so the status the relay records is final.
        'OTEL_BSP_MAX_EXPORT_BATCH_SIZE':'4','OTEL_BLRP_MAX_EXPORT_BATCH_SIZE':'8',
        'OTEL_EXPORTER_OTLP_TIMEOUT':'90000','OTEL_BLRP_EXPORT_TIMEOUT':'120000','OTEL_BSP_EXPORT_TIMEOUT':'120000',
        'CLAUDE_CODE_OTEL_SHUTDOWN_TIMEOUT_MS':'120000',
        # A 60 s metrics interval reused connections the server had already closed as idle.
        'OTEL_METRIC_EXPORT_INTERVAL':'30000','OTEL_METRIC_EXPORT_TIMEOUT':'30000',
        'OTEL_LOG_USER_PROMPTS':'1','OTEL_LOG_ASSISTANT_RESPONSES':'1',
        'OTEL_LOG_TOOL_DETAILS':'1','OTEL_LOG_TOOL_CONTENT':'1',
        'OTEL_METRICS_INCLUDE_SESSION_ID':'true',
        'OTEL_RESOURCE_ATTRIBUTES':f'deployment.environment=ctbench-arm-{arm},env=ctbench-arm-{arm},ctbench.task={task},ctbench.phase={phase}'
    }

def credentials():
    p=ROOT/'private/codetelemetry-ingest-key'
    if not p.is_file() or p.stat().st_mode & 0o077: raise RuntimeError('Private 0600 CodeTelemetry ingest key required')
    key=p.read_text().strip();environment('a','t1','initial',key);return key

def owned(worker):
    if not re.fullmatch(r'ctbench-r[a-f0-9]{12}',worker): raise ValueError('Collection only permits a fresh benchmark run worker')

def activate(worker,env):
    owned(worker)
    # Remove only this fresh worker's preparation denials. Global policies remain intact.
    rules=json.loads(run(['sbx','policy','ls',worker,'--json'],capture_output=True).stdout)['rules']
    targets=set(DENIED)|{'codetelemetry.com','**.codetelemetry.com'}
    for rule in rules:
        # Existing preparation rules may block every port, not just 443.
        if (rule.get('scope')=='sandbox:'+worker and rule.get('resource_type')=='network'
                and rule.get('decision')=='deny' and rule.get('resources')
                and set(rule['resources']).issubset(targets)):
            run(['sbx','policy','rm','network','--sandbox',worker,'--id',rule['id'],'--force'],stdout=-3)
    run(['sbx','policy','allow','network','--sandbox',worker,'ingest.codetelemetry.com:443'],stdout=-3)
    checked=json.loads(run(['sbx','policy','check','network','--sandbox',worker,'--json','ingest.codetelemetry.com:443'],capture_output=True).stdout)
    if not checked.get('allowed'): raise RuntimeError('Collection endpoint remains denied')
    # Claude Code's direct HTTPS export through the sandbox proxy lost batches; a fresh local relay forwards each export.
    run(['sbx','cp',ROOT/'scripts/otlp-relay.py',worker+':/tmp/ctbench-otlp-relay.py'],stdout=-3)
    run(['sbx','exec',worker,'bash','-c',RELAY_STOP+' || true'],stdout=-3,check=False)
    run(['sbx','exec',worker,'bash','-c',RELAY_START],stdout=-3,timeout=60)
    # User settings are supported for exporters; project settings no longer enable them.
    script='import json,pathlib,sys;p=pathlib.Path.home()/".claude/settings.json";d=json.loads(p.read_text());d["env"].update(json.load(sys.stdin));p.write_text(json.dumps(d));p.chmod(0o600)'
    run(['sbx','exec','-i',worker,'python3','-c',script],input=json.dumps(env).encode(),timeout=30)

def deactivate(worker):
    owned(worker)
    run(['sbx','exec',worker,'bash','-c',RELAY_DRAIN],stdout=-3,check=False,timeout=180)
    run(['sbx','exec',worker,'bash','-c',RELAY_STOP+' || true'],stdout=-3,check=False)
    for resource in DENIED:
        run(['sbx','policy','deny','network','--sandbox',worker,resource],stdout=-3)
    run(['sbx','exec','-i',worker,'bash','-s'],input=(ROOT/'scripts/configure-worker.sh').read_bytes(),timeout=120)
