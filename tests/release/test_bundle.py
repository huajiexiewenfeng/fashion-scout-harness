import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import uuid
import zipfile

import pytest

ROOT=Path(__file__).resolve().parents[2]
PS=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
CMD=Path(os.environ['SystemRoot'])/'System32/cmd.exe'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture(scope='session')
def release():
    output=ROOT/'.runtime'/('t6b-candidate-'+uuid.uuid4().hex[:8])
    result=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/release/build_bundle.py'),
                           '--output',str(output)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=40)
    assert result.returncode==0,result.stderr
    (output/'build.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    receipt=json.loads((output/'build-receipt.json').read_text('utf-8'))
    work=ROOT/'.runtime'/('t6b-checks-'+uuid.uuid4().hex[:8]);work.mkdir()
    print('T6b candidate:',output);print('T6b checks:',work)
    return receipt,work


def extract(release, label):
    receipt,work=release
    target=work/label;target.mkdir()
    with zipfile.ZipFile(receipt['zip']) as archive:archive.extractall(target)
    return target/'FashionScout'


def invoke(package, action, expected=0, *, env=None, cmd=False, label=None):
    command=(f'"{CMD}" /d /s /c ""{package/({"Prepare":"01 Prepare.cmd","Open":"02 Open.cmd","Stop":"03 Stop.cmd"}[action])}""'
             if cmd else [str(PS),'-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',str(package/'package.ps1'),'-Action',action])
    result=subprocess.run(command,cwd=package,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=130,
                          stdin=subprocess.DEVNULL)
    record={'argv':command,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
    log=package.parent/(label or (action+'-'+uuid.uuid4().hex[:6]+'.json'))
    log.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    assert result.returncode==expected,record
    return record


def test_bundle_immutable_inputs_and_no_user_data(release):
    receipt,_=release
    assert sha(Path(receipt['zip']))==receipt['zip_sha256']
    with zipfile.ZipFile(receipt['zip']) as archive:
        names=archive.namelist()
        assert not any('/data/' in n or '/.local/' in n or n.endswith(('.key','.sqlite3')) for n in names)
        manifest=json.loads(archive.read('FashionScout/manifest.json'))
        assert len(manifest['dependencies'])==26
        assert manifest['app_sha256']=='9beaa9f5e49063fdb5b36d906b8bac5d1d5a46772f4c5b90a10782a77b772f15'
        assert manifest['runtime_sha256']=='ec43f1a85c29f147d7ae2d13218c52c70b24a983a82ab22d6c607c0593060e10'
        for member in manifest['files']:
            data=archive.read('FashionScout/'+member['path'])
            assert len(data)==member['bytes'] and hashlib.sha256(data).hexdigest()==member['sha256']
        assert any('/licenses/runtime/LICENSE.txt' in n for n in names)


@pytest.mark.parametrize('case',['damaged-wheel','missing-resource','existing-data','config-conflict'])
def test_prepare_rejects_before_touching_data(release,case):
    package=extract(release,case)
    if case=='damaged-wheel':
        p=package/'payload/fashion_scout-0.2.0a1-py3-none-any.whl';p.write_bytes(p.read_bytes()+b'changed')
    elif case=='missing-resource':
        (package/'payload/verify_install.py').unlink()
    else:
        data=package/'data';data.mkdir();(data/'keep.bin').write_bytes(b'USER DATA MUST REMAIN')
        if case=='config-conflict':
            (data/'control').mkdir();(data/'control/client.json').write_text(json.dumps({'schema':1,'data_root':'C:\\UnrelatedRoot','port':8765}),encoding='utf-8')
    original={p.relative_to(package).as_posix():sha(p) for p in (package/'data').rglob('*') if p.is_file()}
    result=invoke(package,'Prepare',2)
    assert ('hash mismatch' if case=='damaged-wheel' else 'missing' if case=='missing-resource' else 'Existing data') in result['stdout']
    assert not (package/'.local').exists()
    assert original=={p.relative_to(package).as_posix():sha(p) for p in (package/'data').rglob('*') if p.is_file()}


def test_real_prepare_failure_preserves_existing_configuration(release):
    package=extract(release,'prepare failure')
    data=package/'data';(data/'control').mkdir(parents=True)
    config=data/'control/client.json';config.write_text(json.dumps({'schema':1,'data_root':str(data),'port':8765}),encoding='utf-8')
    keep=data/'keep.bin';keep.write_bytes(b'EXISTING OWN DATA')
    original=(sha(config),sha(keep))
    env=dict(os.environ);env['PATH']=''  # Only this test child; tar.exe cannot start.
    result=invoke(package,'Prepare',2,env=env,label='real-install-failure.json')
    assert 'tar.exe' in result['stdout'] and (package/'.local/preparing.json').exists()
    assert not (package/'.local/ready.json').exists()
    assert original==(sha(config),sha(keep)) and not (data/'scout.sqlite3').exists()
    retry=invoke(package,'Prepare',2,label='incomplete-repeat-refused.json')
    assert 'incomplete' in retry['stdout'] and original==(sha(config),sha(keep))


def test_long_path_refused_before_preparation(release):
    _,work=release
    label='超界 中文 空格 '+('x'*(101-len(str(work/'超界 中文 空格 '/ 'FashionScout'))))
    package=extract(release,label)
    assert len(str(package))==101
    (package/'data').mkdir();keep=package/'data/preserve.txt';keep.write_bytes(b'OWN USER DATA')
    original=sha(keep)
    result=invoke(package,'Prepare',2,label='long-path-refusal.json')
    assert 'maximum 100 characters' in result['stdout']
    assert not (package/'.local').exists() and sha(keep)==original


def test_independent_zip_install_entries_and_synthetic_export(release):
    receipt,work=release
    label="真实解压 空格 & 单引号's"
    label+='x'*(100-len(str(work/label/'FashionScout')))
    package=extract(release,label)
    assert len(str(package))==100
    env={k:v for k,v in os.environ.items() if k.upper() not in {'PYTHONPATH','PYTHONHOME','VIRTUAL_ENV'}}
    env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1')
    missing=invoke(package,'Open',2,env=env,label='open-before-prepare.json')
    assert 'Prepare.cmd first' in missing['stdout']
    invoke(package,'Prepare',env=env,cmd=True,label='install-original.json')
    data=package/'data';config=data/'control/client.json'
    assert json.loads(config.read_text('utf-8'))=={'schema':1,'data_root':str(data),'port':8765}
    assert not (data/'scout.sqlite3').exists() and not (data/'control/runtime.json').exists()
    python=package/'.local/env/Scripts/python.exe'
    installed=package/'.local/env/Lib/site-packages'
    pip=subprocess.run([str(python),'-I','-B','-m','pip','--isolated','--disable-pip-version-check','check'],cwd=package,env=env,
                       capture_output=True,text=True,encoding='utf-8',timeout=15)
    (package.parent/'pip-check.json').write_text(json.dumps({'returncode':pip.returncode,'stdout':pip.stdout,'stderr':pip.stderr}),encoding='utf-8')
    assert pip.returncode==0 and 'No broken requirements' in pip.stdout
    with zipfile.ZipFile(ROOT/'.runtime/t5c-r1-wheel/fashion_scout-0.2.0a1-py3-none-any.whl') as wheel:
        for name in wheel.namelist():
            if name.startswith('fashion_scout/') and not name.endswith('/'):assert (installed/name).read_bytes()==wheel.read(name)
    audit=package.parent/'imports';audit.mkdir();env['T6A_AUDIT_DIR']=str(audit)
    # Test-only guard records real module origins and intercepts only final OS browser open.
    shutil.copyfile(ROOT/'tests/integration/readiness_sitecustomize.py',installed/'sitecustomize.py')
    sentinel=data/'preserve.txt';sentinel.write_text('own data preserved',encoding='utf-8');before=(sha(config),sha(sentinel))
    invoke(package,'Prepare',env=env,label='repeat-prepare.json')
    assert before==(sha(config),sha(sentinel))
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1',8765));occupied.listen(1)
        conflict=invoke(package,'Open',3,env=env,label='port-conflict.json')
        assert 'PORT_IN_USE' in conflict['stdout']
        assert occupied.getsockname()[1]==8765
    try:
        invoke(package,'Open',env=env,cmd=True,label='open-original.json')
        descriptor=json.loads((data/'control/runtime.json').read_text('utf-8'))
        invoke(package,'Open',env=env,cmd=True,label='open-repeat.json')
        repeat=json.loads((data/'control/runtime.json').read_text('utf-8'))
        assert descriptor['instance']==repeat['instance'] and descriptor['processes']==repeat['processes']
        flow=package.parent/'flow'
        command=[str(python),'-I','-B',str(ROOT/'tests/release/probe_flow.py'),str(package),str(ROOT),str(flow)]
        result=subprocess.run(command,cwd=package,env=env,capture_output=True,text=True,encoding='utf-8',timeout=80)
        (package.parent/'flow-original.json').write_text(json.dumps({'argv':command,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr},ensure_ascii=False,indent=2),encoding='utf-8')
        assert result.returncode==0 and not result.stderr,result.stdout+result.stderr
    finally:
        invoke(package,'Stop',env=env,cmd=True,label='stop-original.json')
    check=[str(python),'-I','-B','-c',
           'import sys,json; from fashion_scout.config import Paths; from fashion_scout import launcher; p=Paths.at(sys.argv[1]);d=launcher.read_descriptor(p); live={r:bool(launcher.verified_process(p,d,r)) for r in ("web","worker")}; assert not any(live.values()); print(json.dumps(live))',str(data)]
    stopped=subprocess.run(check,cwd=package,env=env,capture_output=True,text=True,encoding='utf-8',timeout=15)
    assert stopped.returncode==0 and not stopped.stderr
    records=[json.loads(p.read_text('utf-8')) for p in audit.glob('*.json')]
    services=set()
    for record in records:
        assert not record['editable_finders'] and not record['blocked_network']
        assert str(ROOT/'src') not in record['sys_path'] and str(ROOT/'.venv/Lib/site-packages') not in record['sys_path']
        for name,path in record['modules'].items():
            if name.startswith('fashion_scout'):assert Path(path).is_relative_to(installed/'fashion_scout')
        if '--instance' in record['argv']:
            services.add(Path(record['modules']['__main__']).stem)
    assert services=={'health','worker'}
    assert len([r for r in records if r['browser_open_intercepted']])==2
    # Actual installed static resource disappearance must give a useful refusal.
    resource=installed/'fashion_scout/static/app.css';resource.unlink()
    damaged=invoke(package,'Open',2,env=env,label='installed-resource-missing.json')
    assert 'Installed file changed or missing' in damaged['stderr']+damaged['stdout']
    report={'zip':receipt,'package':str(package),'provenance':records,'stopped':json.loads(stopped.stdout),
            'flow':json.loads((flow/'evidence.json').read_text('utf-8')),'browser_action':'intercepted test-only OS open',
            'source_requests':0,'whole_machine_restart_tested':False,'clean_new_computer_tested':False}
    (work/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
