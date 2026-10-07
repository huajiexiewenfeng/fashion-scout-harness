"""Bounded byte ingress. The API never accepts a filesystem path from the host."""
import ctypes
import hashlib
import json
import os
import re
import stat
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
import psutil
from fashion_scout.domain import ScoutError
from fashion_scout.services.browser_acquisition import BrowserAcquisition
from fashion_scout.services.runs import canonical, digest, new_id


def receiver_dead(row):
    try:
        return abs(psutil.Process(row["receiver_pid"]).create_time() - row["receiver_born"]) > .02
    except (psutil.NoSuchProcess, psutil.ZombieProcess, TypeError):
        return True
    except psutil.AccessDenied:
        return False


class BrowserIntake:
    def __init__(self, paths, runs):
        self.paths, self.runs = paths, runs
        self.source = BrowserAcquisition(runs)

    def path(self, relative):
        root = (self.paths.root / "browser-inbox").resolve()
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or path == root:
            raise ScoutError("SOURCE_BODY_PATH_INVALID", "Inbox path escaped its owned root")
        return path

    def begin(self, run_id, ticket_id, session_id, key, sha256, size, source_url):
        if (not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", key) or
                not re.fullmatch(r"[a-f0-9]{64}", sha256) or type(size) is not int or size <= 0):
            raise ScoutError("INVALID_PAYLOAD", "Bounded upload identity is required", 422)
        payload = {"run_id": run_id, "ticket_id": ticket_id, "session_id": session_id, "sha256": sha256, "bytes": size, "source_url": source_url}
        with self.runs.db.write() as conn:
            if conn.execute("SELECT 1 FROM browser_requests WHERE request_key=?", (key,)).fetchone():
                raise ScoutError("REQUEST_KEY_CONFLICT", "Source key was used for a different action")
            prior = conn.execute("SELECT * FROM browser_uploads WHERE request_key=?", (key,)).fetchone()
            if prior and prior["payload_hash"] != digest(payload):
                raise ScoutError("REQUEST_KEY_CONFLICT", "Upload key has different parameters")
            if prior and prior["state"] == "received":
                return {"receipt": json.loads(prior["response_json"])}
            _, view = self.source.session(conn, run_id, session_id, touch=True)
            ticket = conn.execute("SELECT * FROM browser_assets WHERE id=? AND run_id=?", (ticket_id, run_id)).fetchone()
            if not ticket:
                raise ScoutError("SOURCE_TICKET_NOT_FOUND", "Worker qualification must precede export", 404)
            if ticket["source_url"] != source_url:
                raise ScoutError("SOURCE_ASSET_URL_MISMATCH", "Export URL differs from the qualified gallery ticket", 422)
            if ticket["state"] == "uploading":
                if not receiver_dead(ticket):
                    raise ScoutError("SOURCE_UPLOAD_IN_PROGRESS", "Original upload is still owned by its receiver")
                conn.execute("UPDATE browser_uploads SET state='interrupted' WHERE request_key=? AND state='uploading'", (ticket["upload_key"],))
            elif ticket["state"] not in ("pending", "failed"):
                raise ScoutError("SOURCE_TICKET_BUSY", "Image was already received or archived")
            state = conn.execute("SELECT * FROM browser_runs WHERE run_id=?", (run_id,)).fetchone()
            cap = min(view.snapshot.storage.run_download_bytes, view.snapshot.browser.max_received_bytes)
            reserved = conn.execute("SELECT COALESCE(SUM(bytes),0) FROM browser_assets WHERE run_id=? AND state='uploading' AND id!=?", (run_id,ticket_id)).fetchone()[0]
            if size > view.snapshot.storage.max_image_bytes or state["received_bytes"] + reserved + size > cap:
                raise ScoutError("SOURCE_BYTE_BUDGET", "Frozen received-byte allowance would be exceeded", 413)
            if prior is None and state["selected_assets"] >= view.snapshot.browser.max_selected_assets:
                raise ScoutError("SOURCE_ASSET_BUDGET", "Frozen selected-export allowance reached")
            relative = run_id + "/" + ticket_id + "/" + new_id() + ".body"
            conn.execute("UPDATE browser_assets SET state='uploading',body_path=?,sha256=?,bytes=?,upload_key=?,receiver_pid=?,receiver_born=?,issue_code=NULL WHERE id=?",
                         (relative, sha256, size, key, os.getpid(), psutil.Process().create_time(), ticket_id))
            if prior is None:
                conn.execute("INSERT INTO browser_uploads VALUES (?,?,?,?,'uploading',NULL)", (key, run_id, ticket_id, digest(payload)))
                conn.execute("UPDATE browser_runs SET selected_assets=selected_assets+1 WHERE run_id=?", (run_id,))
            else:
                conn.execute("UPDATE browser_uploads SET state='uploading' WHERE request_key=?", (key,))
        return {"run_id": run_id, "ticket_id": ticket_id, "session_id": session_id,
                "key": key, "relative": relative, "sha256": sha256, "bytes": size}

    def charge(self, transfer, size):
        with self.runs.db.write() as conn:
            _, view = self.source.session(conn, transfer["run_id"], transfer["session_id"], touch=True)
            ticket = conn.execute("SELECT upload_key,state,body_path FROM browser_assets WHERE id=?", (transfer["ticket_id"],)).fetchone()
            if not ticket or tuple(ticket) != (transfer["key"], "uploading", transfer["relative"]):
                raise ScoutError("STALE_SOURCE_UPLOAD", "Upload ownership changed")
            row = conn.execute("SELECT received_bytes FROM browser_runs WHERE run_id=?", (transfer["run_id"],)).fetchone()
            conn.execute("UPDATE browser_runs SET received_bytes=received_bytes+? WHERE run_id=?", (size, transfer["run_id"]))
            conn.execute("UPDATE collection_runs SET downloaded_bytes=downloaded_bytes+? WHERE run_id=?", (size, transfer["run_id"]))
        # Account actual received chunks even when the final chunk violates the cap.
        if row[0] + size > min(view.snapshot.storage.run_download_bytes, view.snapshot.browser.max_received_bytes):
            raise ScoutError("SOURCE_BYTE_BUDGET", "Received-byte allowance reached", 413)

    def complete(self, transfer):
        result = {"ticket_id": transfer["ticket_id"], "state": "received", "sha256": transfer["sha256"], "bytes": transfer["bytes"]}
        with self.runs.db.write() as conn:
            self.source.session(conn, transfer["run_id"], transfer["session_id"], touch=True)
            changed = conn.execute("UPDATE browser_assets SET state='received',receiver_pid=NULL,receiver_born=NULL WHERE id=? AND upload_key=? AND state='uploading' AND body_path=?",
                                   (transfer["ticket_id"], transfer["key"], transfer["relative"])).rowcount
            if not changed:
                raise ScoutError("STALE_SOURCE_UPLOAD", "Upload ownership changed")
            conn.execute("UPDATE browser_uploads SET state='received',response_json=? WHERE request_key=?", (canonical(result), transfer["key"]))
        return result

    def abort(self, transfer, code):
        with self.runs.db.write() as conn:
            conn.execute("UPDATE browser_assets SET state='failed',issue_code=?,receiver_pid=NULL,receiver_born=NULL WHERE id=? AND upload_key=? AND state='uploading' AND body_path=?",
                         (code, transfer["ticket_id"], transfer["key"], transfer["relative"]))
            conn.execute("UPDATE browser_uploads SET state='interrupted' WHERE request_key=? AND state='uploading'", (transfer["key"],))
        # Retain only the bounded owned partial file for diagnosis/recovery, never publish it.

    async def receive(self, request, transfer):
        if "receipt" in transfer:
            return transfer["receipt"]
        path = self.path(transfer["relative"])
        path.parent.mkdir(parents=True, exist_ok=True)
        hasher, received = hashlib.sha256(), 0
        try:
            with path.open("xb") as stream:
                async for chunk in request.stream():
                    if not chunk:
                        continue
                    received += len(chunk)
                    self.charge(transfer, len(chunk))
                    if received > transfer["bytes"]:
                        raise ScoutError("SOURCE_BODY_TOO_LARGE", "Upload exceeded its declared length", 413)
                    hasher.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if received != transfer["bytes"] or hasher.hexdigest() != transfer["sha256"]:
                raise ScoutError("SOURCE_BODY_HASH_MISMATCH", "Upload bytes do not match the frozen manifest", 422)
            return self.complete(transfer)
        except BaseException:
            self.abort(transfer, "SOURCE_UPLOAD_INTERRUPTED")
            raise




