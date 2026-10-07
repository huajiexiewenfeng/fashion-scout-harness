"""Generate new uniquely named synthetic evidence; never overwrite a prior report."""
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid
from fashion_scout.exports import ExportSnapshot, export_zip, verify_zip
from .fixtures import sample

ROOT=Path(__file__).resolve().parents[2]


def main():
    tag=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    work=ROOT/'.runtime'/('t5a-samples-'+tag)
    output=ROOT/'docs/verification/T5a-samples'/tag
    root=work/'media'
    value=sample(root)
    complete=ExportSnapshot.capture(value)
    first=export_zip(complete,{'media':root},output/'complete')
    assert first.state=='succeeded'
    value['export_id']='synthetic-partial-'+tag
    current=value['products'][0]['versions'][1]
    current['images'].append({'source_image_id':'new-missing','source_url':'https://example.invalid/missing.png',
                             'ordinal':3,'asset_id':None,'missing_reason':'HTTP_404'})
    current['expected_count']=4
    value['products'].append({'product_id':'no-images-收藏款','source_json':'{"title":"合成无图收藏款"}',
        'date_basis_json':'{"reason":"source_date_unknown"}','latest_available':None,'latest_observed':None,'versions':[]})
    partial=ExportSnapshot.capture(value)
    # Explicit fixture corruption, never source/archive data from the user's root.
    (root/'b.png').write_bytes(b'synthetic damaged asset')
    second=export_zip(partial,{'media':root},output/'partial')
    assert second.state=='partial' and second.missing_count==2 and second.unknown_count==1
    results=[]
    for label,snapshot,result in [('complete',complete,first),('partial',partial,second)]:
        manifest=verify_zip(Path(result.path),snapshot)
        snapshot_path=output/(label+'-snapshot.json')
        snapshot_path.write_text(snapshot.model_dump_json(indent=2),encoding='utf-8')
        results.append({'label':label,'result':result.model_dump(),'snapshot_path':str(snapshot_path),
                        'member_count':len(manifest['files'])+1,'image_file_count':sum(bool(x['asset_ids']) for x in manifest['files'])})
    evidence={'version':'T5a-local-v1','generated_at':datetime.now(timezone.utc).isoformat(),
              'synthetic':True,'source_network_requests':0,'work_root':str(work),'samples':results}
    path=ROOT/'docs/verification'/('T5a-samples-'+tag+'.json')
    path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'evidence':str(path),'samples':results},ensure_ascii=True))


if __name__=='__main__':main()
