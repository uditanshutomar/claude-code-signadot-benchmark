"""Verify a future manually reviewed freeze. Does not create or approve one."""
import hashlib, pathlib, subprocess
from reset_worker import ROOT

def source_hashes():
    paths=[p for folder in ('config','scripts','grader','prompts') for p in (ROOT/folder).rglob('*')
           if p.is_file() and '__pycache__' not in p.parts]
    paths += [ROOT/'grade.sh',ROOT/'run-one.sh',ROOT/'PROTOCOL.md']
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}

def verify_freeze(record):
    if record.get('source_hashes')!=source_hashes(): raise RuntimeError('Protocol changed or is not frozen')
    revision=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
    if record.get('commit')!=revision: raise RuntimeError('Freeze must identify the current source commit')
    dirty=subprocess.check_output(['git','-C',str(ROOT),'status','--porcelain','--','config','scripts','grader','prompts','grade.sh','run-one.sh','PROTOCOL.md'],text=True).strip()
    if dirty: raise RuntimeError('Frozen sources differ from the committed version')
    if record.get('approved') is not True: raise RuntimeError('Protocol requires human approval')
    if record.get('cost_resume_reconciled') is not True: raise RuntimeError('Initial/resume cost reconciliation is missing')
    if record.get('telemetry_delivery_verified') is not True: raise RuntimeError('End-to-end telemetry verification is missing')
    smokes=record.get('smoke_evidence',{})
    if set(smokes)!={'t1-a','t1-b','t2-a','t2-b'}: raise RuntimeError('All four task/arm smokes are required')
    for path in smokes.values():
        target=(ROOT/path).resolve()
        if not target.is_relative_to(ROOT/'runs') or not target.is_file(): raise RuntimeError('Missing smoke evidence')
