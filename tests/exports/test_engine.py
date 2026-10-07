import copy
import csv
import hashlib
import io
import json
import os
from pathlib import Path
from unittest.mock import patch
import zipfile
import pytest
from pydantic import ValidationError
from fashion_scout.exports import ExportSnapshot, Limits, export_zip, verify_zip, ExportError
from fashion_scout.exports import engine
from fashion_scout.exports.manifest import plan
from .fixtures import sample


@pytest.fixture
def env(tmp_path):
    media=tmp_path/'media'
    return sample(media),{'media':media},tmp_path/'out'


def build(env):
    value,roots,out=env
    frozen=ExportSnapshot.capture(value)
    result=export_zip(frozen,roots,out)
    assert result.state in {'succeeded','partial'},result
    return frozen,result,verify_zip(Path(result.path),frozen)


def test_complete_history_dedupe_relations_and_safe_csv(env):
    frozen,result,manifest=build(env)
    assert result.state=='succeeded' and result.missing_count==0 and result.unknown_count==0
    images=[f for f in manifest['files'] if f['asset_ids']]
    assert len(images)==3
    assert images[0]['asset_ids']==['a','alias']
    assert len(images[0]['relations'])==3 and images[0]['version_ids']==['latest@2','old@1']
    assert images[-1]['asset_ids']==['b']  # latest a,c first; history-only b last
    assert len(images[0]['source_urls'])==2
    with zipfile.ZipFile(result.path) as archive:
        assert len(archive.namelist())==7
        for record in manifest['files']:
            data=archive.read(record['path'])
            assert len(data)==record['bytes'] and hashlib.sha256(data).hexdigest()==record['sha256']
        product=json.loads(archive.read(manifest['products'][0]['directory']+'/product.json'))
        assert product['source']['title']=='=危险公式 女装'
        assert product['source']['options']['尺码']==['S','M']
        rows=list(csv.DictReader(io.StringIO(archive.read('manifest.csv').decode('utf-8-sig'))))
        for row in rows:
            assert all(v.startswith("'") for k,v in row.items() if k!='bytes')
        assert any('HYPERLINK' in r['source_urls'] for r in rows)
    assert hashlib.sha256(Path(result.path).read_bytes()).hexdigest()==result.sha256
    assert all('CON' not in n and '..' not in n for n in [f['path'] for f in manifest['files']])
    assert sorted(p.name for p in env[2].iterdir())==[Path(result.path).name]


def test_current_missing_with_old_preview_and_unknown_enumeration(env):
    value,roots,out=env
    p=value['products'][0]
    p['versions'].append({'version_id':'observed','revision':3,'images':[{'source_image_id':'missing','source_url':'https://example.invalid/new.png','ordinal':0,'asset_id':None,'missing_reason':'HTTP_404'}],
                          'enumeration_complete':False,'expected_count':None,'enumeration_reason':'分页枚举未完成'})
    p['latest_observed']={'version_id':'observed','revision':3}
    frozen,result,manifest=build(env)
    assert result.state=='partial' and result.missing_count==1 and result.unknown_count==1
    assert manifest['products'][0]['coverage']['expected_count'] is None
    assert manifest['products'][0]['coverage']['current_readable_relation_count']==0
    assert len([f for f in manifest['files'] if f['asset_ids']])==3
    with zipfile.ZipFile(result.path) as z:
        missing=json.loads(z.read(manifest['products'][0]['directory']+'/missing.json'))
        assert missing['missing'][0]['reason']=='HTTP_404'
        assert missing['unknown'][0]['detail']=='分页枚举未完成'


def test_no_images_still_metadata(env):
    value,roots,out=env
    value['assets']=[]
    p=value['products'][0];p.update(versions=[],latest_available=None,latest_observed=None)
    frozen,result,manifest=build(env)
    assert result.state=='partial' and result.unknown_count==1
    assert len(manifest['files'])==3
    with zipfile.ZipFile(result.path) as z:assert len(z.namelist())==4


