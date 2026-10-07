"""T6d delivery-only offline smoke. Never creates a Run or contacts a source."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[2]
FINAL=ROOT/'.runtime/t6c-final-browser-v1'
STAGE=ROOT/'.runtime/t2-browser-live-20261007-01'
SHA='5938b20f707c73ebc0042d115abdd7e04d3bf62dd9799362be595afa52393753'
PS=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
CMD=Path(os.environ['SystemRoot'])/'System32/cmd.exe'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    receipt=json.loads((FINAL/'build-receipt.json').read_text('utf-8'))
    provenance=json.loads((STAGE/'build-provenance.json').read_text('utf-8'))
    assert receipt['app_sha256']==provenance['wheel_sha256']==SHA
    wheel=Path(receipt['app_wheel']);assert sha(wheel)==SHA
    assert len(provenance['members'])==72 and sha(ROOT/'requirements-win.lock')==provenance['lock_sha256']
    for relative,digest in provenance['source_sha256'].items():assert sha(STAGE/'source'/relative)==digest
    assert sha(STAGE/'source/pyproject.toml')==provenance['pyproject_sha256']
    archive_path=Path(receipt['zip']);assert sha(archive_path)==receipt['zip_sha256']
    work=ROOT/'.runtime'/('t6c-d-smoke-'+uuid.uuid4().hex[:8]);work.mkdir()
    records=[]
    with zipfile.ZipFile(archive_path) as archive:
        assert not any('/data/' in n or '/.local/' in n or n.endswith(('.key','.sqlite3','.log')) for n in archive.namelist())
        archive.extractall(work)
    package=work/'FashionScout';assert len(str(package).encode('utf-16-le'))//2<=100
    manifest=json.loads((package/'manifest.json').read_text('utf-8'))
    for member in manifest['files']:
        path=package/member['path'];assert sha(path)==member['sha256'] and path.stat().st_size==member['bytes']
    assert len(manifest['skill_files'])==4
    for relative,digest in manifest['skill_files'].items():assert sha(package/relative)==sha(ROOT/relative)==digest
    env={k:v for k,v in os.environ.items() if k.upper() not in {'PYTHONPATH','PYTHONHOME','VIRTUAL_ENV'}}
    env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1')
    python=package/'.local/env/Scripts/python.exe';data=package/'data'
    def run(command,label,expected=0):
        result=subprocess.run(command,cwd=package,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',
                              stdin=subprocess.DEVNULL,timeout=130)
        record={'label':label,'argv':command,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
        records.append(record);print(json.dumps(record,ensure_ascii=True),flush=True)
        (work/(label+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        assert result.returncode==expected,record
        return result
    def entry(action):
        filename={'Prepare':'01 Prepare.cmd','Open':'02 Open.cmd','Stop':'03 Stop.cmd'}[action]
        return run(f'"{CMD}" /d /s /c ""{package/filename}""',action.lower())
    entry('Prepare')
    assert not (data/'scout.sqlite3').exists() and not (data/'control/runtime.json').exists()
    configured=json.loads((data/'control/client.json').read_text('utf-8'))
    assert configured=={'schema':1,'data_root':str(data),'port':8765}
    run([str(python),'-I','-B','-m','pip','--isolated','--disable-pip-version-check','check'],'pip-check')
    installed=package/'.local/env/Lib/site-packages/fashion_scout'
    with zipfile.ZipFile(wheel) as archive:
        names=[n for n in archive.namelist() if n.startswith('fashion_scout/')]
        assert len(names)==72 and sum(n.endswith('.sql') for n in names)==10
        for name in names:assert (installed.parent/name).read_bytes()==archive.read(name)
    audit=work/'imports';audit.mkdir();env['T6A_AUDIT_DIR']=str(audit)
    # Only the smoke copy gets this existing test hook. It is absent from the delivery ZIP.
    shutil.copyfile(ROOT/'tests/integration/readiness_sitecustomize.py',installed.parent/'sitecustomize.py')
    def cli(command,payload,expected=0):
        file=work/(command+'.input.json');file.write_text(json.dumps(payload),encoding='utf-8')
        return run([str(python),'-I','-B','-m','fashion_scout.client','request',command,'--data-root',str(data),'--json-input',str(file)],command,expected)
    try:
        entry('Open')
        cli('status',{});cli('new',{});cli('favorites',{});cli('sites',{});cli('latest',{})
        result=run([str(python),'-I','-B','-c',
                    'import json; from fashion_scout.client_models import MODELS; print(json.dumps(sorted(MODELS)))'],'command-inventory')
        commands=json.loads(result.stdout)
        browser={'browser-status','browser-attach','browser-continue','browser-observe','browser-upload','browser-asset-failure'}
        assert browser<=set(commands) and all(c in (package/'skills/fashion-scout/references/commands.md').read_text('utf-8') for c in browser)
        # Read-only fixed browser entry must be recognized and reject a nonexistent Run.
        file=work/'browser-status.input.json';file.write_text('{"run_id":"t6d-no-run"}',encoding='utf-8')
        cmd=[str(python),'-I','-B','-m','fashion_scout.client','request','browser-status','--data-root',str(data),'--json-input',str(file)]
        result=subprocess.run(cmd,cwd=package,env=env,capture_output=True,text=True,encoding='utf-8',timeout=20)
        record={'label':'browser-status-empty','argv':cmd,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
        records.append(record);print(json.dumps(record),flush=True);(work/'browser-status-empty.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        parsed=json.loads(result.stdout);assert result.returncode!=0 and parsed['error']['code'] not in {'COMMAND_NOT_ALLOWED','INVALID_ARGUMENTS'}
        connection=sqlite3.connect((data/'scout.sqlite3').as_uri()+'?mode=ro',uri=True)
        counts={'runs':connection.execute('SELECT COUNT(*) FROM runs').fetchone()[0],
                'run_intents':connection.execute('SELECT COUNT(*) FROM run_requests').fetchone()[0],
                'source_http':connection.execute('SELECT COUNT(*) FROM collection_http').fetchone()[0]}
        migrations=[r[0] for r in connection.execute('SELECT version FROM schema_migrations ORDER BY version')]
        browser_tables={r[0]:connection.execute('SELECT COUNT(*) FROM '+r[0]).fetchone()[0]
                        for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'browser_%'").fetchall()}
        connection.close()
        assert counts=={'runs':0,'run_intents':0,'source_http':0} and migrations==list(range(1,11)) and not any(browser_tables.values())
    finally:
        entry('Stop')
    result=run([str(python),'-I','-B','-c',
                'import sys,json; from fashion_scout.config import Paths; from fashion_scout import launcher; p=Paths.at(sys.argv[1]);d=launcher.read_descriptor(p);live={r:bool(launcher.verified_process(p,d,r)) for r in ("web","worker")};assert not any(live.values());print(json.dumps(live))',str(data)],'verified-exit')
    origins=[json.loads(path.read_text('utf-8')) for path in audit.glob('*.json')]
    roles=set()
    for origin in origins:
        assert not origin['blocked_network'] and not origin['editable_finders']
        assert str(ROOT/'src') not in origin['sys_path'] and str(ROOT/'.venv/Lib/site-packages') not in origin['sys_path']
        for name,path in origin['modules'].items():
            if name.startswith('fashion_scout'):assert Path(path).is_relative_to(installed)
        if '--instance' in origin['argv']:roles.add(Path(origin['modules']['__main__']).stem)
    assert roles=={'health','worker'} and any(o['browser_open_intercepted'] for o in origins)
    for name,digest in provenance['members'].items():assert sha(installed.parent/name)==digest
    report={'work':str(work),'package':str(package),'package_root_utf16':len(str(package).encode('utf-16-le'))//2,
            'delivery':receipt,'stage_provenance_sha256':sha(STAGE/'build-provenance.json'),'records':records,'module_origins':origins,
            'wheel_members_verified':72,'migrations':migrations,'empty_counts':counts,'browser_tables':browser_tables,
            'fixed_browser_commands':sorted(browser),'stopped':json.loads(result.stdout),
            'OS_browser_action':'test-only intercepted; actual browser rendering not repeated','source_requests':0,'skill_files':manifest['skill_files']}
    (work/'smoke-evidence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'smoke_passed':True,'work':str(work),'members':72,'schema':10,'empty':counts,'stopped':report['stopped']},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
