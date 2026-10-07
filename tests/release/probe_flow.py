"""Synthetic business smoke, executed solely by the ZIP-installed interpreter."""
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile

import httpx
from fashion_scout import launcher
from fashion_scout.client import Connection
from fashion_scout.config import Paths
from fashion_scout.db import Database
from fashion_scout.exports.jobs import Jobs
from fashion_scout.services.runs import Runs
from fashion_scout.maintenance.jobs import Jobs as Maintenance
from fashion_scout.maintenance.backup import verify_bundle

package, repository, output = map(lambda p:Path(p).resolve(), sys.argv[1:])
paths = Paths.at(package/'data')
assert Path(sys.prefix).resolve() == package/'.local/env'
assert Path(launcher.__file__).resolve().is_relative_to(package/'.local/env/Lib/site-packages')
assert paths.root.is_relative_to(repository/'.runtime') and paths.root.parent==package
output.mkdir()
evidence = {'synthetic_only':True,'commands':[]}


def cli(command, payload):
    file = output/(command+'.json')
    file.write_text(json.dumps(payload),encoding='utf-8')
    cmd = [sys.executable,'-I','-B','-m','fashion_scout.client','request',command,
           '--data-root',str(paths.root),'--json-input',str(file)]
    result = subprocess.run(cmd,cwd=package,capture_output=True,text=True,encoding='utf-8',timeout=25)
    record={'argv':cmd,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
    print(json.dumps(record),flush=True)
    evidence['commands'].append(record)
    assert result.returncode==0 and not result.stderr,record
    return json.loads(result.stdout)['data']


db = Database(paths.db)
with db.read() as connection:
    evidence['empty']={'runs':connection.execute('SELECT COUNT(*) FROM runs').fetchone()[0],
                       'source_requests':connection.execute('SELECT COUNT(*) FROM collection_http').fetchone()[0],
                       'migrations':[r[0] for r in connection.execute('SELECT version FROM schema_migrations ORDER BY version')]}
assert evidence['empty']=={'runs':0,'source_requests':0,'migrations':list(range(1,10))}
config = json.loads((paths.root/'control/client.json').read_text('utf-8'))
conn = Connection(paths,config['port'])
conn.verify()
with httpx.Client(base_url=f"http://127.0.0.1:{config['port']}",trust_env=False) as http:
    assert http.get('/v1/products').status_code==401
    headers={'Authorization':'Bearer '+conn.token}
    grant=http.post('/v1/session/bootstrap',json={},headers=headers).json()
    assert http.post('/v1/session/exchange',json={'code':grant['bootstrap_url'].split('#')[1]},
                     headers={'Origin':f"http://127.0.0.1:{config['port']}"}).status_code==200
    assert http.get('/').status_code==200
    for name in ('app.js','maintenance.js','maintenance-findings.js','exports.js','app.css'):
        response=http.get('/static/'+name)
        assert response.status_code==200
        assert response.content==(package/'.local/env/Lib/site-packages/fashion_scout/static'/name).read_bytes()
evidence['http']={'session_exchange':True,'page':200,'resources':5,'unauthorized':401}
seed=runpy.run_path(str(repository/'tests/api/helpers.py'))['seed']
seed(Runs(db),paths,count=1)
# Use the production collector's digest-based original layout (without a source request).
with db.write() as connection:
    for asset in connection.execute('SELECT id,relative_path,sha256 FROM assets').fetchall():
        relative='originals/'+asset['sha256'][:2]+'/'+asset['sha256']+'.png'
        target=paths.media/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(paths.media/asset['relative_path'],target)
        connection.execute('UPDATE assets SET relative_path=? WHERE id=?',(relative,asset['id']))
assert cli('new',{})['total']==1
product=cli('product',{'product_id':'fixture-000'})['product']
cli('user-state',{'product_id':'fixture-000','expected_revision':product['user_state']['revision'],'favorite':True})
assert cli('favorites',{})['total']==1
job=cli('export',{'new_intent':True})['result']['export']
end=time.monotonic()+20
while time.monotonic()<end:
    final=Jobs(paths).get(job['id'])
    if final['state'] in {'succeeded','partial','failed'}:break
    time.sleep(.05)
assert final['state']=='succeeded' and final['counts']=={'products':1,'assets':2}
with httpx.Client(trust_env=False) as http:
    response=http.get(f"http://127.0.0.1:{config['port']}"+final['download_url'],headers=headers)
assert response.status_code==200 and hashlib.sha256(response.content).hexdigest()==final['sha256']
export_file=output/'synthetic-favorites.zip';export_file.write_bytes(response.content)
with zipfile.ZipFile(export_file) as archive:
    assert len([n for n in archive.namelist() if n.endswith('.png')])==2
evidence['export']=final
backup=cli('backup',{'new_intent':True,'destination_id':'local'})['result']['maintenance']
end=time.monotonic()+20
while time.monotonic()<end:
    finished=Maintenance(paths).get(backup['id'])
    if finished['state'] in {'succeeded','partial','failed'}:break
    time.sleep(.05)
assert finished['state']=='succeeded' and finished['result']['counts']['assets']==2
verify_bundle(Path(finished['result']['path']),finished['result']['manifest_sha256'])
evidence['backup']=finished
root_length=len(str(package))
identifier='f'*32;digest='a'*64
budget={
 'default_original': '/data/media/originals/aa/'+digest+'.webp',
 'archive_temp_int64_epoch': '/data/media/temp/'+identifier+'/'+str(2**63-1)+'/'+identifier+'.part',
 'export_final_int64_attempt': '/data/exports/'+identifier+'/attempt-'+str(2**63-1)+'/export-'+digest+'.zip',
 'backup_staged_asset': '/data/maintenance/'+identifier+'/stage-'+('f'*12)+'/assets/'+digest+'.bin',
 'backup_final_asset': '/data/backups/'+identifier+'/assets/'+digest+'.bin',
}
path_budget={name:{'suffix':suffix,'suffix_characters':len(suffix),'at_root_100':100+len(suffix)} for name,suffix in budget.items()}
assert all(row['at_root_100']<=250 for row in path_budget.values())
actual=max((str(p) for p in (package/'.local').rglob('*') if p.is_file()),key=len)
assert len(actual)<=250
evidence['path_budget']={'package_root_characters':root_length,'derived':path_budget,
                         'actual_installed_longest':actual,'actual_installed_characters':len(actual),
                         'actual_backup_member_max':max(len(str(p)) for p in Path(finished['result']['path']).rglob('*') if p.is_file()),
                         'scope':'Fresh default internal data/media/backup paths; external roots and restore targets need separate checks'}
with db.read() as connection:
    evidence['final_counts']={'runs':connection.execute('SELECT COUNT(*) FROM runs').fetchone()[0],
                              'source_requests':connection.execute('SELECT COUNT(*) FROM collection_http').fetchone()[0],
                              'run_intents':connection.execute('SELECT COUNT(*) FROM run_requests').fetchone()[0]}
assert evidence['final_counts']=={'runs':1,'source_requests':0,'run_intents':0}
evidence['module']=launcher.__file__
(output/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
