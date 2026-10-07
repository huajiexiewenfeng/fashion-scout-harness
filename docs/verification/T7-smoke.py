"""Exercise the installed Skill against only the new stable daily package; no source Run."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess

ROOT=Path(__file__).resolve().parents[2]
SKILL=Path(r'C:\Users\Administrator\.codex\skills\fashion-scout')
APP=Path(r'E:\github-workspace\FashionScout')
PS=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
records=[]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def run(action,*args,expected=0):
    command=[str(PS),'-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',str(SKILL/'scripts/entry.ps1'),'-Action',action,*args]
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=150)
    record={'action':action,'argv':command,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
    records.append(record);print(json.dumps(record,ensure_ascii=True),flush=True)
    assert result.returncode==expected,record
    return result


def main():
    assert not (APP/'.local').exists() and not (APP/'data').exists()
    pre=run('Status');assert json.loads(pre.stdout)['prepared'] is False
    assert not (APP/'.local').exists() and not (APP/'data').exists()
    try:
        run('Open')
        first=json.loads((APP/'data/control/runtime.json').read_text('utf-8'))
        inventory=APP/'.local/installed-files.json';before=sha(inventory)
        second=run('Open')
        current=json.loads((APP/'data/control/runtime.json').read_text('utf-8'))
        assert first['instance']==current['instance'] and first['processes']==current['processes'] and sha(inventory)==before
        assert 'Successfully installed' not in second.stdout
        run('Status')
        planned=json.loads(run('Intent','-Intent','Start').stdout)
        assert planned['command']=='start' and planned['payload']=={'new_intent':True,'overrides':{'source_mode':'browser'}}
        continued=json.loads(run('Intent','-Intent','Continue').stdout)
        assert continued['command']=='latest' and continued['read_only'] is True
        requests=APP/'data/requests';requests.mkdir()
        bad=requests/'http-intent.json';bad.write_text('{"new_intent":true,"overrides":{"source_mode":"http"}}',encoding='utf-8')
        refused=run('Intent','-Intent','Start','-InputJson',str(bad),expected=3)
        assert json.loads(refused.stdout)['error']=='SKILL_REQUIRES_BROWSER_SOURCE'
        empty=requests/'empty.json';empty.write_text('{}',encoding='utf-8')
        run('Request','-Command','latest','-InputJson',str(empty))
        run('Request','-Command','new','-InputJson',str(empty))
        # Only explicit, individually selected helper failure cases; no root scan.
        missing=ROOT/'.runtime/t6c-t7-missing-binding.json'
        result=run('Locate','-BindingPath',str(missing),expected=3)
        assert 'BINDING_REQUIRED' in json.loads(result.stdout)['error'] and not missing.exists()
        wrong=ROOT/'.runtime/t6c-t7-wrong-binding.json'
        binding=json.loads((SKILL/'local-binding.json').read_text('utf-8'));binding['package_root']=str(ROOT/'.runtime/t6c-t7-no-app')
        wrong.write_text(json.dumps(binding),encoding='utf-8')
        result=run('Locate','-BindingPath',str(wrong),expected=3)
        assert 'PACKAGE_MISSING' in json.loads(result.stdout)['error']
    finally:
        run('Stop')
    stopped=json.loads((APP/'data/control/runtime.json').read_text('utf-8'));assert stopped['stopped'] is True
    run('Status')
    after=json.loads((APP/'data/control/runtime.json').read_text('utf-8'));assert after['instance']==stopped['instance'] and after['stopped'] is True
    check=[str(APP/'.local/env/Scripts/python.exe'),'-I','-B','-c',
           'import json,sys;from fashion_scout.config import Paths;from fashion_scout import launcher;p=Paths.at(sys.argv[1]);d=launcher.read_descriptor(p);live={r:bool(launcher.verified_process(p,d,r)) for r in ("web","worker")};assert not any(live.values());print(json.dumps(live))',str(APP/'data')]
    result=subprocess.run(check,cwd=APP,capture_output=True,text=True,encoding='utf-8',timeout=15);assert result.returncode==0
    connection=sqlite3.connect((APP/'data/scout.sqlite3').as_uri()+'?mode=ro',uri=True)
    counts={table:connection.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('runs','run_requests','collection_http','products')}
    assert not any(counts.values());connection.close()
    report={'records':records,'stable_app':str(APP),'personal_skill':str(SKILL),'binding':json.loads((SKILL/'local-binding.json').read_text('utf-8')),
            'reused_instance':first['instance'],'installation_inventory_sha256':before,'empty_counts':counts,
            'verified_exit':json.loads(result.stdout),'intent_route':planned,'continue_route':continued,
            'source_requests':0,'actual_OS_browser_open_used':True,'host_skill_discovery_refreshed':'not independently verified'}
    (ROOT/'docs/verification/T7-smoke-evidence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':True,'counts':counts,'exited':json.loads(result.stdout),'second_open_reused':True},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
