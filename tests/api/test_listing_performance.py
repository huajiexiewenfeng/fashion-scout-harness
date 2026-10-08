import os
import pytest
from fashion_scout.media import images
from fashion_scout.services import listing as module
from .helpers import seed


def test_cover_projection_pages_60_without_full_gallery_or_history_reads(api_env, monkeypatch):
    client, app, runs, paths, token = api_env
    ids = seed(runs, paths, 80)
    visible = [pid for i, pid in enumerate(ids) if i % 4 != 3]
    checks = []
    original = module.validate_archived_cover
    def check(path, asset, *limits):
        checks.append(asset['id'])
        return original(path, asset, *limits)
    monkeypatch.setattr(module, 'validate_archived_cover', check)
    monkeypatch.setattr(images, 'validate_image', lambda *args: pytest.fail('Known archived covers must not decode entire images'))
    monkeypatch.setattr(app.state.presentation, 'detail', lambda *args, **kwargs: pytest.fail('List must not read full detail/history'))
    first = client.get('/v1/products?limit=40').json()
    assert first['total'] == 60 and len(first['items']) == 40
    assert len(checks) == 60 and len(set(checks)) == 60
    assert all(p['projection'] == 'cover' and len(p['images']) == 1 and 'versions' not in p and 'album' not in p for p in first['items'])
    checks.clear()
    second = client.get('/v1/products', params={'limit':40, 'cursor':first['next_cursor']}).json()
    assert len(checks) == 20 and len(second['items']) == 20 and second['next_cursor'] is None
    found = [p['id'] for p in first['items'] + second['items']]
    assert found == visible and len(set(found)) == 60
    checks.clear()
    assert client.get('/v1/products?limit=40').json()['total'] == 60 and len(checks) == 60


def test_cover_tampering_with_preserved_size_and_timestamp_is_rechecked(api_env):
    client, app, runs, paths, token = api_env
    seed(runs, paths, 1)
    first = client.get('/v1/products').json()['items'][0]
    assert first['images'][0]['asset_id'] == 'fixture-asset-0-0'
    path = paths.media / 'fixture-asset-0-0.png'
    old = path.stat(); data = bytearray(path.read_bytes()); data[-10] ^= 1
    path.write_bytes(data); os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
    newer = client.get('/v1/products').json()['items'][0]
    assert newer['images'][0]['asset_id'] == 'fixture-asset-0-1'
    (paths.media / 'fixture-asset-0-1.png').unlink()
    assert client.get('/v1/products').json()['total'] == 0
    detail = client.get('/v1/products/fixture-000').json()['product']
    assert detail['images'] == [] and len(detail['album']['missing']) == 2


def test_detail_still_checks_noncover_damage_and_retains_full_gallery(api_env):
    client, app, runs, paths, token = api_env
    seed(runs, paths, 1)
    original = client.get('/v1/products/fixture-000').json()['product']
    assert len(original['images']) == 2 and original['versions']
    (paths.media / 'fixture-asset-0-1.png').write_bytes(b'corrupt non-cover')
    summary = client.get('/v1/products').json()['items'][0]
    assert len(summary['images']) == 1 and summary['gallery_validation'] == 'on_open'
    detailed = client.get('/v1/products/fixture-000').json()['product']
    assert len(detailed['images']) == 1 and detailed['media_state'] == 'partial'
    assert detailed['album']['stored_count'] == 1 and len(detailed['album']['missing']) == 1
    assert detailed['version_id'] == original['version_id'] and detailed['versions'] == original['versions']


def test_legacy_archive_without_format_metadata_decodes_only_cover(api_env, monkeypatch):
    client, app, runs, paths, token = api_env
    seed(runs, paths, 1)
    with runs.db.write() as conn:
        conn.execute("UPDATE assets SET format='UNKNOWN',width=NULL,height=NULL")
    calls = []
    original = images.validate_image
    def check(path, *limits):
        calls.append(path.name)
        return original(path, *limits)
    monkeypatch.setattr(images, 'validate_image', check)
    result = client.get('/v1/products').json()
    assert result['total'] == 1 and len(calls) == 1 and calls == ['fixture-asset-0-0.png']