@contextmanager
def stable_read(path):
    if os.name == 'nt':
        import msvcrt
        from ctypes import wintypes
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.CreateFileW.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,
                                   wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        api.CreateFileW.restype = wintypes.HANDLE
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        # FILE_SHARE_READ excludes concurrent write/delete; OPEN_REPARSE_POINT
        # lets the handle attribute check reject a substituted link.
        handle = api.CreateFileW(str(path),0x80000000,1,None,3,0x00200000,None)
        if handle == ctypes.c_void_p(-1).value:
            raise ScoutError('NATIVE_EXPORT_UNREADABLE','Native export could not be opened read-only')
        try:
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            api.CloseHandle(handle)
            raise
        stream = os.fdopen(fd,'rb')
    else:
        fd = os.open(path, os.O_RDONLY | getattr(os,'O_NOFOLLOW',0))
        stream = os.fdopen(fd,'rb')
    with stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or getattr(info,'st_file_attributes',0) & 0x400:
            raise ScoutError('NATIVE_EXPORT_INVALID','Native export must be a regular file')
        yield stream, info


def native_base():
    return (Path(tempfile.gettempdir()) / 'browser-use' / 'assets').resolve()


def normal_member(raw, directory):
    candidate=Path(raw)
    if not candidate.is_absolute() or '..' in candidate.parts or any(':' in p for p in candidate.parts[1:]):
        raise ScoutError('NATIVE_EXPORT_ROOT_INVALID','Native member path must be ordinary and absolute')
    resolved=candidate.resolve(strict=True)
    if not resolved.is_relative_to(directory) or resolved==directory:
        raise ScoutError('NATIVE_EXPORT_ROOT_INVALID','Native member escaped its export directory')
    for current in (candidate,*candidate.parents):
        info=current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
            raise ScoutError('NATIVE_EXPORT_ROOT_INVALID','Native member cannot pass through a link')
        if current.resolve()==directory:break
    return candidate


