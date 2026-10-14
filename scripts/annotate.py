#!/usr/bin/env python3
"""Apply reviewed transcript observations without altering blind grading evidence."""
import argparse, csv, fcntl, json, pathlib, re
from reset_worker import ROOT
from run_one import FIELDS, summarize
from classify import classify


def review(records, observations):
    if set(observations)!={str(r['round']) for r in records}: raise ValueError('Review every round')
    reviewed=[]
    for record in records:
        note=observations[str(record['round'])]
        for field in ('task_present','declared_done','reported_unfixed_break','skill_invoked','cli_fallback'):
            if not isinstance(note.get(field),bool): raise ValueError('Explicit boolean required: '+field)
        if not note.get('evidence'): raise ValueError('Cite transcript file and line numbers for each assessment')
        if not isinstance(note.get('services_touched'),list): raise ValueError('List services touched')
        status='HARNESS_ERROR' if record['agent'].get('harness_error') else record['grade']['grade_status']
        verdict=classify(status,timed_out=record['agent']['timed_out'],**{k:note[k] for k in ('task_present','declared_done','reported_unfixed_break')})
        if verdict=='NEEDS_TRANSCRIPT_REVIEW': raise ValueError('Evidence does not yet support a final verdict')
        reviewed.append(dict(record,verdict=verdict))
    return reviewed


def main():
    p=argparse.ArgumentParser();p.add_argument('run_id');p.add_argument('observations',type=pathlib.Path);a=p.parse_args()
    if not re.fullmatch(r'r[a-f0-9]{12}',a.run_id): p.error('Expected opaque run ID')
    out=ROOT/'runs'/a.run_id
    with (ROOT/'private/runner.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        notes=json.loads(a.observations.read_text());records=[json.loads(p.read_text()) for p in sorted(out.glob('round-*/outcome.json'))]
        reviewed=review(records,notes)
        row=json.loads((out/'run.json').read_text());harness_error=row['final_verdict']=='HARNESS_ERROR'
        summarize(row,reviewed)
        if harness_error: row['final_verdict']='HARNESS_ERROR'
        row['declared_done']=notes['0']['declared_done']
        row['skill_invoked']=any(n['skill_invoked'] for n in notes.values())
        row['cli_fallback']=any(n['cli_fallback'] for n in notes.values())
        row['services_touched']=';'.join(sorted({s for n in notes.values() for s in n['services_touched']}))
        row['first_break_seen_utc']=min((n['first_break_seen_utc'] for n in notes.values() if n.get('first_break_seen_utc')),default='')
        (out/'transcript-review.json').write_text(json.dumps({'observations':notes,'outcomes':reviewed},indent=2)+'\n')
        # Preserve the original machine record. The reviewed ledger is the analysis input.
        (out/'reviewed-run.json').write_text(json.dumps(row,indent=2)+'\n')
        ledger=ROOT/'ledger.csv';rows=list(csv.DictReader(ledger.open()))
        if sum(r['run_id']==a.run_id for r in rows)!=1: raise RuntimeError('Expected exactly one ledger row')
        temporary=ledger.with_suffix('.tmp')
        with temporary.open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader()
            writer.writerows(row if r['run_id']==a.run_id else r for r in rows)
        temporary.replace(ledger)

if __name__=='__main__':main()
