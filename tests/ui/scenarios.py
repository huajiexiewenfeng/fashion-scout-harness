"""Fault injection and evidence for the explicitly isolated T3 browser QA root."""
import argparse
import json
from pathlib import Path
from fashion_scout.config import Paths
from fashion_scout.db import Database
from fashion_scout.launcher import read_descriptor, verified_process


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['record','corrupt','offline','history'])
    parser.add_argument('--label',default='checkpoint')
    parser.add_argument('--rework',action='store_true')
    args=parser.parse_args()
    repo=Path(__file__).resolve().parents[2]
    paths=Paths.at(repo/'.runtime'/'t3-browser')
    db=Database(paths.db)
    if args.action=='history':
        from fashion_scout.services.runs import digest, canonical
        with db.write() as conn:
            manifest=json.loads(conn.execute("SELECT manifest_json FROM product_versions WHERE id='fixture-version-0' AND revision=1").fetchone()[0])
            manifest['images']=manifest['images'][:1]
            manifest['expected_count']=1
            content=digest({'sha256':sorted({r['sha256'] for r in manifest['images']})})
            conn.execute("INSERT INTO product_versions VALUES ('fixture-version-0',2,'fixture-000',?,?,?)",(digest(manifest),canonical(manifest),content))
            image=manifest['images'][0]
            conn.execute("INSERT INTO version_images VALUES ('fixture-version-0',2,?,?,?,?)",(image['source_image_id'],image['url'],image['ordinal'],image['asset_id']))
            conn.execute("UPDATE products SET latest_observed_revision=2,latest_available_revision=2,latest_complete_revision=2 WHERE id='fixture-000'")
    if args.action=='corrupt':
        for n in range(2):(paths.media/f'fixture-asset-2-{n}.png').write_bytes(b'Invalid image: isolated browser fault fixture')
        with db.write() as conn:
            source=json.loads(conn.execute("SELECT listing_json FROM collection_products WHERE product_id='fixture-002'").fetchone()[0])
            source['title']='<img src=x onerror=alert(1)> 来源文字测试'
            conn.execute("UPDATE collection_products SET listing_json=? WHERE product_id='fixture-002'",(json.dumps(source),))
    if args.action=='offline':
        with db.read() as conn:
            if conn.execute("SELECT 1 FROM runs WHERE state IN ('queued','running','interrupted','cancelling')").fetchone():
                raise RuntimeError('Never stop a Worker with active work in this QA action')
        descriptor=read_descriptor(paths)
        proc=verified_process(paths,descriptor,'worker')
        if proc:
            proc.terminate();proc.wait(timeout=5)
        if verified_process(paths,descriptor,'worker') is not None:raise RuntimeError('Worker still running')
        with db.write() as conn:conn.execute("UPDATE workers SET state='offline'")
    with db.read() as conn:
        snapshot={'label':args.label,
            'runs':[dict(r) for r in conn.execute('SELECT id,state,created_at FROM runs ORDER BY created_at,id')],
            'favorites':[r[0] for r in conn.execute('SELECT product_id FROM product_user_state WHERE favorite=1 ORDER BY product_id')],
            'view_events':[dict(r) for r in conn.execute('SELECT product_id,version_id,version_revision,viewed_at FROM view_events ORDER BY viewed_at')],
            'user_states':[dict(r) for r in conn.execute('SELECT product_id,category_override,revision,seen_version_revision,seen_content_digest FROM product_user_state ORDER BY product_id')],
            'source_http_count':conn.execute('SELECT COUNT(*) FROM collection_http').fetchone()[0],
            'run_request_count':conn.execute('SELECT COUNT(*) FROM run_requests').fetchone()[0]}
    destination=repo/'docs'/'verification'/('T3-R1-browser-evidence.json' if args.rework else 'T3-browser-evidence.json')
    existing=json.loads(destination.read_text('utf-8')) if destination.exists() else []
    existing.append(snapshot);destination.write_text(json.dumps(existing,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(snapshot,ensure_ascii=False))


if __name__=='__main__':main()
