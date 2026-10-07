"""Bounded immutable JSON inventory captured only from a caller's DB snapshot."""
import json
from fashion_scout.domain import ScoutError


def capture(conn,scope='all',product_ids=(),all_assets=False):
    products=[r['id'] for r in conn.execute('SELECT id FROM products ORDER BY id')]
    if scope=='selected':
        if not product_ids or len(set(product_ids))!=len(product_ids):raise ScoutError('INVALID_SELECTION','请选择非重复的商品',422)
        if not set(product_ids)<=set(products):raise ScoutError('PRODUCT_NOT_FOUND','部分商品不存在',404)
        products=sorted(product_ids)
    if len(products)>1000:raise ScoutError('MAINTENANCE_LIMIT','单次最多核验1000款',422)
    versions,relations,issues=[],[],[];wanted=set(products);asset_ids=set();with_version=set()
    for row in conn.execute('SELECT * FROM product_versions ORDER BY id,revision'):
        if row['product_id'] not in wanted:continue
        version=dict(row);versions.append(version);with_version.add(row['product_id'])
        refs=[dict(r) for r in conn.execute('SELECT * FROM version_images WHERE version_id=? AND revision=? ORDER BY ordinal,source_image_id',(row['id'],row['revision']))]
        relations.extend(refs)
        key=f"version:{row['id']}:{row['revision']}"
        try:
            manifest=json.loads(row['manifest_json'])
            if not manifest.get('enumeration_complete') or manifest.get('expected_count')!=len(refs):
                issues.append({'object_id':key,'code':'ENUMERATION_UNKNOWN','category':'unknown'})
        except (TypeError,ValueError,AttributeError):issues.append({'object_id':key,'code':'MANIFEST_INVALID','category':'unknown'})
        for ref in refs:
            if ref['asset_id']:asset_ids.add(ref['asset_id'])
            else:issues.append({'object_id':key+':'+ref['source_image_id'],'code':'IMAGE_NOT_ARCHIVED','category':'missing'})
    for pid in wanted-with_version:issues.append({'object_id':'product:'+pid,'code':'IMAGE_SCOPE_UNKNOWN','category':'unknown'})
    assets=[dict(r) for r in conn.execute('SELECT * FROM assets ORDER BY id') if all_assets or r['id'] in asset_ids]
    for aid in asset_ids-{a['id'] for a in assets}:issues.append({'object_id':'asset:'+aid,'code':'ASSET_RECORD_MISSING','category':'missing'})
    if len(assets)>10000 or len(relations)>100000:raise ScoutError('MAINTENANCE_LIMIT','素材或关系数量超过单次上限',422)
    roots={r['id']:r['path'] for r in conn.execute('SELECT * FROM storage_roots ORDER BY id')}
    value={'schema':1,'products':products,'versions':versions,'relations':relations,'assets':assets,'roots':roots,'issues':issues}
    if len(json.dumps(value,ensure_ascii=False).encode())>64*1024**2:raise ScoutError('MAINTENANCE_LIMIT','核验元数据超过限制',422)
    return value
