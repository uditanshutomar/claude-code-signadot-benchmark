"""Validate measurements and retain only Claude project/session artifacts."""
import hashlib, json, math, pathlib, tarfile


def cost_delta(total, previous, initial=False):
    valid=lambda x:isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and x>=0
    if not valid(total) or (not initial and not valid(previous)): return None
    if initial: return total
    return round(total-previous,12) if total>=previous else None


def inspect_stream(text, session, model, exit_code, termination):
    events=[];error=None
    deadline=termination.get('deadline_expired') is True
    lines=text.splitlines()
    for index,line in enumerate(lines):
        try:
            event=json.loads(line)
            if not isinstance(event,dict): raise ValueError('not an object')
            events.append(event)
        except ValueError:
            if not (deadline and index==len(lines)-1 and not text.endswith('\n')):
                error='Malformed stream-json transcript'
    results=[e for e in events if e.get('type')=='result']
    result=results[-1] if results else {}
    models=set(result.get('modelUsage',{}))
    sessions={e['session_id'] for e in events if e.get('session_id')}
    if not termination: error='Missing worker termination record; inspect connection or worker failure'
    elif not deadline and (exit_code or not results or result.get('is_error')): error='Agent process/API failure; inspect transcript'
    elif sessions!={session} and (sessions or not deadline): error='Missing or unexpected session ID'
    elif models!={model} and not deadline: error='Missing or unexpected response model'
    elif models and models!={model}: error='Unexpected response model'
    return result,deadline,error


# Run within the worker. Export the fresh project's session tree, not the home or auth config.
ARCHIVE_SCRIPT=r'''
import io,os,pathlib,sys,tarfile
home=pathlib.Path.home()/'.claude/projects'
session=sys.argv[1]
logs=list(home.glob('*/'+session+'.jsonl'))
if len(logs)!=1: raise SystemExit('Expected exactly one persisted session')
project=logs[0].parent
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz') as archive:
    for path in sorted(project.rglob('*')):
        if path.is_symlink(): raise SystemExit('Unexpected symlink in session evidence')
        if path.is_file():
            archive.add(path,arcname=str(path.relative_to(home)),recursive=False)
'''


def verify_archive(path, session):
    files=[]
    with tarfile.open(path,'r:gz') as archive:
        for member in archive:
            parts=pathlib.PurePosixPath(member.name).parts
            if member.name.startswith('/') or '..' in parts or not member.isfile():
                raise RuntimeError('Unsafe session archive member')
            if len(parts)<2 or any(p in ('.credentials.json','settings.json','.claude.json') for p in parts):
                raise RuntimeError('Non-session configuration in archive')
            data=archive.extractfile(member).read()
            files.append({'path':member.name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    if not any(pathlib.PurePosixPath(f['path']).name==session+'.jsonl' for f in files):
        raise RuntimeError('Persisted session is missing from archive')
    return {'archive_sha256':hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest(),'files':files}


def export_summary(path):
    """Per-round proof of telemetry delivery from the relay's log: every export and how many failed."""
    if not path.is_file(): return None
    rows=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    # 'foreign' rows are other processes (e.g. the app under test) that reached the relay without the ingest key.
    own=[r for r in rows if r.get('status')!='foreign']
    return {'requests':len(own),'failed':sum(1 for r in own if r.get('status')!=200),'foreign':len(rows)-len(own)}


def telemetry_problem(summary):
    """A collected round counts only if the relay recorded exports and every one was delivered."""
    if not summary: return 'no relay export log'
    if summary['requests']==0: return 'relay recorded no exports'
    if summary['failed']: return f"{summary['failed']} of {summary['requests']} exports not delivered"
    return None
