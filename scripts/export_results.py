#!/usr/bin/env python3
"""Copy each ledger run's transcripts, diffs and grader output to results/<run_id>/ with secrets removed."""
import csv, json, pathlib, re, shutil, sys

PATTERNS=[r'sk-ant-[A-Za-z0-9_-]+', r'cot_[A-Za-z0-9_-]+', r'gh[opusr]_[A-Za-z0-9]{36,}', r'(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+']

def redact(text, secrets, root):
    for secret in secrets:
        if secret: text=text.replace(secret,'[REDACTED]')
    for pattern in PATTERNS:
        text=re.sub(pattern,lambda m:(m.group(1) if m.groups() else '')+'[REDACTED]',text)
    home=str(pathlib.Path.home())
    # Claude Code also encodes the home directory in project paths, e.g. -Users-<name>-src-...
    return text.replace(str(root)+'/','').replace(home,'~').replace(home.replace('/','-'),'-Users-user')

def export(root, run_id, secrets):
    source=root/'runs'/run_id;target=root/'results'/run_id
    if target.exists(): shutil.rmtree(target)
    files=[p for p in source.glob('round-*/*') if p.name in ('prompt.txt','transcript.jsonl','submission.diff','outcome.json','agent.json','telemetry-exports.jsonl','termination.json')]
    expected=('submission.diff','run.json','reviewed-run.json','transcript-review.json','timing.json','harness-error.txt')
    files+=[source/n for n in expected if (source/n).exists()]
    target.mkdir(parents=True,exist_ok=True)
    # Record what a complete run would hold but this one does not, e.g. a run that failed before its first round.
    (target/'manifest.json').write_text(json.dumps({'missing':[n for n in expected if n!='harness-error.txt' and not (source/n).exists()],
                                                    'rounds':sorted(p.name for p in source.glob('round-*'))},indent=2)+'\n')
    for path in files:
        out=target/path.relative_to(source);out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(redact(path.read_text(errors='replace'),secrets,root))

def secrets(root):
    values=[(root/'private/codetelemetry-ingest-key').read_text().strip()]
    values+=[l.split('=',1)[1].strip() for l in (root/'private/claude-subscription.env').read_text().splitlines() if '=' in l]
    key=root/'private/signadot-api-key'
    if key.exists(): values.append(key.read_text().strip())
    for config in (pathlib.Path.home()/'.signadot/config.yaml',root/'private/signadot.yaml'):
        if config.exists(): values+=re.findall(r'^api_key:\s*(\S+)',config.read_text(),re.M)
    return values

if __name__=='__main__':
    root=pathlib.Path(__file__).resolve().parents[1]
    rows=list(csv.DictReader((root/'ledger.csv').open()))
    wanted=sys.argv[1:] or [r['run_id'] for r in rows if r['notes'].startswith('primary')]
    values=secrets(root)
    for run_id in wanted: export(root,run_id,values)
    leaked=[p for p in (root/'results').rglob('*') if p.is_file() and any(v and v in p.read_text(errors='replace') for v in values)]
    if leaked: sys.exit('Secret still present in: '+', '.join(map(str,leaked)))
    print(f'Exported {len(wanted)} runs to results/')
