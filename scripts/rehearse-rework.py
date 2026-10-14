#!/usr/bin/env python3
"""Exercise real diff capture/grading around a scripted edit, without a model."""
import argparse,json,pathlib,subprocess,uuid
from run_one import ROOT,LiveBackend,rounds,keep_worker

p=argparse.ArgumentParser();p.add_argument('prepared_run_id');p.add_argument('control_id');args=p.parse_args()
state=json.loads((ROOT/'private/workers'/args.prepared_run_id/'state.json').read_text())
assert state['ready']
assert args.control_id.startswith('rehearsal-') and args.control_id.replace('-','').isalnum()
out=ROOT/'runs'/args.control_id;out.mkdir(exist_ok=False)
class FixtureBackend(LiveBackend):
    def agent(self,prompt,session,number):
        folder=self.out/f'round-{number}';folder.mkdir()
        (folder/'fixture-input.json').write_text(json.dumps({'prompt':prompt,'session_id':session,'round':number,'model_called':False},indent=2)+'\n')
        if number==1:
            subprocess.run(['git','-C',self.state['workspace'],'apply',str(ROOT/'reference-solutions/t1.patch')],check=True)
        elif number!=0: raise RuntimeError('Reference should pass after the first scripted edit')
        return {'timed_out':False,'resumable':True,'fixture':True}
backend=FixtureBackend(state,out,'t1')
with keep_worker(state['worker']):
    records=rounds(backend,'SCRIPTED FIXTURE: baseline, then reference patch',str(uuid.uuid4()))
assert [r['grade']['grade_status'] for r in records]==['FAIL','PASS']
assert records[-1]['verdict']=='VERIFIED_CORRECT'
(out/'fixture-summary.json').write_text(json.dumps({'model_called':False,'purpose':'orchestration rehearsal, not a benchmark result','records':records},indent=2)+'\n')
print('PASS: baseline failed; scripted reference edit passed; same worker retained; no model called')
