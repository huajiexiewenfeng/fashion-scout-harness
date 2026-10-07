"""Bounded offline snapshot-to-ZIP engine. No jobs, DB access or source requests."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import warnings
import zipfile
from contextvars import ContextVar

from PIL import Image, UnidentifiedImageError
from .models import ExportSnapshot, ExportResult, Limits, capture_snapshot
from .manifest import json_bytes, plan

CHUNK = 1024 * 1024
META_LIMIT = 64 * 1024**2
_CHECKPOINT = ContextVar('export_checkpoint', default=lambda: None)


def checkpoint():
    _CHECKPOINT.get()()
DEVICES = re.compile(r'^(CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|CLOCK\$|COM[0-9¹²³]|LPT[0-9¹²³])(?:\.|$)', re.I)


class ExportError(Exception):
    def __init__(self, code): self.code = code


def safe_member(name):
    if not isinstance(name, str) or not name or '\\' in name or len(name) > 512:
        raise ExportError('INVALID_MEMBER')
    parts = name.split('/')
    if any(not p or p in {'.', '..'} or p.endswith(('.', ' ')) or DEVICES.match(p)
           or any(ord(c) < 32 or c in ':<>"|?*' for c in p) for p in parts):
        raise ExportError('INVALID_MEMBER')
    if PurePosixPath(name).is_absolute(): raise ExportError('INVALID_MEMBER')
    return name


def file_identity(info):
    # CPython Windows stat(path).st_ctime may still mean birth time whereas
    # fstat(handle).st_ctime reports change time. Compare explicit birth time on
    # Windows, and change time on POSIX; final checks also rehash actual content.
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, getattr(info, 'st_birthtime_ns', info.st_ctime_ns)


def no_links(path):
    """Reject symlinks/junctions at every existing path component, including root."""
    for node in (path, *path.parents):
        try: info = node.lstat()
        except FileNotFoundError: continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ExportError('INVALID_PATH')


def source_path(asset, roots):
    root = roots.get(asset.root_id)
    if root is None: raise ExportError('ROOT_UNAVAILABLE')
    try:
        safe_member(asset.relative_path)
        path = root.joinpath(*asset.relative_path.split('/'))
        no_links(path)
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root) or resolved == root:
            raise ExportError('INVALID_PATH')
        if not stat.S_ISREG(resolved.stat().st_mode): raise ExportError('INVALID_PATH')
        return resolved
    except ExportError as exc:
        if exc.code == 'INVALID_MEMBER': raise ExportError('INVALID_PATH') from None
        raise
    except FileNotFoundError: raise ExportError('ASSET_MISSING') from None
    except OSError: raise ExportError('ASSET_UNREADABLE') from None


class Workspace:
    def __init__(self, output):
        self.output = output
        self.path = Path(tempfile.mkdtemp(prefix='.t5a-', dir=output))
        self.identity = file_identity(self.path.stat())[:2]
        self.owned = {}

    def create(self, suffix):
        path = self.path / (str(len(self.owned)) + suffix)
        stream = path.open('xb')
        self.owned[path] = file_identity(os.fstat(stream.fileno()))[:2]
        return path, stream

    def cleanup(self):
        # Never recursively delete. Unknown/replaced files remain for later inspection.
        try:
            no_links(self.path)
            if self.path.parent != self.output or self.path.resolve().parent != self.output:
                return
            if file_identity(self.path.stat())[:2] != self.identity: return
            for path, identity in self.owned.items():
                try:
                    info = path.lstat()
                    if stat.S_ISREG(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400 and file_identity(info)[:2] == identity:
                        path.unlink()
                except OSError: pass
            self.path.rmdir()
        except (OSError, ExportError): pass


def validate_image(path, asset, limits):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.width * image.height > limits.max_pixels:
                    raise ExportError('IMAGE_PIXEL_LIMIT')
                if image.format != asset.format:
                    raise ExportError('IMAGE_FORMAT_MISMATCH')
                if getattr(image, 'n_frames', 1) != 1:
                    raise ExportError('IMAGE_INVALID')
                image.verify()
            with Image.open(path) as image: image.load()
    except ExportError: raise
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ExportError('IMAGE_INVALID') from None


def unchanged(asset, roots, original, identity):
    try:
        current = source_path(asset, roots)
        if current != original or file_identity(current.stat()) != identity: return False
        digest, size = hashlib.sha256(), 0
        with current.open('rb') as stream:
            before = os.fstat(stream.fileno())
            if file_identity(before) != identity: return False
            while chunk := stream.read(CHUNK):
                checkpoint()
                size += len(chunk)
                if size > asset.bytes: return False
                digest.update(chunk)
            after = os.fstat(stream.fileno())
            if file_identity(after) != identity or after.st_ctime_ns != before.st_ctime_ns: return False
        return (size == asset.bytes and digest.hexdigest() == asset.sha256
                and source_path(asset, roots) == current and file_identity(current.stat()) == identity)
    except (OSError, ExportError): return False


def stage_asset(asset, roots, workspace, limits):
    if asset.bytes > limits.max_asset_bytes: raise ExportError('ASSET_LIMIT')
    path = source_path(asset, roots)
    try: before = file_identity(path.stat())
    except FileNotFoundError: raise ExportError('ASSET_MISSING') from None
    except OSError: raise ExportError('ASSET_UNREADABLE') from None
    if before[2] != asset.bytes: raise ExportError('SIZE_MISMATCH')
    staged, output = workspace.create('.asset')
    hasher, size = hashlib.sha256(), 0
    try:
        with output, path.open('rb') as source:
            handle_before = os.fstat(source.fileno())
            if file_identity(handle_before) != before:
                raise ExportError('SOURCE_CHANGED')
            while chunk := source.read(CHUNK):
                checkpoint()
                size += len(chunk)
                if size > asset.bytes or size > limits.max_asset_bytes:
                    raise ExportError('SOURCE_CHANGED')
                hasher.update(chunk)
                try: output.write(chunk)
                except OSError: raise ExportError('OUTPUT_WRITE_FAILED') from None
            try: output.flush(); os.fsync(output.fileno())
            except OSError: raise ExportError('OUTPUT_WRITE_FAILED') from None
            handle_after = os.fstat(source.fileno())
            if file_identity(handle_after) != before or handle_after.st_ctime_ns != handle_before.st_ctime_ns:
                raise ExportError('SOURCE_CHANGED')
        if size != asset.bytes: raise ExportError('SIZE_MISMATCH')
        if hasher.hexdigest() != asset.sha256: raise ExportError('HASH_MISMATCH')
        if not unchanged(asset, roots, path, before): raise ExportError('SOURCE_CHANGED')
        validate_image(staged, asset, limits)
        if not unchanged(asset, roots, path, before): raise ExportError('SOURCE_CHANGED')
        return {'staged': staged, 'source': path, 'identity': before}
    except ExportError: raise
    except OSError as exc:
        # An output write failure cannot be represented as missing source content.
        if exc.errno in {28, 122}: raise ExportError('OUTPUT_WRITE_FAILED') from None
        raise ExportError('ASSET_UNREADABLE') from None


def zip_info(name):
    safe_member(name)
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o444) << 16
    info.compress_type = zipfile.ZIP_STORED
    return info


def write_archive(workspace, snapshot, staged, failures):
    manifest, payloads = plan(snapshot, staged, failures)
    if sum(len(x) for x in payloads.values()) > META_LIMIT: raise ExportError('METADATA_LIMIT')
    target, stream = workspace.create('.zip')
    with stream:
        with zipfile.ZipFile(stream, 'w', allowZip64=True) as archive:
            names = set()
            for record in manifest['files']:
                checkpoint()
                name = safe_member(record['path'])
                if name.casefold() in names: raise ExportError('MEMBER_CONFLICT')
                names.add(name.casefold())
                with archive.open(zip_info(name), 'w', force_zip64=True) as member:
                    if name in payloads:
                        member.write(payloads[name])
                    else:
                        path = staged[record['asset_ids'][0]]['staged']
                        with path.open('rb') as source:
                            while chunk := source.read(CHUNK):
                                checkpoint()
                                member.write(chunk)
            if 'manifest.json' in names: raise ExportError('MEMBER_CONFLICT')
            archive.writestr(zip_info('manifest.json'), payloads['manifest.json'])
        stream.flush(); os.fsync(stream.fileno())
    return target, manifest


def verify_zip(path, snapshot, limits=Limits()):
    """Reopen and verify exact snapshot-derived members and streamed payload hashes.

    Existing immutable outputs are checked without relying on current source files.
    Their partial/succeeded result describes the original build, not present storage.
    """
    snapshot = capture_snapshot(snapshot)
    try:
        no_links(path)
        with zipfile.ZipFile(path, 'r') as archive:
            infos = archive.infolist()
            names = [safe_member(i.filename) for i in infos]
            if len({x.casefold() for x in names}) != len(names): raise ExportError('MEMBER_CONFLICT')
            if len(infos) > 12000 or any(i.flag_bits & 1 or i.compress_type != zipfile.ZIP_STORED
                    or i.create_system != 3 or i.external_attr != zip_info(i.filename).external_attr for i in infos):
                raise ExportError('ZIP_INVALID')
            root = archive.getinfo('manifest.json')
            if root.file_size > META_LIMIT: raise ExportError('METADATA_LIMIT')
            observed = json.loads(archive.read(root))
            if observed.get('snapshot_sha256') != snapshot.digest or observed.get('snapshot') != snapshot.model_dump(mode='json'):
                raise ExportError('SNAPSHOT_CONFLICT')
            expected, payloads = plan(snapshot, observed['verified_asset_ids'], observed['asset_failures'])
            if json_bytes(observed) != json_bytes(expected) or archive.read(root) != payloads['manifest.json']:
                raise ExportError('MANIFEST_MISMATCH')
            records = {r['path']: r for r in expected['files']}
            if set(names) != set(records) | {'manifest.json'}: raise ExportError('MEMBER_SET_MISMATCH')
            size_total = 0
            for name, record in records.items():
                info = archive.getinfo(name)
                if info.file_size != record['bytes']: raise ExportError('ZIP_HASH_MISMATCH')
                size_total += info.file_size
                if size_total > limits.max_total_bytes + META_LIMIT: raise ExportError('OUTPUT_LIMIT')
                digest, count = hashlib.sha256(), 0
                with archive.open(name) as member:
                    while data := member.read(CHUNK):
                        checkpoint()
                        digest.update(data); count += len(data)
                if digest.hexdigest() != record['sha256'] or count != record['bytes']:
                    raise ExportError('ZIP_HASH_MISMATCH')
                if name in payloads and hashlib.sha256(payloads[name]).hexdigest() != record['sha256']:
                    raise ExportError('MANIFEST_MISMATCH')
        return expected
    except ExportError: raise
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, RuntimeError):
        raise ExportError('ZIP_INVALID') from None


def package_result(path, snapshot, manifest, reused):
    with path.open('rb') as stream: digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return ExportResult(state=manifest['state'], snapshot_sha256=snapshot.digest, path=str(path),
        sha256=digest, bytes=path.stat().st_size, reused=reused,
        missing_count=manifest['missing_count'], unknown_count=manifest['unknown_count'])


def _export_zip(snapshot, roots, output_dir, limits=Limits()):
    """Publish once by export_id. Invalid/corrupt existing packages are never replaced.

    Caller owns the root mapping and job persistence. No real-time selection occurs.
    A valid same-snapshot existing package is verified and returned unchanged.
    To rebuild a partial output later, T5b may allocate a distinct controlled attempt
    output directory while retaining the exact snapshot/export_id. This function
    has no retry/lease API and never overwrites an earlier attempt's package.
    """
    workspace, digest = None, ''
    try:
        snapshot = capture_snapshot(snapshot); digest = snapshot.digest
        limits = Limits.model_validate(limits.model_dump())
        if sum(a.bytes for a in snapshot.assets) > limits.max_total_bytes:
            raise ExportError('SNAPSHOT_BYTES_LIMIT')
        output = Path(output_dir)
        if not output.is_absolute(): raise ExportError('INVALID_OUTPUT_ROOT')
        no_links(output)
        output.mkdir(parents=True, exist_ok=True)
        output = output.resolve(strict=True)
        roots = dict(roots)  # Detach caller mapping before any file reads.
        for key, root in roots.items():
            root = Path(root)
            if not root.is_absolute(): raise ExportError('INVALID_ROOT_MAP')
            no_links(root)
            roots[key] = root.resolve()
        name = 'export-' + hashlib.sha256(snapshot.export_id.encode()).hexdigest() + '.zip'
        final = output / name
        if final.exists() or final.is_symlink():
            manifest = verify_zip(final, snapshot, limits)
            return package_result(final, snapshot, manifest, True)
        # Reserve two copies plus metadata, including repetition across products.
        asset_map = {a.asset_id: a for a in snapshot.assets}
        repeated = sum(sum(asset_map[aid].bytes for aid in {i.asset_id for v in p.versions for i in v.images if i.asset_id}) for p in snapshot.products)
        if repeated > limits.max_total_bytes: raise ExportError('OUTPUT_LIMIT')
        needed = sum(a.bytes for a in snapshot.assets) + 2 * repeated + META_LIMIT + limits.min_free_bytes
        if shutil.disk_usage(output).free < needed: raise ExportError('DISK_RESERVE')
        workspace = Workspace(output)
        staged, failures = {}, {}
        for asset in snapshot.assets:
            checkpoint()
            try: staged[asset.asset_id] = stage_asset(asset, roots, workspace, limits)
            except ExportError as exc:
                from .manifest import FAILURES
                if exc.code not in FAILURES: raise
                failures[asset.asset_id] = exc.code
        # One bounded rebuild can exclude files changed while packaging. If new
        # changes keep occurring on the second pass, fail without publishing.
        for attempt in range(2):
            archive, manifest = write_archive(workspace, snapshot, staged, failures)
            verify_zip(archive, snapshot, limits)
            changed = [aid for aid, item in staged.items()
                       if not unchanged(asset_map[aid], roots, item['source'], item['identity'])]
            if not changed: break
            if attempt: raise ExportError('SOURCE_UNSTABLE')
            for aid in changed:
                del staged[aid]; failures[aid] = 'SOURCE_CHANGED'
        # A hard-link create is atomic and fails if the destination exists. Unlike
        # replace/rename on some platforms it cannot clobber a concurrently published ZIP.
        checkpoint()
        try: os.link(archive, final)
        except FileExistsError:
            manifest = verify_zip(final, snapshot, limits)
            return package_result(final, snapshot, manifest, True)
        return package_result(final, snapshot, manifest, False)
    except ExportError as exc:
        return ExportResult(state='failed', snapshot_sha256=digest, error_code=exc.code)
    except (ValueError, TypeError, AttributeError):
        return ExportResult(state='failed', snapshot_sha256=digest, error_code='INVALID_SNAPSHOT')
    except (OSError, zipfile.BadZipFile, RuntimeError):
        return ExportResult(state='failed', snapshot_sha256=digest, error_code='OUTPUT_WRITE_FAILED')
    finally:
        if workspace: workspace.cleanup()


def export_zip(snapshot, roots, output_dir, limits=Limits(), checkpoint=None):
    """Optional cooperative ownership/stop check; default retains the T5a contract."""
    token=_CHECKPOINT.set(checkpoint or (lambda: None))
    try:return _export_zip(snapshot,roots,output_dir,limits)
    finally:_CHECKPOINT.reset(token)