@contextmanager
def selected_export(payload):
    directory = Path(payload['native_directory']).resolve(strict=True)
    if directory.parent != native_base() or str(uuid.UUID(directory.name)) != directory.name:
        raise ScoutError('NATIVE_EXPORT_ROOT_INVALID','Only a native pageAssets export directory is allowed')
    manifest = normal_member(payload['manifest_path'],directory)
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate key')
            result[key]=value
        return result
    with stable_read(manifest) as (incoming, info):
        if info.st_size > 1024**2:
            raise ScoutError('NATIVE_EXPORT_INVALID','Manifest exceeds the bounded metadata allowance')
        value=json.loads(incoming.read(1024**2 + 1),object_pairs_hook=pairs)
    entries=value.get('assets',[]) if isinstance(value,dict) else []
    selected=[entry for entry in entries if isinstance(entry,dict) and entry.get('id') == payload['asset_id']]
    if len(selected)!=1 or len(entries)>2400:
        raise ScoutError('NATIVE_EXPORT_INVALID','Selected asset identity is absent or ambiguous')
    entry=selected[0]
    if entry.get('url') != payload['source_url'] or entry.get('kind') not in (None,'image'):
        raise ScoutError('NATIVE_EXPORT_URL_MISMATCH','Selected asset differs from the observed gallery URL')
    path=normal_member(entry['path'],directory)
    with stable_read(path) as (stream, info):
        if info.st_size != payload['bytes'] or info.st_size > 25 * 1024**2:
            raise ScoutError('NATIVE_EXPORT_SIZE_MISMATCH','Selected file size differs from the manifest receipt')
        if hashlib.file_digest(stream,'sha256').hexdigest() != payload['sha256']:
            raise ScoutError('NATIVE_EXPORT_HASH_MISMATCH','Selected file hash differs from the receipt')
        stream.seek(0)
        yield stream
