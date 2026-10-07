import hashlib
import json
from pathlib import Path
import zipfile
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/verification'
KIT=ROOT/'.runtime/t6c-inputs-1bc09368'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    baseline=json.loads((DOC/'T6d-R1-baseline.json').read_text('utf-8'))
    current={name:sha(ROOT/name) for name in baseline}
    changed={name for name in baseline if baseline[name]!=current[name]}
    assert changed=={'tests\\release\\test_input_refresh.py','scripts\\release\\templates\\README.zh-CN.md','scripts\\release\\templates\\PACKAGE-CONTEXT.zh-CN.md'}
    one=json.loads((ROOT/'.runtime/t6c-final-browser-v1/build-receipt.json').read_text('utf-8'))
    two=json.loads((ROOT/'.runtime/t6c-final-browser-v2/build-receipt.json').read_text('utf-8'))
    for receipt in (one,two):
        assert sha(Path(receipt['zip']))==receipt['zip_sha256'] and sha(Path(receipt['manifest']))==receipt['manifest_sha256']
        assert sha(Path(receipt['app_wheel']))==receipt['app_sha256']=='5938b20f707c73ebc0042d115abdd7e04d3bf62dd9799362be595afa52393753'
    first=json.loads(Path(one['manifest']).read_text('utf-8'));second=json.loads(Path(two['manifest']).read_text('utf-8'))
    top={name for name in first if first[name]!=second[name]};assert top=={'candidate','files'}
    a={m['path']:m for m in first['files']};b={m['path']:m for m in second['files']};assert set(a)==set(b)
    differs={name for name in a if a[name]!=b[name]};assert differs=={'README.zh-CN.md','PACKAGE-CONTEXT.zh-CN.md'}
    with zipfile.ZipFile(one['zip']) as old,zipfile.ZipFile(two['zip']) as new:
        assert old.testzip() is None and new.testzip() is None and set(old.namelist())==set(new.namelist())
        different_bytes={name for name in old.namelist() if old.read(name)!=new.read(name)}
        assert different_bytes=={'FashionScout/README.zh-CN.md','FashionScout/PACKAGE-CONTEXT.zh-CN.md','FashionScout/manifest.json'}
        for name,entry in b.items():
            data=new.read('FashionScout/'+name);assert len(data)==entry['bytes'] and hashlib.sha256(data).hexdigest()==entry['sha256']
    assert first['source_files']==second['source_files'] and len(second['source_files'])==72
    assert first['skill_files']==second['skill_files'] and len(second['skill_files'])==4
    for name,digest in second['skill_files'].items():assert sha(ROOT/name)==digest
    records=[{'path':str(path),'sha256':sha(path),'record':json.loads(path.read_text('utf-8'))} for path in sorted((KIT/'logs').glob('*.json'))]
    copies={'T6d-R1-manifest-v2.json':Path(two['manifest'])}
    for name,path in copies.items():
        target=DOC/name;assert not target.exists();target.write_bytes(path.read_bytes())
    artifacts=[*DOC.glob('T6d-R1*'),ROOT/'tests/release/test_input_refresh.py',ROOT/'scripts/release/templates/README.zh-CN.md',
               ROOT/'scripts/release/templates/PACKAGE-CONTEXT.zh-CN.md',ROOT/'README.md',ROOT/'docs/delivery.zh-CN.md']
    report={'at':datetime.now(timezone.utc).isoformat(),'scope':'T6d R1 fixture inputs plus documentation-only v2',
            'baseline_count':len(baseline),'allowed_changed':sorted(changed),'unchanged_count':len(baseline)-len(changed),
            'baseline_sha256':baseline,'current_sha256':current,'v1_receipt':one,'v2_receipt':two,
            'manifest_top_differences':sorted(top),'manifest_file_differences':sorted(differs),'zip_byte_differences':sorted(different_bytes),
            'unchanged_manifest_files':len(a)-len(differs),'source_members_unchanged':72,'skill_files_unchanged':4,
            'command_records':records,'tests':'27 passed in26.51s; -W error; T6d-R1-tests.txt',
            'artifact_sha256':{str(p.relative_to(ROOT)):sha(p) for p in artifacts if p.is_file() and p.name!='T6d-R1-evidence-v1.json'},
            'application_install_repeated':False,'source_requests':0}
    target=DOC/'T6d-R1-evidence-v1.json';assert not target.exists();target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'baseline':len(baseline),'allowed_changed':sorted(changed),'unchanged':len(baseline)-len(changed),
                      'unchanged_manifest_files':len(a)-len(differs),'zip_differences':sorted(different_bytes),'final_sha256':two['zip_sha256'],'bytes':two['bytes']}))


if __name__=='__main__':main()
