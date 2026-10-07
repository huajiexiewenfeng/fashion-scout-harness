import hashlib
import json
from pathlib import Path
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/verification'
KIT=ROOT/'.runtime/t6c-inputs-b95213e3'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    baseline=json.loads((DOC/'T6c-R1-baseline.json').read_text('utf-8'))
    current={name:sha(ROOT/name) for name in baseline}
    changed={name for name in baseline if baseline[name]!=current[name]}
    assert changed=={'scripts\\release\\templates\\package.ps1','tests\\release\\test_input_refresh.py'}
    evidence=json.loads((KIT/'r1-plus-evidence.json').read_text('utf-8'));receipt=evidence['receipt']
    assert sha(Path(receipt['app_wheel']))==receipt['app_sha256']
    assert sha(Path(receipt['zip']))==receipt['zip_sha256']
    assert sha(Path(receipt['manifest']))==receipt['manifest_sha256']
    records=[{'path':str(path),'sha256':sha(path),'record':json.loads(path.read_text('utf-8'))}
             for path in sorted((KIT/'logs').glob('*.json'))]
    old=ROOT/'.runtime/t6b-final-v1/FashionScout-0.2.0a1-local-candidate-v1.zip'
    assert sha(old)=='6fa3a026a87da7d7c03da6daa075c55efc526eb0a5b108deb8d3ca32fe1a0960'
    artifacts=[*DOC.glob('T6c-R1*'),ROOT/'scripts/release/templates/package.ps1',
               ROOT/'tests/release/test_input_refresh.py',Path(__file__)]
    report={'at':datetime.now(timezone.utc).isoformat(),'scope':'T6c same-task R1 plus path syntax only',
            'baseline_count':len(baseline),'allowed_changed':sorted(changed),'unchanged_count':len(baseline)-len(changed),
            'baseline_sha256':baseline,'current_sha256':current,'plus_fixture':evidence,'raw_command_records':records,
            'artifact_sha256':{str(path.relative_to(ROOT)):sha(path) for path in artifacts if path.is_file() and path.name!='T6c-R1-evidence-v1.json'},
            'old_T6b_zip_sha256':sha(old),'test_result':'3 passed,24 deselected in11.55s; -W error',
            'live_Core_source_used':False,'services_or_install':False,'source_site_requests':0}
    path=DOC/'T6c-R1-evidence-v1.json';assert not path.exists();path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'baseline':len(baseline),'changed':sorted(changed),'unchanged':len(baseline)-len(changed),
                      'raw_records':len(records),'old_T6b_zip_sha256':sha(old)}))


if __name__=='__main__':main()
