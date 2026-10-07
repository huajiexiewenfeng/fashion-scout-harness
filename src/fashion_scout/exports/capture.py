"""Capture through the caller's short SQLite transaction; never hash/open assets."""
import json
from fashion_scout.domain import ScoutError
from .models import capture_snapshot, canonical


def capture_favorites(conn, export_id, now):
    rows=conn.execute('SELECT p.*,u.revision AS user_revision,u.category_override FROM products p JOIN product_user_state u ON u.product_id=p.id WHERE u.favorite=1 ORDER BY p.id').fetchall()
    if not rows:raise ScoutError('EMPTY_FAVORITES','还没有收藏款式，请先收藏再导出',422)
    products,assets,roots=[],{},{}
    scoped=False
    for row in rows:
        versions=[]
        for version in conn.execute('SELECT * FROM product_versions WHERE product_id=? ORDER BY id,revision',(row['id'],)):
            manifest=json.loads(version['manifest_json'])
            images=[]
            original={x['source_image_id']:x for x in manifest.get('images',[])}
            for ref in conn.execute('SELECT * FROM version_images WHERE version_id=? AND revision=? ORDER BY ordinal,source_image_id',(version['id'],version['revision'])):
                prior=original.get(ref['source_image_id'],{})
                images.append({'source_image_id':ref['source_image_id'],'source_url':ref['source_url'],'ordinal':ref['ordinal'],
                    'asset_id':ref['asset_id'],'missing_reason':prior.get('error_code'),'variant_ids':prior.get('variant_ids',[])})
                if ref['asset_id'] and ref['asset_id'] not in assets:
                    a=conn.execute('SELECT a.*,s.path FROM assets a JOIN storage_roots s ON s.id=a.root_id WHERE a.id=?',(ref['asset_id'],)).fetchone()
                    if a is None:raise ScoutError('EXPORT_SNAPSHOT_INVALID','归档资产关系不完整，未创建导出',409)
                    assets[a['id']]={'asset_id':a['id'],'root_id':a['root_id'],'relative_path':a['relative_path'],
                        'sha256':a['sha256'],'bytes':a['bytes'],'format':a['format'] if a['state']=='verified' and a['format'] in {'PNG','JPEG','WEBP','GIF'} else 'UNKNOWN'}
                    roots[a['root_id']]=a['path']
            complete=bool(manifest.get('enumeration_complete',False))
            scope=manifest.get('promised_scopes',['product.images'])
            if scope not in (['product.images'],['browser.gallery']):
                raise ScoutError('EXPORT_SNAPSHOT_INVALID','版本采集范围不明确，未创建导出',409)
            scoped=scoped or scope==['browser.gallery']
            versions.append({'version_id':version['id'],'revision':version['revision'],'images':images,
                'coverage_scope':scope[0],
                'enumeration_complete':complete,'expected_count':manifest.get('expected_count') if complete else None,
                'enumeration_reason':None if complete else '快照时来源图集枚举尚未完成'})
        obs=conn.execute('SELECT fields_json,date_evidence_json FROM observations WHERE id=?',(row['latest_observation_id'],)).fetchone()
        if obs:source=json.loads(obs['fields_json']);dates=json.loads(obs['date_evidence_json'])
        else:
            source_row=conn.execute('SELECT c.listing_json,c.detail_json FROM collection_products c JOIN runs r ON r.id=c.run_id WHERE c.product_id=? ORDER BY r.created_at DESC,r.id DESC LIMIT 1',(row['id'],)).fetchone()
            source=json.loads(source_row['detail_json'] or source_row['listing_json']) if source_row else {}
            dates={'reason':source.get('date_reason','unknown'),'source_published_at':source.get('source_published_at')}
        dates.update(first_seen_at=row['first_seen_at'],first_eligible_at=row['first_eligible_at'])
        source['local_selection']={'favorite':True,'user_revision':row['user_revision'],'category_override':row['category_override']}
        notes=[]
        current=next((v for v in versions if (v['version_id'],v['revision'])==(row['latest_observed_version_id'],row['latest_observed_revision'])),None)
        for note in source.get('capability_notes',[]):
            if note.get('scope') and (note['scope']!='product.images' or (current and current['coverage_scope']=='browser.gallery')):
                notes.append({'scope':note['scope'],'status':note.get('status') if note.get('status') in {'unknown','unsupported','supported'} else 'unknown','reason':note.get('reason') or note.get('detail') or '来源支持范围说明'})
        def pointer(kind):
            vid=row[f'latest_{kind}_version_id'];revision=row[f'latest_{kind}_revision']
            return {'version_id':vid,'revision':revision} if vid and revision else None
        products.append({'product_id':row['id'],'source_json':canonical(source),'date_basis_json':canonical(dates),
            'latest_available':pointer('available'),'latest_observed':pointer('observed'),'versions':versions,'capability_notes':notes})
    try:
        value={'export_id':export_id,'captured_at':now,'products':products,'assets':list(assets.values())}
        if scoped:
            value.update(schema_version=2,promised_scope='per_version')
        else:
            for p in products:
                for v in p['versions']:v.pop('coverage_scope')
        return capture_snapshot(value),roots
    except (ValueError,TypeError):raise ScoutError('EXPORT_SNAPSHOT_INVALID','冻结数据不符合导出契约，未创建导出',409) from None
