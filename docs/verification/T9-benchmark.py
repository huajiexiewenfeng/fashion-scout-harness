"""Benchmark current code on the same live library using only SQLite mode=ro."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
LIVE = Path('E:/github-workspace/FashionScout')
if sys.argv[1] == 'source': sys.path.insert(0, str(ROOT / 'src'))
from fashion_scout.services.presentation import Presentation
from fashion_scout.services import presentation as module
from fashion_scout.media import images
from fashion_scout.services import listing as listing_module

class ReadOnly:
    @contextmanager
    def read(self):
        conn = sqlite3.connect((LIVE / 'data/scout.sqlite3').as_uri() + '?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        try: yield conn
        finally: conn.close()

db = ReadOnly()
def state():
    with db.read() as conn:
        rows = [tuple(r) for r in conn.execute('SELECT * FROM product_user_state ORDER BY product_id')]
        return {'products': conn.execute('SELECT COUNT(*) FROM products').fetchone()[0],
                'assets': conn.execute('SELECT COUNT(*) FROM assets').fetchone()[0],
                'user_state_sha256': hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()}

counters = {'full_decode':0, 'cover_checks':0}
full, cover = images.validate_image, listing_module.validate_archived_cover
def decode(*args, **kwargs):
    counters['full_decode'] += 1
    return full(*args, **kwargs)
def check(*args, **kwargs):
    counters['cover_checks'] += 1
    return cover(*args, **kwargs)
images.validate_image = module.validate_image = decode
listing_module.validate_archived_cover = check
before = state()
samples = []
def measure(name, call):
    counters.update(full_decode=0, cover_checks=0)
    start = time.perf_counter()
    value = call()
    row = {'name':name, 'seconds':round(time.perf_counter()-start,6), 'total':value['total'],
           'items':len(value['items']), 'cover_images':sum(len(p['images']) for p in value['items']),
           'response_bytes':len(json.dumps(value,ensure_ascii=False).encode()), **counters}
    samples.append(row); print(json.dumps(row), flush=True)
    return value

projection = Presentation(db)
first = measure('cold_first', lambda:projection.listing('new',None,None,40))
following = measure('next', lambda:projection.listing('new',None,first['next_cursor'],40))
assert len({p['id'] for p in first['items'] + following['items']}) == len(first['items']) + len(following['items']) == first['total']
for n in range(3): measure('refresh_' + str(n+1), lambda:projection.listing('new',None,None,40))
measure('new_instance_first', lambda:Presentation(db).listing('new',None,None,40))
after = state(); assert before == after
old = json.loads(Path('E:/github-workspace/.team/fashion-scout/t9-manager-before.json').read_text('utf-8'))
result = {'implementation':sys.argv[1], 'module':module.__file__, 'samples':samples, 'same_library':before,
          'business_read_only':True, 'before_equals_after':True, 'old_manager_benchmark':old,
          'cold_definition':'Fresh Presentation object, no cross-request result cache; OS disk cache is not flushed and may be warm.',
          'comparison':'Old and new use same real library through read-only connections; existing Manager timing was measured separately.'}
output = ROOT / 'docs/verification' / ('T9-' + sys.argv[1] + '-benchmark.json')
with output.open('x',encoding='utf-8') as stream: json.dump(result,stream,ensure_ascii=False,indent=2)
assert all(row['seconds'] < 1 for row in samples)
assert all(row['full_decode'] == 0 for row in samples)
