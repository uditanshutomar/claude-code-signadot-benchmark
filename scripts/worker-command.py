#!/usr/bin/env python3
"""Run one command with a recorded deadline. No model-specific behavior."""
import argparse, json, os, pathlib, signal, subprocess, time


def execute(command, seconds, record, grace=30):
    start=time.monotonic()
    child=subprocess.Popen(command,start_new_session=True)
    deadline=False
    try:
        code=child.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        deadline=True
        os.killpg(child.pid,signal.SIGTERM)
        try: code=child.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid,signal.SIGKILL);code=child.wait()
    data={'deadline_expired':deadline,'child_exit_code':code,
          'duration_ms':round((time.monotonic()-start)*1000),
          'termination_reason':'deadline' if deadline else ('signal' if code<0 else 'exit')}
    pathlib.Path(record).write_text(json.dumps(data)+'\n')
    return 124 if deadline else (128-code if code<0 else code)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--seconds',type=float,required=True)
    p.add_argument('--record',required=True);p.add_argument('command',nargs=argparse.REMAINDER)
    a=p.parse_args();raise SystemExit(execute(a.command,a.seconds,a.record))
