import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch
import pytest
from fashion_scout.maintenance.files import MaintenanceError
from tests.maintenance.test_local import setup,execute

module=importlib.import_module('fashion_scout.maintenance.restore')


def change_byte(path):
    data=bytearray(path.read_bytes());data[0]^=1;path.write_bytes(data)


@pytest.mark.parametrize('fault',['asset_before','db_before','asset_during','stage_asset','stage_db'])
def test_changes_after_preflight_never_publish(setup,tmp_path,fault):
    paths,runs,jobs,owner=setup;jid,_=jobs.create('backup','race',{'destination_id':'local'})
    result=execute(paths,jobs,owner);bundle=Path(result['result']['path']);target=tmp_path/'restored'
    manifest=json.loads((bundle/'manifest.json').read_text('utf-8'))
    asset=bundle/next(f['path'] for f in manifest['files'] if f['path'].startswith('assets/'))
    original_dump=None
    with runs.db.read() as c:original_dump=list(c.iterdump())
    initial_verify=module.verify_bundle;copy=module.copy_verified;verify_stage=module.verify_stage;triggered=[]
    def preflight(*args,**kwargs):
        value=initial_verify(*args,**kwargs)
        if fault=='asset_before':change_byte(asset);triggered.append(fault)
        if fault=='db_before':
            c=sqlite3.connect(bundle/'database.sqlite3');c.execute('UPDATE product_user_state SET favorite=1');c.commit()
            assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok';c.close();triggered.append(fault)
        return value
    def stage_check(files):
        if fault.startswith('stage_'):
            target_file=next(p for p,e,l in files if (p.name=='scout.sqlite3')==(fault=='stage_db'))
            change_byte(target_file);triggered.append(fault)
        return verify_stage(files)
    def actual_copy(source,target,expected,limit):
        if fault!='asset_during' or source!=asset:return copy(source,target,expected,limit)
        original_open=Path.open
        class Reader:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):return self
            def __exit__(self,*args):self.stream.close()
            def fileno(self):return self.stream.fileno()
            def read(self,size):
                chunk=self.stream.read(size)
                if chunk and not triggered:change_byte(source);triggered.append(fault)
                return chunk
        def opened(p,*args,**kwargs):
            stream=original_open(p,*args,**kwargs)
            return Reader(stream) if p==source and args and args[0]=='rb' else stream
        # Use the underlying open for deterministic mutation, avoiding recursive wrapper reads.
        def mutate_byte(p):
            with original_open(p,'r+b') as s:first=s.read(1);s.seek(0);s.write(bytes([first[0]^1]));s.flush()
        with patch.object(Path,'open',opened),patch(__name__+'.change_byte',mutate_byte):
            return copy(source,target,expected,limit)
    with patch.object(module,'verify_bundle',preflight),patch.object(module,'copy_verified',actual_copy),patch.object(module,'verify_stage',stage_check):
        with pytest.raises(MaintenanceError) as exc:module.restore(paths.root,jid,target,True)
    assert triggered==[fault]
    assert exc.value.code in {'RESTORE_FILE_CHANGED','RESTORE_FILE_MISMATCH'}
    assert not target.exists()
    with runs.db.read() as c:assert list(c.iterdump())==original_dump


def test_normal_complete_restore_still_matches_manifest(setup,tmp_path):
    paths,runs,jobs,owner=setup
    # Retain only complete synthetic products, preserving actual assets.
    with runs.db.write() as c:
        c.execute("DELETE FROM version_images WHERE version_id='fixture-version-3'")
        c.execute("DELETE FROM product_versions WHERE id='fixture-version-3'")
        c.execute("DELETE FROM collection_products WHERE product_id='fixture-003'")
        c.execute("DELETE FROM product_user_state WHERE product_id='fixture-003'")
        c.execute("DELETE FROM products WHERE id='fixture-003'")
    jid,_=jobs.create('backup','complete',{'destination_id':'local'});result=execute(paths,jobs,owner)
    assert result['state']=='succeeded';target=tmp_path/'complete'
    out=module.restore(paths.root,jid,target);assert out['state']=='succeeded' and not out['services_started']
    with sqlite3.connect(target/'scout.sqlite3') as c:
        for relative,root_id,digest in c.execute('SELECT relative_path,root_id,sha256 FROM assets'):
            root=c.execute('SELECT path FROM storage_roots WHERE id=?',(root_id,)).fetchone()[0]
            assert hashlib.sha256((Path(root)/relative).read_bytes()).hexdigest()==digest


def test_groups_use_frozen_product_names_and_keep_diagnostics(setup):
    paths,runs,jobs,owner=setup;jid,_=jobs.create('verify','names',{'scope':'all'})
    value=execute(paths,jobs,owner)
    assert value['finding_groups']==[{'category':'missing','code':'IMAGE_NOT_ARCHIVED','count':2,'product_count':1,'product_names':['米杏色 · 垂感连衣裙']}]
    assert all(i['object_id'].startswith('version:') for i in value['result']['issues'])
    jid,_=jobs.create('backup','backup-names',{'destination_id':'local'});backup=execute(paths,jobs,owner)
    assert backup['finding_groups']==value['finding_groups']
