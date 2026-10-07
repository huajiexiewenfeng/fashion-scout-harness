"""Read-only scoped delivery audit. Output is new and immutable by default."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
from fashion_scout.config import Paths
from fashion_scout import launcher
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
ALLOWED={
 'src/fashion_scout/client.py','src/fashion_scout/client_models.py','src/fashion_scout/worker.py',
 'src/fashion_scout.egg-info/SOURCES.txt','src/fashion_scout/api/routes.py',
 'src/fashion_scout/exports/engine.py','src/fashion_scout/exports/models.py',
 'src/fashion_scout/static/app.css','src/fashion_scout/templates/index.html',
 'tests/api/test_interface.py','tests/client/test_client.py','tests/client/test_local_integration.py',
 'tests/core/test_runs.py','tests/core/test_worker_repairs.py','tests/exports/test_engine.py',
 'skills/fashion-scout/SKILL.md','skills/fashion-scout/references/commands.md'}


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def save(name,value):
    with (ROOT/'docs/verification'/name).open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)


def main():
    baseline=json.loads((ROOT/'docs/verification/T5b-baseline.json').read_text('utf-8'))
    changed={p.replace('\\','/') for p,h in baseline.items() if sha(ROOT/p)!=h}
    assert changed<=ALLOWED,changed-ALLOWED
    protected={p:h for p,h in baseline.items() if p.replace('\\','/') not in ALLOWED}
    selected={}
    for pattern in ('t5b-recovery-*','t5b-http-cli-*','t5b-web-exit-*','t5b-t4-regression-*'):
        for root in (ROOT/'.runtime').glob(pattern):
            p=root/('integration-evidence.json' if 't4-regression' in root.name else 'evidence.json')
            if not p.exists():continue
            data=json.loads(p.read_text('utf-8'))
            key=pattern+data.get('mode','')+data.get('stop_kind','')
            if key not in selected or p.stat().st_mtime>selected[key][0].stat().st_mtime:selected[key]=(p,data)
    process=[{'path':str(p),'sha256':sha(p),'data':data} for p,data in selected.values()]
    assert len(process)==6
    assert all(x['data']['stop']['stopped'] for x in process)
    save('T5b-process-evidence-v1.json',process)
    browser=json.loads((ROOT/'.runtime/t5b-browser-v1/browser-evidence.json').read_text('utf-8'))
    assert browser['job_count']==browser['attempt_count']==1 and browser['source_requests']==0
    download=Path(browser['browser_download']['path'])
    assert sha(download)==browser['exports'][0]['sha256']
    sample=ROOT/'docs/verification/T5b-browser-download.zip'
    with sample.open('xb') as target,download.open('rb') as source:shutil.copyfileobj(source,target)
    with zipfile.ZipFile(sample) as z:
        assert z.testzip() is None
        manifest=json.loads(z.read('manifest.json'))
        assert manifest['state']=='partial' and manifest['missing_count']==2
    browser.update(download_copy=str(sample),stop={'stopped':True,'forced_roles':[]},
        ui={'empty_disabled':True,'explicit_click_count':1,'reload_kept_same_job':True,'pending_disabled':True,
            'actual_browser_download':True,'console_warnings_or_errors':[],
            'desktop_viewport':[1440,1000],'desktop_document_width':1425,'desktop_scroll_width':1425,
            'mobile_viewport':[390,844],'mobile_document_width':375,'mobile_scroll_width':375})
    save('T5b-browser-evidence-v1.json',browser)
    services=[]
    for root in (ROOT/'.runtime').glob('t5b-*'):
        if not (root/'control/runtime.json').exists():continue
        paths=Paths.at(root);d=launcher.read_descriptor(paths)
        live=[role for role in ('web','worker') if launcher.verified_process(paths,d,role)]
        assert not live,(root,live)
        services.append({'root':str(root),'descriptor_stopped':d['stopped'],'live_roles':live})
    wheel=next((ROOT/'.runtime/t5b-wheel').glob('*.whl'))
    production=[p for p in (ROOT/'src/fashion_scout').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    with zipfile.ZipFile(wheel) as z:
        for p in production:assert z.read(p.relative_to(ROOT/'src').as_posix())==p.read_bytes(),p
        assert sum(n.startswith('fashion_scout/db/migrations/') for n in z.namelist())==8
    files=production+[ROOT/p for p in changed]
    files += [p for folder in ('tests/exports','skills/fashion-scout') for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    files += [ROOT/'tests/integration/test_export_flow.py',ROOT/'tests/integration/export_process_helper.py']
    files += [p for p in (ROOT/'docs/verification').glob('T5b*') if p.is_file()]
    images={}
    for p in (ROOT/'docs/verification').glob('T5b-browser*.png'):
        with Image.open(p) as im:images[p.name]=list(im.size)
    value={'version':'T5b-local-v1','generated_at':datetime.now(timezone.utc).isoformat(),
        'protected_count':len(protected),'protected_sha256':protected,'protected_changes':[],
        'expected_baseline_changes':sorted(changed),'isolated_services':services,'screenshots':images,
        'wheel':{'path':str(wheel),'sha256':sha(wheel),'production_files_matched':len(production),'migrations':8},
        'source_network_requests':0,'sha256':{str(p.relative_to(ROOT)):sha(p) for p in sorted(set(files))}}
    save('T5b-evidence-v1.json',value)
    print(json.dumps({'protected_count':len(protected),'protected_changes':[], 'wheel':value['wheel'],
        'evidence':str(ROOT/'docs/verification/T5b-evidence-v1.json'),'stopped_roots':len(services),'file_hashes':len(value['sha256'])}))


if __name__=='__main__':main()
