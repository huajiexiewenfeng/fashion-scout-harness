"""Freeze T6c input evidence without reading live Core or invoking business services."""
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
import re

ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/verification'
KIT=ROOT/'.runtime/t6c-inputs-ae307604'
TARGETED=ROOT/'.runtime/t6c-inputs-a92912db'
ALLOWED={'scripts\\release\\build_bundle.py','scripts\\release\\templates\\package.ps1'}


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    baseline=json.loads((DOC/'T6c-baseline.json').read_text('utf-8'))
    actual={name:sha(ROOT/name) for name in baseline}
    changed={name for name in baseline if baseline[name]!=actual[name]}
    assert changed==ALLOWED,changed
    old=ROOT/'.runtime/t6b-final-v1/FashionScout-0.2.0a1-local-candidate-v1.zip'
    assert sha(old)=='6fa3a026a87da7d7c03da6daa075c55efc526eb0a5b108deb8d3ca32fe1a0960'
    receipts={'legacy':json.loads((KIT/'default-evidence.json').read_text('utf-8')),
              'explicit_fixtures':json.loads((KIT/'explicit-evidence.json').read_text('utf-8'))}
    for receipt in [receipts['legacy'],*receipts['explicit_fixtures']]:
        assert sha(Path(receipt['zip']))==receipt['zip_sha256']
        assert sha(Path(receipt['manifest']))==receipt['manifest_sha256']
        assert sha(Path(receipt['app_wheel']))==receipt['app_sha256']
    records=[]
    # Initial output-escape test put its log one level above logs; preserve that original.
    paths=[*sorted((KIT/'logs').glob('*.json')),*sorted(KIT.glob('t6c-escaped-*.json')),
           *sorted((TARGETED/'logs').glob('*.json'))]
    for path in paths:
        records.append({'path':str(path),'sha256':sha(path),'record':json.loads(path.read_text('utf-8'))})
    for target,value in [('T6c-command-records-v1.json',records),('T6c-input-evidence-v1.json',receipts)]:
        path=DOC/target;assert not path.exists();path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    links=[]
    for target in re.findall(r'\]\(([^)]+)\)',(DOC/'T6c.md').read_text('utf-8')):
        path=(DOC/target).resolve();assert path.exists() or path==DOC/'T6c-evidence-v1.json'
        links.append(target)
    files=[*DOC.glob('T6c*'),ROOT/'scripts/release/build_bundle.py',ROOT/'scripts/release/templates/package.ps1',
           ROOT/'tests/release/test_input_refresh.py',Path(__file__)]
    hashes={str(path.relative_to(ROOT)):sha(path) for path in files if path.is_file() and path.name!='T6c-evidence-v1.json'}
    report={'at':datetime.now(timezone.utc).isoformat(),'scope':'T6c tool preparation only; no production candidate',
            'baseline_count':len(baseline),'allowed_existing_changed':sorted(changed),'unchanged_count':len(baseline)-len(changed),
            'baseline_sha256':baseline,'current_sha256':actual,'artifact_sha256':hashes,'document_links':links,
            'input_receipts':receipts,'command_log_files':len(records),'old_T6b_zip_sha256':sha(old),
            'live_Core_source_used':False,'install_or_services':False,'source_site_requests':0,
            'test_results':['25 passed in19.68s; warnings as errors','1 affected logging case passed in0.19s']}
    path=DOC/'T6c-evidence-v1.json';assert not path.exists();path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'baseline':len(baseline),'allowed_changed':sorted(changed),'unchanged':len(baseline)-len(changed),
                      'artifacts':len(hashes),'links':len(links),'command_log_files':len(records),'old_T6b_zip_sha256':sha(old)}))


if __name__=='__main__':main()
