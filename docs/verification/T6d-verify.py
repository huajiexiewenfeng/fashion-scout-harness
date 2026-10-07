"""Freeze only this delivery's artifacts and explicitly permitted file changes."""
import hashlib
import json
from pathlib import Path
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/verification'
FINAL=ROOT/'.runtime/t6c-final-browser-v1'
WORK=ROOT/'.runtime/t6c-d-smoke-18206465'
STAGE=ROOT/'.runtime/t2-browser-live-20261007-01'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    baseline=json.loads((DOC/'T6d-baseline.json').read_text('utf-8'))
    current={name:sha(ROOT/name) for name in baseline}
    changed={name for name in baseline if baseline[name]!=current[name]}
    assert changed=={'scripts\\release\\build_bundle.py','scripts\\release\\templates\\README.zh-CN.md','docs\\delivery.zh-CN.md'}
    receipt=json.loads((FINAL/'build-receipt.json').read_text('utf-8'))
    assert sha(Path(receipt['zip']))==receipt['zip_sha256'] and sha(Path(receipt['manifest']))==receipt['manifest_sha256']
    provenance=json.loads((STAGE/'build-provenance.json').read_text('utf-8'))
    assert sha(Path(provenance['wheel']))==receipt['app_sha256']==provenance['wheel_sha256']
    for relative,digest in provenance['source_sha256'].items():assert sha(STAGE/'source'/relative)==digest
    copies={'T6d-smoke-evidence-v1.json':WORK/'smoke-evidence.json','T6d-manifest-v1.json':Path(receipt['manifest'])}
    for name,source in copies.items():
        target=DOC/name;assert not target.exists();target.write_bytes(source.read_bytes())
    inputs={'stage_provenance':provenance,'stage_provenance_sha256':sha(STAGE/'build-provenance.json'),'delivery':receipt}
    target=DOC/'T6d-input-evidence-v1.json';assert not target.exists();target.write_text(json.dumps(inputs,ensure_ascii=False,indent=2),encoding='utf-8')
    old=ROOT/'.runtime/t6b-final-v1/FashionScout-0.2.0a1-local-candidate-v1.zip'
    assert sha(old)=='6fa3a026a87da7d7c03da6daa075c55efc526eb0a5b108deb8d3ca32fe1a0960'
    files=[ROOT/'README.md',ROOT/'docs/delivery.zh-CN.md',ROOT/'scripts/release/build_bundle.py',
           ROOT/'scripts/release/templates/README.zh-CN.md',ROOT/'scripts/release/templates/PACKAGE-CONTEXT.zh-CN.md',*DOC.glob('T6d*')]
    artifacts={str(path.relative_to(ROOT)):sha(path) for path in files if path.is_file() and path.name!='T6d-evidence-v1.json'}
    http=json.loads((DOC/'T6d-http-evidence-v1.json').read_text('utf-8'));assert not any(http['final']['live'].values()) and not any(http['final']['counts'].values())
    report={'at':datetime.now(timezone.utc).isoformat(),'scope':'T6d final local candidate; independent review pending',
            'baseline_count':len(baseline),'allowed_existing_changed':sorted(changed),'unchanged_count':len(baseline)-len(changed),
            'baseline_sha256':baseline,'current_sha256':current,'artifact_sha256':artifacts,'delivery':receipt,
            'skill_source_sha256':receipt['skill_files'],'old_T6b_zip_sha256':sha(old),'final_smoke':http['final'],
            'new_source_requests':0,'user_55016_or_56117_accessed':False,'global_install':False}
    target=DOC/'T6d-evidence-v1.json';assert not target.exists();target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'baseline':len(baseline),'allowed_changed':sorted(changed),'unchanged':len(baseline)-len(changed),
                      'artifacts':len(artifacts),'zip_sha256':receipt['zip_sha256'],'bytes':receipt['bytes'],'final':http['final']}))


if __name__=='__main__':main()
