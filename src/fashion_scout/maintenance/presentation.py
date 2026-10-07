"""Human-facing grouping; exact diagnostic results remain unchanged."""
import json


def finding_groups(issues,inventory):
    objects={};titles={};versions={}
    for v in inventory.get('versions',[]):
        pid=v['product_id'];key=f"version:{v['id']}:{v['revision']}";versions[(v['id'],v['revision'])]=pid
        objects[key]={pid}
        try:
            title=json.loads(v['manifest_json']).get('product',{}).get('title')
            if isinstance(title,str) and title.strip():titles[pid]=title.strip()[:200]
        except (ValueError,TypeError,AttributeError):pass
    for pid in inventory.get('products',[]):objects['product:'+pid]={pid}
    for r in inventory.get('relations',[]):
        pid=versions.get((r['version_id'],r['revision']))
        if pid is None:continue
        objects[f"version:{r['version_id']}:{r['revision']}:{r['source_image_id']}"]={pid}
        if r['asset_id']:objects.setdefault('asset:'+r['asset_id'],set()).add(pid)
    groups={}
    for issue in issues:
        key=(issue['category'],issue['code'])
        group=groups.setdefault(key,{'category':key[0],'code':key[1],'count':0,'products':set()})
        group['count']+=1;group['products'].update(objects.get(issue['object_id'],()))
    return [{'category':g['category'],'code':g['code'],'count':g['count'],'product_count':len(g['products']),
             'product_names':list(dict.fromkeys(titles[p] for p in sorted(g['products']) if p in titles))[:5]}
            for g in groups.values()]
