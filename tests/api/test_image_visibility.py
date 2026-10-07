"""New款 membership requires intact decoded local imagery; audit data is retained."""
import hashlib
from .helpers import seed


def test_missing_corrupt_or_metadata_only_products_are_hidden_from_new(api_env):
    client, app, runs, paths, token = api_env
    ids = seed(runs, paths, 4)
    assert client.get('/v1/products').json()['total'] == 3
    assert client.get('/v1/products/' + ids[3]).status_code == 200
    client.patch('/v1/products/' + ids[0] + '/user-state', json={'expected_revision': 1, 'favorite': True})
    # A file with a matching persisted hash is still unusable if it is not an image.
    for n in (0, 1):
        aid = 'fixture-asset-0-' + str(n)
        path = paths.media / (aid + '.png')
        data = b'not a decoded gallery image'
        path.write_bytes(data)
        with runs.db.write() as conn:
            conn.execute('UPDATE assets SET sha256=?,bytes=? WHERE id=?', (hashlib.sha256(data).hexdigest(), len(data), aid))
        (paths.media / ('fixture-asset-1-' + str(n) + '.png')).unlink()
        (paths.media / ('fixture-asset-2-' + str(n) + '.png')).write_bytes(b'tampered')
    before = {pid: client.get('/v1/products/' + pid).json()['product']['user_state'] for pid in ids}
    result = client.get('/v1/products').json()
    assert result['total'] == 0 and result['items'] == []
    favorite = client.get('/v1/products?view=favorites').json()
    assert favorite['total'] == 1 and favorite['items'][0]['id'] == ids[0]
    assert favorite['items'][0]['images'] == [] and favorite['items'][0]['album']['stored_count'] == 0
    assert {pid: client.get('/v1/products/' + pid).json()['product']['user_state'] for pid in ids} == before
    with runs.db.read() as conn:
        assert conn.execute('SELECT COUNT(*) FROM products').fetchone()[0] == 4
        assert conn.execute('SELECT COUNT(*) FROM product_versions').fetchone()[0] == 4


def test_registering_sites_and_reading_views_keeps_37_exclusions(api_env):
    client, app, runs, paths, token = api_env
    ids = seed(runs, paths, 37)
    with runs.db.write() as conn:
        conn.execute("UPDATE product_user_state SET excluded=1,favorite=1,category_override='tops',revision=7")
        before = [dict(r) for r in conn.execute('SELECT * FROM product_user_state ORDER BY product_id')]
    runs.initialize()
    assert client.get('/v1/products').json()['total'] == 0
    assert client.get('/v1/products?view=favorites').json()['total'] == 37
    with runs.db.read() as conn:
        assert [dict(r) for r in conn.execute('SELECT * FROM product_user_state ORDER BY product_id')] == before
        assert conn.execute('SELECT COUNT(*) FROM products').fetchone()[0] == len(ids)
