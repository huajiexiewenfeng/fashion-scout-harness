import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import venv
import zipfile

ROOT=Path(__file__).resolve().parents[2]
WHEEL=ROOT/'.runtime/t5c-r1-wheel/fashion_scout-0.2.0a1-py3-none-any.whl'
EXPECTED='9beaa9f5e49063fdb5b36d906b8bac5d1d5a46772f4c5b90a10782a77b772f15'


def test_readiness_shipped_wheel_isolated_entry():
    assert hashlib.sha256(WHEEL.read_bytes()).hexdigest()==EXPECTED
    work=ROOT/'.runtime'/('t6a-package-'+uuid.uuid4().hex[:8]);work.mkdir()
    envdir=work/'env';venv.EnvBuilder(with_pip=False).create(envdir)
    site=envdir/'Lib/site-packages';audit=work/'imports';audit.mkdir()
    with zipfile.ZipFile(WHEEL) as z:
        names=z.namelist();assert all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in names)
        assert len([n for n in names if n.endswith('.sql')])==9
        z.extractall(site)
        package_names=[n for n in names if n.startswith('fashion_scout/') and not n.endswith('/')]
        for name in package_names:assert (site/name).read_bytes()==z.read(name)
    # A plain path .pth reuses installed dependencies without executing the old editable .pth.
    (site/'locked-dependencies.pth').write_text(str(ROOT/'.venv/Lib/site-packages')+'\n',encoding='utf-8')
    shutil.copyfile(ROOT/'tests/integration/readiness_sitecustomize.py',site/'sitecustomize.py')
    env={k:v for k,v in os.environ.items() if k.upper() not in {'PYTHONPATH','PYTHONHOME','VIRTUAL_ENV'}}
    env.update(T6A_AUDIT_DIR=str(audit),PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1')
    command=[str(envdir/'Scripts/python.exe'),'-B',str(ROOT/'tests/integration/readiness_scenario.py'),str(ROOT),str(work)]
    result=subprocess.run(command,cwd=work,env=env,capture_output=True,text=True,encoding='utf-8',timeout=110)
    (work/'commands.txt').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
    print('T6a package root:',work);assert result.returncode==0,result.stdout[-3500:]+result.stderr
    records=[json.loads(p.read_text('utf-8')) for p in audit.glob('*.json')]
    roles=set();seen=set()
    for record in records:
        assert not record['blocked_network'] and not record['editable_finders'],record
        assert str(ROOT/'src') not in record['sys_path']
        for name,path in record['modules'].items():
            if name!='__main__' or 'fashion_scout' in path:
                assert Path(path).is_relative_to(site/'fashion_scout'),path;seen.add(name)
            if name=='__main__' and Path(path).name in {'health.py','worker.py'} and '--instance' in record['argv']:roles.add(Path(path).stem)
    assert roles=={'health','worker'}
    assert any(Path(r['modules'].get('__main__','')).name=='restore.py' and '--data-root' in r['argv'] for r in records)
    assert any(r['browser_open_intercepted'] for r in records)
    with zipfile.ZipFile(WHEEL) as z:
        for name in package_names:assert (site/name).read_bytes()==z.read(name)
    scenario=json.loads((work/'scenario.json').read_text('utf-8'))
    from_code=scenario['models'];doc=(ROOT/'skills/fashion-scout/references/commands.md').read_text('utf-8')
    assert all(command in doc for command in from_code)
    report={'wheel':str(WHEEL),'sha256':EXPECTED,'work':str(work),'package_files':len(package_names),'migrations':9,
            'entry_command':command,'returncode':result.returncode,'provenance':records,'scenario':scenario,
            'fixed_commands':from_code,'entry_points':'python -m modules; no console_scripts declared',
            'dependencies':'Existing locked project site-packages via plain .pth; no pip/download/editable hook',
            'source_requests':0,'global_install':False,'browser_rendering':False}
    (work/'evidence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
