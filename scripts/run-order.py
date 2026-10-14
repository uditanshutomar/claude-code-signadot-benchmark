#!/usr/bin/env python3
"""Print the preregistered order. Never launches a run."""
import argparse,csv,json,pathlib
p=argparse.ArgumentParser();p.add_argument('--ledger',type=pathlib.Path);args=p.parse_args()
extensions={}
if args.ledger:
    rows=list(csv.DictReader(args.ledger.open()))
    for task in ('t1','t2'):
        counts={}
        for arm in ('a','b'):
            # Harness errors and contaminated attempts stay in the ledger but their clean reruns are what count.
            valid=[r for r in rows if r['task']==task and r['arm']==arm and int(r['rep'])<=5
                   and r['initial_verdict']!='HARNESS_ERROR' and r['final_verdict']!='HARNESS_ERROR' and r['notes'].startswith('primary')
                   and 'contaminat' not in r['notes'].lower()]
            if len(valid)!=5 or {int(r['rep']) for r in valid}!=set(range(1,6)):
                raise SystemExit('Need five distinct, uncontaminated primary repetitions per arm before deciding extensions')
            if any(r['initial_verdict']=='NEEDS_TRANSCRIPT_REVIEW' for r in valid):
                raise SystemExit('Resolve transcript review before deciding extensions')
            counts[arm]=sum(r['initial_verdict']=='VERIFIED_CORRECT' for r in valid)
        extensions[task]=abs(counts['a']-counts['b'])<4
order=[]
for task in ('t1','t2'):
    for rep in range(1,11 if extensions.get(task) else 6):
        for arm in ('a','b'): order.append({'task':task,'arm':arm,'rep':rep})
print(json.dumps({'execute':False,'order':order,'extensions':extensions},indent=2))
