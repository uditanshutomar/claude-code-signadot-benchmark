#!/usr/bin/env python3
"""Write a dated phase record only after all six live controls match expectations."""
import hashlib
import json
import pathlib
import time

root = pathlib.Path(__file__).resolve().parents[1]
expected = {'check01':'FAIL','check02':'PASS','check03':'FAIL','check04':'PASS','check05':'FAIL','check06':'FAIL'}
labels = {'check01':'Task 1 baseline', 'check02':'Task 1 reference', 'check03':'Task 2 baseline',
          'check04':'Task 2 reference', 'check05':'Task 1 without React update', 'check06':'Task 2 with fixed $3.50 fare'}
latest = []
for run, status in expected.items():
    pointer = json.loads((root/'runs'/run/'latest-grade.json').read_text())
    path = root/pointer['path']/'result.json'
    result = json.loads(path.read_text())
    assert result['grade_status'] == status, (run, result['grade_status'])
    assert result['cleanup']['sandbox_deleted'] and result['cleanup']['database_dropped']
    latest.append({'label':labels[run], 'path':str(path.relative_to(root)), **result})
# Require successful controls to have used the same behavior checker.
assert len({r['grader_sha256']['grader/check.mjs'] for r in latest}) == 1
attempts = []
for path in sorted((root/'runs').glob('*/grade-*/result.json')):
    result = json.loads(path.read_text())
    attempts.append({'path':str(path.relative_to(root)), 'status':result['grade_status'],
                     'error':result.get('error'), 'patch_sha256':result['patch_sha256']})
record = {'record_type':'phase record; results at the recorded time, not current status',
          'checked_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
          'calibration_only':True, 'model_generation_calls':0, 'codetelemetry_ingestion':'disabled',
          'latest_controls':latest, 'all_completed_attempts':attempts,
          'aborted_attempts':[str(p.relative_to(root)) for p in sorted((root/'runs').glob('*/grade-*/ABORTED.md'))],
          'reference_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((root/'reference-solutions').glob('*.patch'))},
          'local_tests':'10 classifier/submission tests passed; prompt and model consistency check passed',
          'limits':['No agent run or subscription-model access tested.',
                    'Worker browser tunnel needs smoke validation after the observed truncated transfers.',
                    'Fresh-worker run/reset/rework orchestration and CodeTelemetry ingestion remain unverified.']}
json_path = root/'preflight/2026-10-13-grader-calibration.json'
md_path = root/'GRADING-VALIDATION.md'
if json_path.exists() or md_path.exists():
    raise RuntimeError('A phase record already exists. Write a new dated record instead of replacing it.')
json_path.write_text(json.dumps(record,indent=2)+'\n')
lines = ['# Grader calibration', '', 'Phase record, 2026-10-13. These are preparation checks, not agent benchmark results.', '',
         '| Control | Actual result | Evidence |', '| --- | --- | --- |']
for r in latest:
    lines.append(f"| {r['label']} | {r['grade_status']} | [Result]({r['path']}) |")
lines += ['', 'Both unmodified baselines fail. Both references pass. The partial contract change fails in the UI, and the fixed fare fails proportional pricing after passing the minimum-fare case.', '',
          'The Task 2 reference passed real dispatch, arrival, fare display, history POST/PATCH, reload, total count and MySQL persistence. The grader uses host Playwright with local port-forwards to the sandbox entry pods; calls between services retain Signadot routing. All six sandboxes and temporary databases were removed.', '',
          'The checker records the existing Leaflet `_clearLines` / `removeLayer` browser error separately. It was reproduced on the unmodified baseline. Other uncaught browser errors fail the check. This exception must be frozen before primary runs.', '',
          'Earlier attempts are retained. They include connection lifecycle failures, a reference proxy failure, truncated JavaScript transfers through ControlPlaneProxy, and the baseline Leaflet error. One cleanup timeout ended before a result JSON could be written; its ABORTED.md records what happened. No attempt was an agent session.', '',
          'Ten local classifier/submission tests passed. The four prompts and proposed Sonnet 4.6/high-effort settings passed consistency checks. Actual Claude subscription sign-in/model access, the run/reset/rework runner, worker-browser transport and telemetry smoke tests remain gates before primary runs.', '',
          'No model generation or CodeTelemetry ingestion was used for these checks. Nothing was pushed or published.', '',
          'Reference patch SHA-256:', '']
for name,sha in record['reference_sha256'].items():lines.append(f'- `{name}`: `{sha}`')
lines += ['', '[Full calibration record](preflight/2026-10-13-grader-calibration.json). The earlier phase records remain unchanged because they describe the setup when those checks were taken.', '']
md_path.write_text('\n'.join(lines))
print(json_path)
