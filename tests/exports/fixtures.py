import hashlib
import json
from pathlib import Path
from PIL import Image


def sample(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    assets=[]
    for name,color in [('a','red'),('b','blue'),('c','green')]:
        path=root/(name+'.png')
        Image.new('RGB',(24,32),color).save(path,'PNG')
        assets.append({'asset_id':name,'root_id':'media','relative_path':name+'.png',
                       'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size,'format':'PNG'})
    # Same actual bytes, distinct archived record and URL.
    (root/'alias.png').write_bytes((root/'a.png').read_bytes())
    assets.append({**assets[0],'asset_id':'alias','relative_path':'alias.png'})
    def ref(aid,n,url=None):
        return {'source_image_id':f'source-{aid}-{n}','source_url':url or f'https://example.invalid/{aid}.png',
                'ordinal':n,'asset_id':aid,'variant_ids':['红色','=FORMULA()']}
    versions=[{'version_id':'old','revision':1,'images':[ref('b',0),ref('a',1)],'enumeration_complete':True,'expected_count':2},
              {'version_id':'latest','revision':2,'images':[ref('a',0),ref('alias',1,'=HYPERLINK("https://example.invalid")'),ref('c',2)],
               'enumeration_complete':True,'expected_count':3}]
    return {'schema_version':1,'export_id':'synthetic-测试/CON','captured_at':'2026-10-06T13:00:00Z',
            'promised_scope':'product.images','assets':assets,
            'products':[{'product_id':'../CON:测试','source_json':json.dumps({'title':'=危险公式 女装','url':'https://example.invalid/product/1','description':'原文\n第二行','options':{'尺码':['S','M'] }},ensure_ascii=False),
                'date_basis_json':json.dumps({'source_published_at':None,'reason':'synthetic/unknown','first_seen_at':'2026-10-06T12:00:00Z'}),
                'latest_available':{'version_id':'latest','revision':2},'latest_observed':{'version_id':'latest','revision':2},
                'versions':versions,'capability_notes':[{'scope':'product.video','status':'unsupported','reason':'范围外'}]}]}
