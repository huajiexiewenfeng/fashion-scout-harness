"""Explicit synthetic local fixtures; never run the production collector."""
import hashlib
import io
import json
from PIL import Image, ImageDraw
from fashion_scout.services.runs import canonical, digest


def seed(runs, paths, count=8):
    colors = ['#697457','#a47662','#3e5265','#d0b9a3','#4c4748','#93825e']
    from fashion_scout.domain.models import Snapshot
    revision, plan = runs.default_plan()
    snapshot = Snapshot(**plan.model_dump(), plan_revision=revision,
        window_start='2026-09-17T12:00:00Z', window_end='2026-10-01T12:00:00Z',
        adapter_versions={'futario':'futario-json-v1'}, site_entries={'futario':'https://example.invalid'},
        discovery_baseline_complete={'futario':False})
    run_id = 'synthetic-fixture-run'
    with runs.db.write() as conn:
        conn.execute("INSERT OR IGNORE INTO storage_roots VALUES ('fixture-root',?,'media')", (str(paths.media),))
        # Insert a terminal fixture atomically: no queued Run can ever be claimed by a live Worker.
        conn.execute("INSERT INTO runs(id,state,snapshot_json,created_at,finished_at) VALUES (?,'succeeded',?,'2026-10-01T12:00:00Z','2026-10-01T12:00:00Z')", (run_id,snapshot.model_dump_json()))
        for i in range(count):
            pid = f'fixture-{i:03}'
            title = ['秋日松弛感 · 羊毛针织衫','暖砂色 · 简约长款风衣','雾蓝色 · 轻盈衬衫','米杏色 · 垂感连衣裙','深灰色 · 直筒半裙','橄榄绿 · 休闲外套'][i % 6]
            category = ['knitwear','outerwear','tops','dress','bottoms','outerwear'][i % 6]
            source = {'source_id':str(i),'title':title,'url':f'https://example.invalid/products/{i}','source_published_at':None,'date_reason':'synthetic_fixture'}
            conn.execute("INSERT INTO products(id,site_id,source_id,first_seen_at,first_eligible_at,category_key) VALUES (?,'futario',?,'2026-10-01T12:00:00Z','2026-10-01T12:00:00Z',?)", (pid,str(i),category))
            conn.execute("INSERT INTO product_user_state(product_id) VALUES (?)", (pid,))
            conn.execute("INSERT INTO collection_products(run_id,product_id,seen_before_run,eligible,rule,listing_json) VALUES (?,?,0,1,'synthetic',?)", (run_id,pid,canonical(source)))
            images=[]
            # Every fourth product is an explicit missing-image fixture.
            for n in range(2):
                aid = None
                sha = None
                if i % 4 != 3:
                    image=Image.new('RGB',(600,800),'#eae7df')
                    draw=ImageDraw.Draw(image)
                    color=colors[(i+n)%len(colors)]
                    draw.ellipse((115,730,495,762),fill='#dbd7cd')
                    draw.polygon([(215,130),(275,110),(325,110),(385,130),(475,300),(395,342),(363,268),(386,684),(214,684),(237,268),(205,342),(125,300)],fill=color)
                    draw.ellipse((276,98,324,135),fill='#eae7df')
                    draw.line([(300,135),(300,670)],fill='#b4a895',width=2)
                    for y in range(210,610,65):draw.ellipse((307,y,313,y+6),fill='#d4c9b6')
                    draw.text((20,770),'SYNTHETIC TEST FIXTURE',fill='#817b70')
                    output=io.BytesIO();image.save(output,'PNG');data=output.getvalue()
                    aid=f'fixture-asset-{i}-{n}';sha=hashlib.sha256(data).hexdigest();relative=aid+'.png'
                    (paths.media/relative).write_bytes(data)
                    conn.execute("INSERT INTO assets(id,root_id,relative_path,sha256,bytes,state,verified_at,format,width,height) VALUES (?,'fixture-root',?,?,?,'verified','2026-10-01T12:00:00Z','PNG',600,800)", (aid,relative,sha,len(data)))
                images.append({'asset_id':aid,'sha256':sha,'source_image_id':f'{i}-{n}','url':f'https://example.invalid/{i}-{n}.png','ordinal':n,'error_code':None if aid else 'HTTP_404'})
            manifest={'product':source,'images':images,'promised_scopes':['product.images'],'expected_count':2,'enumeration_complete':True,'complete':i%4!=3,'capability_notes':[]}
            content=digest({'sha256':sorted({x['sha256'] for x in images if x['sha256']})});vid='fixture-version-'+str(i)
            conn.execute("INSERT INTO product_versions VALUES (?,1,?,?,?,?)",(vid,pid,digest(manifest),canonical(manifest),content))
            for item in images:conn.execute("INSERT INTO version_images VALUES (?,1,?,?,?,?)",(vid,item['source_image_id'],item['url'],item['ordinal'],item['asset_id']))
            conn.execute("UPDATE products SET latest_observed_version_id=?,latest_observed_revision=1,latest_available_version_id=?,latest_available_revision=?,latest_complete_version_id=?,latest_complete_revision=? WHERE id=?",(vid,vid if i%4!=3 else None,1 if i%4!=3 else None,vid if i%4!=3 else None,1 if i%4!=3 else None,pid))
    return [f'fixture-{i:03}' for i in range(count)]
