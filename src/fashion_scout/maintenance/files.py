import hashlib
import os
from pathlib import Path
import warnings
from PIL import Image,UnidentifiedImageError
from fashion_scout.exports.engine import no_links,safe_member,file_identity,ExportError

CHUNK=1024*1024
MAX_ASSET=64*1024**2
MAX_TOTAL=4*1024**3


class MaintenanceError(Exception):
    def __init__(self,code):self.code=code


def hash_file(path,checkpoint=lambda:None,limit=MAX_TOTAL):
    digest=hashlib.sha256();size=0
    with path.open('rb') as stream:
        while chunk:=stream.read(CHUNK):
            checkpoint();size+=len(chunk)
            if size>limit:raise MaintenanceError('FILE_LIMIT')
            digest.update(chunk)
    return digest.hexdigest(),size


def check_asset(asset,roots,destination=None,checkpoint=lambda:None):
    target=None
    try:
        checkpoint()
        if asset['bytes']<1 or asset['bytes']>MAX_ASSET:raise MaintenanceError('ASSET_LIMIT')
        root=Path(roots[asset['root_id']]);relative=safe_member(asset['relative_path'])
        if not root.is_absolute():raise MaintenanceError('INVALID_PATH')
        path=root.joinpath(*relative.split('/'));no_links(path)
        if not path.resolve().is_relative_to(root.resolve()):raise MaintenanceError('INVALID_PATH')
        before=file_identity(path.stat())
        if before[2]!=asset['bytes']:raise MaintenanceError('SIZE_MISMATCH')
        if destination:
            try:
                destination.parent.mkdir(parents=True,exist_ok=True);no_links(destination)
                target=destination.open('xb')
            except OSError:raise MaintenanceError('OUTPUT_WRITE_FAILED') from None
        digest=hashlib.sha256();size=0
        with path.open('rb') as stream:
            handle=os.fstat(stream.fileno())
            if file_identity(handle)!=before:raise MaintenanceError('SOURCE_CHANGED')
            while chunk:=stream.read(CHUNK):
                checkpoint();size+=len(chunk)
                if size>asset['bytes']:raise MaintenanceError('SOURCE_CHANGED')
                digest.update(chunk)
                if target:
                    try:target.write(chunk)
                    except OSError:raise MaintenanceError('OUTPUT_WRITE_FAILED') from None
            after=os.fstat(stream.fileno())
            if file_identity(after)!=before or after.st_ctime_ns!=handle.st_ctime_ns:raise MaintenanceError('SOURCE_CHANGED')
        if target:
            try:target.flush();os.fsync(target.fileno());target.close();target=None
            except OSError:raise MaintenanceError('OUTPUT_WRITE_FAILED') from None
        if size!=asset['bytes'] or digest.hexdigest()!=asset['sha256']:raise MaintenanceError('HASH_MISMATCH')
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(destination or path) as image:
                if image.width*image.height>50_000_000 or getattr(image,'n_frames',1)!=1:raise MaintenanceError('IMAGE_INVALID')
                if image.format!=asset['format']:raise MaintenanceError('IMAGE_FORMAT_UNKNOWN' if not asset['format'] else 'IMAGE_FORMAT_MISMATCH')
                image.verify()
            with Image.open(destination or path) as image:image.load()
        if asset['state']!='verified':raise MaintenanceError('ASSET_STATE_UNKNOWN')
        if hash_file(path,checkpoint,MAX_ASSET)!=(asset['sha256'],asset['bytes']) or file_identity(path.stat())!=before:
            raise MaintenanceError('SOURCE_CHANGED')
        return None
    except FileNotFoundError:code='ASSET_MISSING'
    except PermissionError:code='ASSET_UNREADABLE'
    except ExportError:code='INVALID_PATH'
    except MaintenanceError as exc:
        if exc.code=='OUTPUT_WRITE_FAILED':raise
        code=exc.code
    except (UnidentifiedImageError,Image.DecompressionBombError,Image.DecompressionBombWarning,ValueError):code='IMAGE_INVALID'
    except KeyError:code='ROOT_UNKNOWN'
    except OSError as exc:
        if destination:raise MaintenanceError('OUTPUT_WRITE_FAILED') from None
        code='ASSET_UNREADABLE'
    finally:
        if target:target.close()
    return {'object_id':'asset:'+asset['id'],'code':code,'category':'missing' if code=='ASSET_MISSING' else 'unknown' if code in {'ASSET_UNREADABLE','ROOT_UNKNOWN','IMAGE_FORMAT_UNKNOWN','ASSET_STATE_UNKNOWN'} else 'damaged'}


def verify_inventory(inventory,checkpoint=lambda:None):
    issues=list(inventory['issues']);verified=0
    for asset in inventory['assets']:
        issue=check_asset(asset,inventory['roots'],checkpoint=checkpoint)
        if issue:issues.append(issue)
        else:verified+=1
    counts={category:sum(i['category']==category for i in issues) for category in ('missing','damaged','unknown')}
    return {'state':'partial' if issues else 'succeeded','counts':{'products':len(inventory['products']),'assets':len(inventory['assets']),'verified':verified,**counts},'issues':issues}
