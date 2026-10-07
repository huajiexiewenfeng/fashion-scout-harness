"""Deterministic package projection and safe CSV; no file-system reads."""
import csv
import hashlib
import io
import json
from .models import canonical

FAILURES = {'ASSET_MISSING', 'ASSET_UNREADABLE', 'INVALID_PATH', 'ROOT_UNAVAILABLE',
            'SOURCE_CHANGED', 'HASH_MISMATCH', 'SIZE_MISMATCH', 'IMAGE_INVALID',
            'IMAGE_FORMAT_MISMATCH', 'ASSET_LIMIT', 'IMAGE_PIXEL_LIMIT'}
EXT = {'PNG': 'png', 'JPEG': 'jpg', 'WEBP': 'webp', 'GIF': 'gif'}


def json_bytes(value):
    return (canonical(value) + '\n').encode('utf-8')


def key(version):
    return (version.version_id, version.revision) if version else None


def file_record(path, data, product_id=None, **extra):
    return {'path': path, 'product_id': product_id, 'asset_ids': [], 'version_ids': [],
            'source_urls': [], 'relations': [], 'sha256': hashlib.sha256(data).hexdigest(),
            'bytes': len(data), **extra}


def csv_bytes(records):
    fields = ['path', 'product_id', 'asset_ids', 'sha256', 'bytes', 'version_ids', 'source_urls', 'relations']
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\r\n')
    writer.writerow(fields)
    for record in records:
        # Text cells are explicitly text even when source values begin =, +, -, @,
        # whitespace or control characters. Exact original values remain in JSON.
        writer.writerow([record[k] if k == 'bytes' else "'" + (
            canonical(record[k]) if isinstance(record[k], (list, dict)) else str(record[k] or '')) for k in fields])
    return output.getvalue().encode('utf-8-sig')


