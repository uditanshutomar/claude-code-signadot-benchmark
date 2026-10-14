#!/usr/bin/env python3
"""Run the eight live calibration controls sequentially. No model or telemetry calls."""
import json
import time
import pathlib
import subprocess
import sys

root = pathlib.Path(__file__).resolve().parents[1]
expected = {'check01':'FAIL','check02':'PASS','check03':'FAIL','check04':'PASS','check05':'FAIL','check06':'FAIL','check07':'PASS','check08':'PASS'}
selected = sys.argv[1:] or list(expected)
if any(run not in expected for run in selected):
    sys.exit('Unknown calibration ID')
stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
for run in selected:
    print(f'Starting {run}; expected {expected[run]}', flush=True)
    cp = subprocess.run([root/'grade.sh',run], capture_output=True, text=True, cwd=root)
    (root/'artifacts'/f'{run}-calibration-{stamp}.json').write_text(cp.stdout)
    if cp.stderr:
        (root/'artifacts'/f'{run}-calibration-{stamp}-stderr.txt').write_text(cp.stderr)
    try:
        result = json.loads(cp.stdout)
    except ValueError:
        sys.exit(f'{run}: no valid grade result; inspect artifacts before continuing')
    status = result.get('grade_status')
    print(f'{run}: {status}; {result.get("error", "behavior checks passed")}', flush=True)
    checks = result.get('checks', [])
    if status == expected[run] and status == 'FAIL':
        if run == 'check01':
            assert checks and checks[-1]['error'] == 'location contract uses digit-string locID and name in id'
        elif run == 'check03':
            assert checks and checks[-1]['error'] == 'location GET ride-history is implemented'
        elif run == 'check05':
            assert checks and 'all location names retain their meaning' in checks[-1]['checks']
            assert 'selectOption' in checks[-1]['error']
        elif run == 'check06':
            assert len(checks) == 2 and checks[0]['status'] == 'PASS'
            assert checks[1]['mode'] == 'normal' and checks[1]['etaSeconds'] >= 180
            assert checks[1]['error'] == 'fare matches max(3.50, 1.50 times ETA minutes)'
    if status != expected[run]:
        sys.exit(f'{run}: unexpected result; stopping calibration')
print('Selected calibration controls matched their expected outcomes.', flush=True)
