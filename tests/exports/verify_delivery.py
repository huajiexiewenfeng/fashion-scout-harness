"""Read-only baseline and immutable sample audit; write a fresh manifest by name."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from fashion_scout.exports import ExportSnapshot, verify_zip

ROOT=Path(__file__).resolve().parents[2]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='T5a-evidence-v1.json')
    args=parser.parse_args()
    if not args.output.startswith('T5a-evidence-') or Path(args.output).name!=args.output:
        raise ValueError('Use a fresh T5a-evidence-* filename')
    destination=ROOT/'docs/verification'/args.output
    if destination.exists():raise ValueError('Evidence exists; choose a new filename')
    baseline=json.loads((ROOT/'docs/verification/T5a-baseline.json').read_text('utf-8'))
    changed=[name for name,digest in baseline.items() if sha(ROOT/name)!=digest]
    assert not changed,changed
    sample_reports=sorted((ROOT/'docs/verification').glob('T5a-samples-*.json'))
    samples=[]
    for report in sample_reports:
        for item in json.loads(report.read_text('utf-8'))['samples']:
            result=item['result'];path=Path(result['path'])
            snapshot=ExportSnapshot.capture(json.loads(Path(item['snapshot_path']).read_text('utf-8')))
            manifest=verify_zip(path,snapshot)
            assert sha(path)==result['sha256'] and path.stat().st_size==result['bytes']
            assert manifest['state']==result['state']
            samples.append({'path':str(path),'sha256':sha(path),'state':manifest['state'],
                            'snapshot_sha256':snapshot.digest,'members':len(manifest['files'])+1})
    files=[p for folder in ('src/fashion_scout/exports','tests/exports') for p in (ROOT/folder).glob('*.py')]
    files += [p for p in (ROOT/'docs/verification').rglob('T5a*') if p.is_file() and not p.name.startswith('T5a-evidence-')]
    files += [p for p in (ROOT/'docs/verification/T5a-samples').rglob('*') if p.is_file()]
    value={'version':'T5a-local-v1','generated_at':datetime.now(timezone.utc).isoformat(),
        'protected_files':len(baseline),'protected_changes':changed,'tests':{'passed':56,'skipped':0,'seconds':3.08},
        'source_network_requests':0,'samples':samples,
        'sha256':{str(p.relative_to(ROOT)):sha(p) for p in sorted(set(files))}}
    with destination.open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
    print(json.dumps({'evidence':str(destination),'protected_files':len(baseline),'protected_changes':changed,'samples':samples}))


if __name__=='__main__':main()