def plan(snapshot, verified_ids, failures):
    assets = {a.asset_id: a for a in snapshot.assets}
    good = set(verified_ids)
    if good & set(failures) or good | set(failures) != set(assets):
        raise ValueError('Asset outcome partition differs from snapshot')
    if any(code not in FAILURES for code in failures.values()):
        raise ValueError('Unknown failure code')
    payloads, files, summaries = {}, [], []
    total_missing, total_unknown = 0, 0
    for index, product in enumerate(snapshot.products, 1):
        directory = f'product-{index:04d}-' + hashlib.sha256(product.product_id.encode()).hexdigest()[:16]
        versions = sorted(product.versions, key=lambda v: (key(v) != key(product.latest_available), v.version_id, v.revision))
        grouped = {}
        for version in versions:
            for item in sorted(version.images, key=lambda i: i.ordinal):
                if item.asset_id not in good: continue
                asset = assets[item.asset_id]
                group = grouped.setdefault(asset.sha256, {'asset': asset, 'asset_ids': [], 'relations': []})
                if asset.asset_id not in group['asset_ids']: group['asset_ids'].append(asset.asset_id)
                group['relations'].append({'asset_id': asset.asset_id, 'version_id': version.version_id,
                    'revision': version.revision, 'source_image_id': item.source_image_id,
                    'ordinal': item.ordinal, 'source_url': item.source_url, 'variant_ids': list(item.variant_ids)})
        for number, (sha, group) in enumerate(grouped.items(), 1):
            asset = group['asset']
            files.append({'path': f'{directory}/images/{number:04d}-{sha}.{EXT[asset.format]}',
                'product_id': product.product_id, 'asset_ids': group['asset_ids'], 'sha256': sha,
                'bytes': asset.bytes, 'version_ids': sorted({f"{r['version_id']}@{r['revision']}" for r in group['relations']}),
                'source_urls': sorted({r['source_url'] for r in group['relations']}),
                'relations': group['relations']})
        required_assets = sorted({i.asset_id for v in product.versions for i in v.images if i.asset_id})
        missing = [{'kind': 'frozen_asset', 'asset_id': aid, 'reason': failures[aid]}
                   for aid in required_assets if aid in failures]
        current = next((v for v in product.versions if key(v) == key(product.latest_observed)), None)
        unknown = []
        if current is None:
            unknown.append({'reason': 'NO_OBSERVED_VERSION', 'detail': 'No frozen current gallery manifest'})
        else:
            if not current.enumeration_complete:
                unknown.append({'reason': 'ENUMERATION_UNKNOWN', 'detail': current.enumeration_reason})
            for item in current.images:
                if item.asset_id is None:
                    missing.append({'kind': 'latest_relation', 'version_id': current.version_id,
                        'revision': current.revision, 'source_image_id': item.source_image_id,
                        'source_url': item.source_url, 'reason': item.missing_reason or 'NOT_ARCHIVED'})
        scope='product.images' if snapshot.schema_version==1 else current.coverage_scope if current else 'unknown'
        observed_scope_complete=not missing and not unknown
        if snapshot.schema_version==2 and scope=='browser.gallery':
            unknown.append({'reason':'FULL_PRODUCT_IMAGES_UNPROVEN','scope':'product.images',
                            'detail':'Observed browser gallery does not prove the complete source product.images collection'})
        coverage = {'scope': scope, 'latest_observed': product.latest_observed.model_dump(mode='json') if product.latest_observed else None,
            'enumeration_complete': bool(current and current.enumeration_complete),
            'expected_count': current.expected_count if current else None,
            'current_readable_relation_count': sum(i.asset_id in good for i in current.images) if current else 0,
            'required_historical_asset_ids': required_assets, 'missing_count': len(missing),
            'unknown_count': len(unknown), 'complete': not missing and not unknown}
        if snapshot.schema_version==2:
            coverage['observed_scope_complete']=observed_scope_complete
            coverage['full_product_images_complete']=None if scope=='browser.gallery' else observed_scope_complete
        total_missing += len(missing); total_unknown += len(unknown)
        summaries.append({'product_id': product.product_id, 'directory': directory,
                          'coverage': coverage, 'capability_notes': [n.model_dump() for n in product.capability_notes]})
        metadata = {'product_id': product.product_id, 'source': json.loads(product.source_json),
            'date_basis': json.loads(product.date_basis_json),
            'latest_available': product.latest_available.model_dump(mode='json') if product.latest_available else None,
            'latest_observed': product.latest_observed.model_dump(mode='json') if product.latest_observed else None,
            'versions': [v.model_dump(mode='json') for v in product.versions],
            'assets': [assets[aid].model_dump(mode='json') for aid in required_assets],
            'coverage': coverage, 'capability_notes': [n.model_dump() for n in product.capability_notes]}
        for filename, value in [('product.json', metadata), ('missing.json', {'missing': missing, 'unknown': unknown})]:
            name = directory + '/' + filename
            payloads[name] = json_bytes(value)
            files.append(file_record(name, payloads[name], product.product_id))
    payloads['manifest.csv'] = csv_bytes(files)
    files.append(file_record('manifest.csv', payloads['manifest.csv']))
    manifest = {'schema_version': snapshot.schema_version, 'snapshot_sha256': snapshot.digest,
        'snapshot': snapshot.model_dump(mode='json'),
        'state': 'partial' if total_missing or total_unknown else 'succeeded',
        'scope_statement': '承诺范围内完整' if not total_missing and not total_unknown else '承诺范围存在缺失或未知',
        'missing_count': total_missing, 'unknown_count': total_unknown,
        'verified_asset_ids': sorted(good), 'asset_failures': failures,
        'products': summaries, 'files': files,
        'index_policy': 'manifest.json indexes payloads and manifest.csv; its own bytes are covered by the returned ZIP SHA256. CSV indexes payloads only.'}
    payloads['manifest.json'] = json_bytes(manifest)
    return manifest, payloads