@pytest.mark.parametrize('problem,expected',[('missing','ASSET_MISSING'),('hash','HASH_MISMATCH'),('bytes','SIZE_MISMATCH'),('invalid','IMAGE_INVALID'),('format','IMAGE_FORMAT_MISMATCH'),('unreadable','ASSET_UNREADABLE')])
def test_bad_asset_is_partial_even_historical_or_duplicate(env,problem,expected):
    value,roots,out=env
    asset=value['assets'][1];path=roots['media']/asset['relative_path'] # historical-only b
    if problem=='missing':path.unlink()
    if problem=='hash':path.write_bytes(b'X'*asset['bytes'])
    if problem=='bytes':path.write_bytes(b'x')
    if problem=='invalid':
        path.write_bytes(b'x'*asset['bytes']);asset['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    if problem=='format':asset['format']='JPEG'
    original=Path.open
    def open_file(p,*args,**kwargs):
        if problem=='unreadable' and p==path:raise PermissionError('synthetic read denial')
        return original(p,*args,**kwargs)
    with patch.object(Path,'open',open_file):frozen,result,manifest=build(env)
    assert result.state=='partial' and result.missing_count==1
    assert manifest['asset_failures']['b']==expected
    assert not any('b' in r['asset_ids'] for r in manifest['files'])


@pytest.mark.parametrize('relative',['../escape.png','/absolute.png','C:/other.png','nested/../a.png','nested\\a.png','NUL.png','aux','COM1.txt','safe.png:stream','name.','name ','//server/share','CONIN$','a\x00.png'])
def test_source_paths_cannot_escape(env,relative):
    env[0]['assets'][0]['relative_path']=relative
    frozen,result,manifest=build(env)
    assert result.state=='partial' and manifest['asset_failures']['a']=='INVALID_PATH'


@pytest.mark.parametrize('name',['../x','/x','x\\y','C:/x','NUL.txt','a//b','a/./b','COM¹.txt','x:ads'])
def test_member_names_rejected(name):
    with pytest.raises(ExportError):engine.safe_member(name)


def test_snapshot_deep_freeze_and_strict_schema(env):
    value,roots,out=env
    frozen=ExportSnapshot.capture(value);digest=frozen.digest
    value['products'][0]['versions'][0]['images'].clear()
    value['products'][0]['source_json']='{}'
    value['assets'].clear()
    assert frozen.digest==digest and len(frozen.assets)==4
    with pytest.raises(ValidationError):frozen.products[0].product_id='new'
    assert isinstance(frozen.products,tuple) and isinstance(frozen.products[0].versions[0].images,tuple)
    result=export_zip(frozen,roots,out);assert result.state=='succeeded'
    wrong=frozen.model_dump(mode='json');wrong['products'][0]['versions'][0]['expected_count']=99
    with pytest.raises(ValidationError):ExportSnapshot.capture(wrong)
    wrong=frozen.model_dump(mode='json');wrong['url']='https://example.invalid'
    with pytest.raises(ValidationError):ExportSnapshot.capture(wrong)


def test_duplicate_snapshot_ids_and_bad_pointers(env):
    value=env[0]
    for wrong in [dict(value,products=value['products']*2),dict(value,assets=value['assets']*2)]:
        with pytest.raises(ValidationError):ExportSnapshot.capture(wrong)
    value['products'][0]['latest_observed']['version_id']='nonexistent'
    with pytest.raises(ValidationError):ExportSnapshot.capture(value)


def test_changed_during_read_is_refused(env):
    value,roots,out=env
    original=engine.unchanged
    def mutate(asset,*args):
        if asset.asset_id=='b':
            path=roots['media']/'b.png';path.write_bytes(path.read_bytes()+b'changed')
        return original(asset,*args)
    with patch.object(engine,'unchanged',mutate):frozen,result,manifest=build(env)
    assert result.state=='partial' and manifest['asset_failures']['b']=='SOURCE_CHANGED'


def test_changed_during_zip_build_rebuilds_without_file(env):
    value,roots,out=env
    original=engine.write_archive
    calls=[]
    def mutate(*args):
        result=original(*args);calls.append(1)
        if len(calls)==1:(roots['media']/'b.png').write_bytes(b'replaced')
        return result
    with patch.object(engine,'write_archive',mutate):frozen,result,manifest=build(env)
    assert len(calls)==2 and manifest['asset_failures']['b']=='SOURCE_CHANGED'
    assert not any('b' in r['asset_ids'] for r in manifest['files'])


def test_continuous_changes_fail_without_publication(env):
    value,roots,out=env
    original=engine.write_archive;calls=[]
    def mutate(*args):
        result=original(*args);calls.append(1)
        (roots['media']/('b.png' if len(calls)==1 else 'c.png')).write_bytes(b'change')
        return result
    with patch.object(engine,'write_archive',mutate):result=export_zip(ExportSnapshot.capture(value),roots,out)
    assert result.state=='failed' and result.error_code=='SOURCE_UNSTABLE' and result.path is None
    assert list(out.iterdir())==[]


@pytest.mark.parametrize('phase',['write','verify','publish'])
def test_output_failures_do_not_publish_or_delete_other_files(env,phase):
    value,roots,out=env;out.mkdir();sentinel=out/'unrelated.txt';sentinel.write_text('keep')
    target={'write':'write_archive','verify':'verify_zip','publish':'os.link'}[phase]
    error=ExportError('ZIP_HASH_MISMATCH') if phase=='verify' else OSError('synthetic output failure')
    with patch('fashion_scout.exports.engine.'+target,side_effect=error):
        result=export_zip(ExportSnapshot.capture(value),roots,out)
    assert result.state=='failed' and result.path is None
    assert list(out.iterdir())==[sentinel] and sentinel.read_text()=='keep'


def test_existing_same_snapshot_verified_reuse_no_source_access_or_overwrite(env):
    frozen,result,manifest=build(env)
    path=Path(result.path);before=path.read_bytes()
    (env[1]['media']/'a.png').unlink()
    reused=export_zip(frozen,env[1],env[2])
    assert reused.reused and reused.state=='succeeded' and path.read_bytes()==before
    changed=frozen.model_dump(mode='json');changed['products'][0]['source_json']='{"title":"changed"}'
    conflict=export_zip(ExportSnapshot.capture(changed),env[1],env[2])
    assert conflict.state=='failed' and conflict.error_code=='SNAPSHOT_CONFLICT' and path.read_bytes()==before
    path.write_bytes(b'corrupt existing output')
    corrupt=export_zip(frozen,env[1],env[2])
    assert corrupt.state=='failed' and path.read_bytes()==b'corrupt existing output'


@pytest.mark.parametrize('corruption',['extra','duplicate','case','bytes','manifest','symlink'])
def test_reopen_verification_rejects_member_and_manifest_tamper(env,corruption):
    frozen,result,manifest=build(env)
    archive=Path(result.path)
    with zipfile.ZipFile(archive) as z:items=[(i,z.read(i.filename)) for i in z.infolist()]
    with zipfile.ZipFile(archive,'w') as z:
        for info,data in items:
            if corruption=='symlink' and info.filename==manifest['files'][0]['path']:info.external_attr=0o120777<<16
            if corruption=='bytes' and info.filename==manifest['files'][0]['path']:data=b'bad'
            if corruption=='manifest' and info.filename=='manifest.json':data=data.replace(b'"state":"succeeded"',b'"state":"partial"')
            z.writestr(info,data)
        if corruption=='extra':z.writestr('unexpected.txt',b'x')
        if corruption=='duplicate':
            with pytest.warns(UserWarning):z.writestr(items[0][0],items[0][1])
        if corruption=='case':z.writestr(items[0][0].filename.upper(),items[0][1])
    with pytest.raises(ExportError):verify_zip(archive,frozen)


def test_duplicate_content_in_two_products_is_not_cross_product_dedup(env):
    value,roots,out=env
    second=copy.deepcopy(value['products'][0]);second['product_id']='second'
    value['products'].append(second)
    frozen,result,manifest=build(env)
    assert len([f for f in manifest['files'] if f['asset_ids']])==6


def test_limits_do_not_load_oversized_asset(env):
    value,roots,out=env
    result=export_zip(ExportSnapshot.capture(value),roots,out,Limits(max_asset_bytes=1))
    assert result.state=='partial' and result.missing_count==4
    result=export_zip(ExportSnapshot.capture(value),roots,out/'another',Limits(max_total_bytes=1))
    assert result.state=='failed' and result.error_code=='SNAPSHOT_BYTES_LIMIT'


def test_pixel_limit_and_unknown_root_are_explicit(env):
    value,roots,out=env
    result=export_zip(ExportSnapshot.capture(value),roots,out,Limits(max_pixels=1))
    assert result.state=='partial' and result.missing_count==4
    result=export_zip(ExportSnapshot.capture(value),{},out/'missing-root')
    manifest=verify_zip(Path(result.path),ExportSnapshot.capture(value))
    assert set(manifest['asset_failures'].values())=={'ROOT_UNAVAILABLE'}


def test_real_reparse_escape_is_not_read(env,tmp_path):
    value,roots,out=env
    outside=tmp_path/'outside';outside.mkdir()
    (outside/'outside.png').write_bytes((roots['media']/'a.png').read_bytes())
    if os.name=='nt':
        import _winapi
        _winapi.CreateJunction(str(outside),str(roots['media']/'link'))
    else:
        os.symlink(outside,roots['media']/'link',target_is_directory=True)
    try:
        value['assets'][0]['relative_path']='link/outside.png'
        frozen,result,manifest=build(env)
        assert manifest['asset_failures']['a']=='INVALID_PATH'
        assert (outside/'outside.png').exists()
    finally:
        if os.name=='nt':(roots['media']/'link').rmdir()
        else:(roots['media']/'link').unlink()


def test_file_replacement_same_bytes_detected(env):
    value,roots,out=env
    original=engine.validate_image
    def replace(path,asset,limits):
        original(path,asset,limits)
        if asset.asset_id=='b':
            target=roots['media']/'b.png';info=target.stat()
            other=roots['media']/'replacement.png';other.write_bytes(target.read_bytes())
            os.utime(other,ns=(info.st_atime_ns,info.st_mtime_ns));os.replace(other,target)
    with patch.object(engine,'validate_image',replace):frozen,result,manifest=build(env)
    assert manifest['asset_failures']['b']=='SOURCE_CHANGED'


def test_mid_read_mutation_and_bounded_reads(env):
    value,roots,out=env
    original=Path.open;reads=[];changed=[]
    class Reader:
        def __init__(self,stream,path):self.stream,self.path=stream,path
        def __enter__(self):return self
        def __exit__(self,*args):return self.stream.__exit__(*args)
        def fileno(self):return self.stream.fileno()
        def read(self,size=-1):
            assert 0 < size <= 32
            reads.append(size);data=self.stream.read(size)
            if self.path.name=='b.png' and data and not changed:
                with original(self.path,'r+b') as writer:writer.write(b'X')
                changed.append(True)
            return data
    def opening(path,*args,**kwargs):
        stream=original(path,*args,**kwargs)
        if path.parent==roots['media'] and args==('rb',):return Reader(stream,path)
        return stream
    with patch.object(Path,'open',opening),patch.object(engine,'CHUNK',32):
        frozen,result,manifest=build(env)
    assert reads and changed and manifest['asset_failures']['b']=='SOURCE_CHANGED'


def test_same_snapshot_packages_are_deterministic_and_attempt_is_separate(env):
    frozen,result,manifest=build(env)
    second=export_zip(frozen,env[1],env[2]/'attempt-2')
    assert second.sha256==result.sha256 and not second.reused


def test_atomic_publish_race_never_overwrites(env):
    value,roots,out=env
    original=os.link;captured=[]
    def race(source,destination):
        Path(destination).write_bytes(b'other writer')
        captured.append(Path(destination))
        return original(source,destination)
    with patch.object(engine.os,'link',race):result=export_zip(ExportSnapshot.capture(value),roots,out)
    assert result.state=='failed' and result.path is None
    assert captured[0].read_bytes()==b'other writer'
    assert list(out.iterdir())==captured


def test_disk_reservation_failure_no_partial_output(env):
    value,roots,out=env
    with patch.object(engine.shutil,'disk_usage',return_value=type('Disk',(),{'free':0})()):
        result=export_zip(ExportSnapshot.capture(value),roots,out)
    assert result.state=='failed' and result.error_code=='DISK_RESERVE' and list(out.iterdir())==[]
