import hashlib
import json
import uuid
from pathlib import Path
import pytest
from fashion_scout import client as c
from fashion_scout.config import Paths
from fashion_scout.domain import ScoutError
from fashion_scout.media import browser_intake as intake
from .test_bridge import image_bytes


def export_fixture(tmp_path,monkeypatch):
    base=tmp_path/'native-assets';directory=base/str(uuid.uuid4());directory.mkdir(parents=True)
    monkeypatch.setattr(intake,'native_base',lambda:base)
    data=image_bytes();path=directory/'image.png';path.write_bytes(data)
    manifest=directory/'manifest.json';url='https://futario.com/cdn/shop/files/example.png?width=1080'
    value={'assets':[{'id':'native-id','kind':'image','path':str(path),'url':url,'contentType':'image/webp'}],'failures':[]}
    manifest.write_text(json.dumps(value),encoding='utf-8')
    payload={'native_directory':str(directory),'manifest_path':str(manifest),'asset_id':'native-id','source_url':url,
             'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
    return payload,value,path,manifest


def test_native_selected_export_is_bounded_read_only_and_url_bound(tmp_path,monkeypatch):
    payload,value,path,manifest=export_fixture(tmp_path,monkeypatch)
    with intake.selected_export(payload) as stream:
        assert not stream.writable() and stream.read()==image_bytes()
    for change in ({'sha256':'0'*64},{'bytes':1},{'source_url':'https://futario.com/cdn/shop/files/different.png'}):
        with pytest.raises(ScoutError):
            with intake.selected_export({**payload,**change}):pass
    outside=tmp_path/'outside.png';outside.write_bytes(image_bytes())
    value['assets'][0]['path']=str(outside);manifest.write_text(json.dumps(value))
    with pytest.raises(ScoutError):
        with intake.selected_export(payload):pass


def test_native_duplicate_asset_and_reparse_member_rejected(tmp_path,monkeypatch):
    payload,value,path,manifest=export_fixture(tmp_path,monkeypatch)
    value['assets']*=2;manifest.write_text(json.dumps(value))
    with pytest.raises(ScoutError):
        with intake.selected_export(payload):pass
    link=path.parent/'link.png'
    try:link.symlink_to(path)
    except OSError:pytest.skip('Windows account cannot create a synthetic symlink')
    value['assets']=value['assets'][:1];value['assets'][0]['path']=str(link);manifest.write_text(json.dumps(value))
    with pytest.raises(ScoutError):
        with intake.selected_export(payload):pass


def test_old_saved_intent_spec_body_hash_and_bytes_are_unchanged(tmp_path):
    paths=Paths.at(tmp_path);journal=c.Journal(paths);journal.root.mkdir(parents=True)
    iid=uuid.uuid4().hex;k=uuid.uuid4().hex
    old_input={'new_intent':True,'overrides':{'window_days':7}}
    spec={'command':'start','input':old_input,'request_key':k,'method':'POST','path':'/v1/runs',
          'body':{'request_key':k,'trigger':'skill','overrides':{'window_days':7}}}
    record={'intent_id':iid,'created_at':1.0,'state':'sending','spec':spec,'sha256':c.fingerprint(spec)}
    path=journal.root/(iid+'.json');raw=json.dumps(record,ensure_ascii=True).encode();path.write_bytes(raw)
    assert journal.read(iid)['spec']==spec
    assert path.read_bytes()==raw and c.write_spec('start',c.validate('start',old_input),k)==spec
    new=c.write_spec('browser-continue',c.validate('browser-continue',{'new_intent':True,'run_id':'r'}),k)
    assert new['spec_schema']==2 and new['path']=='/v1/runs/r/browser-source/continue'


@pytest.mark.parametrize('command,payload',[
 ('browser-observe',{'new_intent':True,'run_id':'r','session_id':'a'*32,'observation':{'kind':'finish','success':True}}),
 ('browser-attach',{'new_intent':True,'run_id':'r','url':'https://other.invalid'}),
 ('browser-continue',{'new_intent':True,'run_id':'r','request_key':'caller'}),
])
def test_fixed_browser_commands_reject_source_control(command,payload):
    with pytest.raises(c.ClientError):c.validate(command,payload)
