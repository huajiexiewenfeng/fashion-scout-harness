import ctypes
import hashlib
import os
from pathlib import Path
import shutil
import uuid
from fashion_scout.db import Database
from fashion_scout.domain import ScoutError
from fashion_scout.exports.engine import no_links,safe_member,ExportError


def local_directory(value):
    if not isinstance(value,str) or not value or len(value)>1024 or value.startswith(('\\\\','//')):
        raise ScoutError('INVALID_STORAGE_PATH','仅支持本机绝对目录',422)
    path=Path(value)
    if not path.is_absolute() or '..' in path.parts or path==Path(path.anchor) or any(':' in p for p in path.parts[1:]):
        raise ScoutError('INVALID_STORAGE_PATH','目录不能是磁盘根、设备或父级穿越路径',422)
    try:
        safe_member('/'.join(path.parts[1:]))
        no_links(path)
        if os.name=='nt' and ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) not in (2,3,6):
            raise ScoutError('INVALID_STORAGE_PATH','不支持网络盘或不可写磁盘',422)
        if path.exists() and not path.is_dir():raise OSError()
        return path.resolve()
    except (OSError,ExportError):raise ScoutError('INVALID_STORAGE_PATH','目录不可用或含链接/联接点',422) from None


def writable(path,min_free=64*1024**2):
    # Only a uniquely owned probe is removed; never delete user files/directories.
    try:
        path.mkdir(parents=True,exist_ok=True)
        no_links(path)
        if shutil.disk_usage(path).free<min_free:raise ScoutError('DISK_RESERVE','目录可用空间不足',409)
    except (OSError,ExportError):raise ScoutError('STORAGE_NOT_WRITABLE','目录无法安全写入',422) from None
    probe=path/('.scout-probe-'+uuid.uuid4().hex)
    try:
        with probe.open('xb') as stream:stream.write(b'probe');stream.flush();os.fsync(stream.fileno())
    except OSError:raise ScoutError('STORAGE_NOT_WRITABLE','目录无法写入',422) from None
    finally:probe.unlink(missing_ok=True)


class Storage:
    def __init__(self,paths):self.paths,self.db=paths,Database(paths.db)

    def get(self):
        with self.db.read() as conn:row=conn.execute('SELECT * FROM storage_preferences WHERE id=1').fetchone()
        return {'revision':row['revision'] if row else 0,'media_root':row['media_root'] if row else str(self.paths.media),
            'authority':'database' if row else 'legacy_default','affects':'future_archives','local_backup_root':str(self.paths.root/'backups')}

    def patch(self,revision,value):
        path=local_directory(value)
        if self.paths.root.is_relative_to(path) or any(path.is_relative_to(self.paths.root/name) for name in ('control','logs','backups','maintenance')):
            raise ScoutError('INVALID_STORAGE_PATH','请选择独立素材目录，不能覆盖应用或控制目录',422)
        with self.db.write() as conn:
            row=conn.execute('SELECT * FROM storage_preferences WHERE id=1').fetchone()
            current=row['revision'] if row else 0
            if revision!=current:raise ScoutError('REVISION_CONFLICT','保存位置已变化，请重新读取后核对',409)
            if conn.execute("SELECT 1 FROM runs WHERE state IN ('queued','running','interrupted','cancelling')").fetchone() or conn.execute("SELECT 1 FROM maintenance_jobs WHERE state IN ('queued','running')").fetchone() or conn.execute("SELECT 1 FROM archive_journal WHERE state!='committed' AND recovery_state!='superseded'").fetchone():
                raise ScoutError('STORAGE_BUSY','巡检、维护或未完成归档仍在使用素材根',409)
            for old in conn.execute('SELECT path FROM storage_roots'):
                old_path=Path(old['path'])
                if path!=old_path and (path.is_relative_to(old_path) or old_path.is_relative_to(path)):
                    raise ScoutError('INVALID_STORAGE_PATH','新旧素材根不能相互嵌套',422)
            writable(path)
            conn.execute('INSERT INTO storage_preferences VALUES (1,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,media_root=excluded.media_root',(current+1,str(path)))
            conn.execute("INSERT OR IGNORE INTO storage_roots VALUES (?,?,'media')",(hashlib.sha256(str(path).encode()).hexdigest(),str(path)))
        return self.get()
