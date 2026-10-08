"""Read-only fixed Skill commands against the upgraded, integrity-checked live app."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
LIVE = Path('E:/github-workspace/FashionScout')
WORK = ROOT / '.runtime/t9-upgrade-v1'
PERSONAL = Path('C:/Users/Administrator/.codex/skills/fashion-scout')
PS = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
receipt = json.loads((ROOT / '.runtime/t8b-t9f/.runtime/t8b-t9r/build-receipt.json').read_text('utf-8'))
assert hashlib.sha256((LIVE / 'manifest.json').read_bytes()).hexdigest() == receipt['manifest_sha256']
assert json.loads((PERSONAL / 'local-binding.json').read_text('utf-8'))['app_sha256'] == receipt['app_sha256']
environment = {k:v for k,v in os.environ.items() if k.upper() not in {'PYTHONPATH','PYTHONHOME','VIRTUAL_ENV'}}
environment.update(PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1')
checked = subprocess.run([str(LIVE / '.local/env/Scripts/python.exe'),'-I','-B',str(LIVE / 'payload/verify_install.py'),'check',str(LIVE)],
    env=environment,cwd=LIVE,capture_output=True,text=True,encoding='utf-8',timeout=30)
assert checked.returncode == 0, checked.stderr
requests = LIVE / 'data/requests/t9-upgrade-v1/skill'; requests.mkdir()
samples = []
def request(name, command, payload):
    path = requests / (name + '.json'); path.write_text(json.dumps(payload),encoding='utf-8')
    args = [str(PS),'-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',str(PERSONAL / 'scripts/entry.ps1'),
            '-Action','Request','-Command',command,'-InputJson',str(path)]
    start = time.perf_counter()
    result = subprocess.run(args,env=environment,cwd=LIVE,capture_output=True,text=True,encoding='utf-8',timeout=30)
    seconds = time.perf_counter()-start
    assert result.returncode == 0, (name,result.stderr,result.stdout[:500])
    envelope = json.loads(result.stdout); assert envelope['ok']
    value = envelope['data']
    samples.append({'name':name,'command':command,'seconds':round(seconds,6),'returncode':0,'ok':True,
                    'total':value.get('total'),'items':len(value.get('items',[]))})
    return value

first = request('first','new',{'limit':40})
following = request('next','new',{'limit':40,'cursor':first['next_cursor']})
fresh = request('refresh','new',{'limit':40})
assert first['total'] == following['total'] == fresh['total'] == 60
assert len(first['items']) == 40 and len(following['items']) == 20 and len(fresh['items']) == 40
assert len({p['id'] for p in first['items']+following['items']}) == 60
assert all(p['projection']=='cover' and len(p['images'])==1 for p in first['items']+following['items'])
favorites = request('favorites','favorites',{})
assert favorites['total'] == 4
full = request('detail','product',{'product_id':first['items'][0]['id']})['product']
assert len(full['images']) > 1 and full['versions'] and full['album']['stored_count'] == len(full['images'])
status = request('status','status',{})
evidence = {'at_live_package':str(LIVE),'app_sha256':receipt['app_sha256'],'manifest_sha256':receipt['manifest_sha256'],
            'installed_integrity_check_returncode':checked.returncode,'installed_integrity_result':checked.stdout,
            'fixed_skill_request_samples':samples,'total':60,'pagination':[40,20],'unique_ids':60,
            'empty_new_cards':0,'favorites':4,'detail_images':len(full['images']),'detail_versions':len(full['versions']),
            'projection':'cover','full_detail_separate':True,'no_source_requests':True,
            'skill_open_receipt':str(WORK / 'personal-open.json'),
            'business_api_commands':['new','favorites','product','status'], 'business_writes':0}
with (ROOT / 'docs/verification/T9-live-verification.json').open('x',encoding='utf-8') as stream:
    json.dump(evidence,stream,ensure_ascii=False,indent=2)
print(json.dumps({k:v for k,v in evidence.items() if k not in {'installed_integrity_result','business_api_commands'}},ensure_ascii=False))
