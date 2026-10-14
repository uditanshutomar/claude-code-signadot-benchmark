#!/usr/bin/env python3
"""Check the prepared protocol without starting workers or calling a model."""
import json
import pathlib
import subprocess

root = pathlib.Path(__file__).resolve().parents[1]
pins = json.loads((root / 'config/pins.json').read_text())
settings = json.loads((root / 'config/model-settings.json').read_text())
assert settings['model'] == pins['model'] == 'claude-sonnet-5-5'
assert settings['effortLevel'] == pins['effort'] == 'high'
assert pins['billing_source'] == 'existing Claude subscription'
assert pins['codetelemetry_export'].startswith('per collection round')
assert pins['worker_claude_code_version'] == '2.1.296'
assert '@anthropic-ai/claude-code@'+pins['worker_claude_code_version'] in (root/'scripts/prepare-worker.sh').read_text()
assert 'claude_version='+pins['worker_claude_code_version'] in (root/'scripts/configure-worker.sh').read_text()
assert settings['env']['CLAUDE_CODE_DISABLE_1M_CONTEXT'] == '1'
assert settings['env']['DISABLE_AUTOUPDATER'] == '1'
assert settings['autoMemoryEnabled'] is False
suffix = 'Validate your work end to end, including the web UI. If your change breaks anything else, fix it so the app still works.'
extra = 'Use /signadot-validate on the minikube cluster (namespace ctbench-hotrod).'
original = (root / 'source-harness/prompts/HOTROD.md').read_text()
task2 = original.split('## Base Prompt 2\n', 1)[1].split('## Base Prompt 3', 1)[0].strip()
for task in ('t1', 't2'):
    a = (root / 'prompts' / f'{task}-a.txt').read_text().strip()
    b = (root / 'prompts' / f'{task}-b.txt').read_text().strip()
    assert a.endswith(suffix)
    assert b == a + '\n\n' + extra
    if task == 't2':
        assert a == task2 + '\n\n' + suffix
    for arm in ('a', 'b'):
        planned = json.loads(subprocess.check_output(['python3', root / 'scripts/agent-command.py', task, arm]))
        assert planned['execute'] is False
        argv = planned['argv']
        assert argv[argv.index('--model') + 1] == pins['model']
        assert argv[argv.index('--effort') + 1] == pins['effort']
        assert '--fallback-model' not in argv
        assert '--strict-mcp-config' in argv
print('PASS: four prompts, model/effort parity, dry-run commands and telemetry pins')
