"""T1 byte-level archive journal; T2 must validate images before staging bytes."""
import hashlib
import os

from fashion_scout.config import Paths
from fashion_scout.domain import Lease, ScoutError
from fashion_scout.services.runs import Runs, canonical, new_id, timestamp


class Archive:
    def __init__(self, paths: Paths, runs: Runs):
        self.paths, self.runs = paths.freeze_media(), runs
        self.root_id = hashlib.sha256(str(self.paths.media).encode()).hexdigest()
        with runs.db.write() as conn:
            conn.execute('INSERT OR IGNORE INTO storage_preferences VALUES (1,1,?)',(str(Paths.at(paths.root).media),))
            existing=conn.execute('SELECT id FROM storage_roots WHERE path=?',(str(self.paths.media),)).fetchone()
            if existing:self.root_id=existing['id']
            conn.execute("INSERT OR IGNORE INTO storage_roots VALUES (?,?,'media')", (self.root_id, str(self.paths.media)))

    def create_temp(self, lease, item_id):
        relative = f"temp/{lease.run_id}/{lease.epoch}/{new_id()}.part"
        path = self.paths.inside_media(relative)
        with self.runs.db.write() as conn:
            self.runs.fence(conn, lease)
            conn.execute("INSERT INTO owned_temps(root_id,relative_path,run_id,item_id,epoch,state) VALUES (?,?,?,?,?,'allocated')",
                         (self.root_id, relative, lease.run_id, item_id, lease.epoch))
        # Persist intent before creating bytes. An allocation interrupted before
        # identity capture is retained for review, never guessed to be ours.
        with self.runs.db.write() as conn:
            self.runs.fence(conn, lease)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stat = os.fstat(stream.fileno())
            conn.execute("UPDATE owned_temps SET file_device=?,file_inode=?,state='ready' WHERE root_id=? AND relative_path=?",
                         (str(stat.st_dev), str(stat.st_ino), self.root_id, relative))
        return relative

    def _temp_path(self, relative):
        path = self.paths.inside_media(relative)
        if not path.is_relative_to(self.paths.media / "temp"):
            raise ScoutError("INVALID_TEMP_PATH", "Cleanup is confined to the media temp directory")
        return path

    def _referenced_temp(self, conn, relative, except_journal=None):
        return conn.execute("SELECT 1 FROM assets WHERE root_id=? AND relative_path=?", (self.root_id, relative)).fetchone() or conn.execute(
            "SELECT 1 FROM archive_journal WHERE root_id=? AND temp_path=? AND id!=? AND state!='committed' AND recovery_state IN ('active','blocked')",
            (self.root_id, relative, except_journal or "")).fetchone()

    def cleanup_temp(self, lease, relative):
        # Keep fence, identity check and unlink under the same SQLite write lock:
        # a replacement lease/journal cannot appear between validation and delete.
        with self.runs.db.write() as conn:
            self.runs.fence(conn, lease)
            row = conn.execute("SELECT * FROM owned_temps WHERE root_id=? AND relative_path=? AND run_id=?", (self.root_id, relative, lease.run_id)).fetchone()
            if not row or row["state"] == "removed" or row["epoch"] > lease.epoch:
                return
            if self._referenced_temp(conn, relative):
                return
            error = None
            try:
                path = self._temp_path(relative)
                if path.exists():
                    stat = path.stat()
                    if not stat.st_ino or (str(stat.st_dev), str(stat.st_ino)) != (row["file_device"], row["file_inode"]):
                        error = "TEMP_IDENTITY_CHANGED"
                    else:
                        path.unlink()
            except (OSError, ScoutError):
                error = "TEMP_CLEANUP_REVIEW_REQUIRED"
            conn.execute("UPDATE owned_temps SET state=?,error_code=? WHERE root_id=? AND relative_path=?",
                         ("retained" if error else "removed", error, self.root_id, relative))

    def cleanup_committed(self, lease, journal_id):
        with self.runs.db.read() as conn:
            self.runs.fence(conn, lease)
            row = conn.execute("SELECT * FROM archive_journal WHERE id=? AND run_id=? AND state='committed'", (journal_id, lease.run_id)).fetchone()
            if not row or row["root_id"] != self.root_id:
                return
            row = dict(row)
            tracked = conn.execute("SELECT 1 FROM owned_temps WHERE root_id=? AND relative_path=?", (self.root_id, row["temp_path"])).fetchone()
        if tracked:
            self.cleanup_temp(lease, row["temp_path"])
            return
        # Compatibility for pre-007 intents: validate the journal bytes, then
        # recheck file identity and journal generation while fenced before unlink.
        try:
            path = self._temp_path(row["temp_path"])
            if not path.exists():
                return
            stat = path.stat()
            self.verify(path, row["sha256"], row["bytes"])
            with self.runs.db.write() as conn:
                self.runs.fence(conn, lease)
                current = conn.execute("SELECT * FROM archive_journal WHERE id=?", (journal_id,)).fetchone()
                if current["generation"] != row["generation"] or current["state"] != "committed" or current["temp_path"] != row["temp_path"]:
                    return
                if self._referenced_temp(conn, row["temp_path"], journal_id):
                    return
                now = path.stat()
                if stat.st_ino and (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns) == (now.st_dev, now.st_ino, now.st_size, now.st_mtime_ns):
                    path.unlink()
        except OSError:
            return  # Retain bounded journal-owned bytes for next recovery/review.
        except ScoutError as exc:
            if exc.code in {"STALE_LEASE", "DATABASE_BUSY"}:
                raise

    @staticmethod
    def verify(path, expected_hash: str, size: int):
        if not path.is_file() or path.stat().st_size != size:
            raise ScoutError("ARCHIVE_MISSING_OR_CHANGED", "Archive bytes do not match the journal")
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected_hash:
            raise ScoutError("ARCHIVE_HASH_MISMATCH", "Archive hash differs from staged bytes")

    def stage(self, lease: Lease, item_id: str, temp_path: str, final_path: str, sha256: str, size: int) -> str:
        temp, final = self.paths.inside_media(temp_path), self.paths.inside_media(final_path)
        if temp == final or size < 0 or len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            raise ScoutError("INVALID_JOURNAL", "Invalid staging paths, hash or size", 422)
        self.verify(temp, sha256, size)
        with self.runs.db.write() as conn:
            self.runs.fence(conn, lease)
            item = conn.execute("SELECT state FROM work_items WHERE id=? AND run_id=?", (item_id, lease.run_id)).fetchone()
            if not item or item["state"] != "running":
                raise ScoutError("ITEM_NOT_ACTIVE", "Archive requires a running work item")
            prior = list(conn.execute("SELECT * FROM archive_journal WHERE run_id=? AND item_id=? AND recovery_state!='superseded'", (lease.run_id, item_id)))
            for old in prior:
                same = (old["temp_path"], old["final_path"], old["sha256"], old["bytes"]) == (temp_path, final_path, sha256, size)
                if old["recovery_state"] == "active" and same:
                    return old["id"]
                if old["root_id"] != self.root_id or old["recovery_state"] != "retryable":
                    raise ScoutError("JOURNAL_CONFLICT", "Existing intent must be recovered before replacement")
                # Retryable means unpublished bytes only. Never replace a published target.
                if self.paths.inside_media(old["final_path"]).exists() or conn.execute("SELECT 1 FROM assets WHERE journal_id=?", (old["id"],)).fetchone():
                    raise ScoutError("ARCHIVE_TARGET_CONFLICT", "Published intent requires reconciliation")
                self._event(conn, lease, old, "superseded", old["error_code"], dict(old))
                conn.execute("UPDATE archive_journal SET recovery_state='superseded' WHERE id=?", (old["id"],))
            existing = conn.execute("SELECT * FROM archive_journal WHERE run_id=? AND item_id=? AND sha256=?", (lease.run_id, item_id, sha256)).fetchone()
            if existing:
                # Preserve the unique logical journal, append immutable history, advance generation.
                if existing["recovery_state"] != "superseded":
                    raise ScoutError("JOURNAL_CONFLICT", "Existing archive intent differs")
                conn.execute("UPDATE archive_journal SET epoch=?,temp_path=?,final_path=?,bytes=?,state='staged',error_code=NULL,recovery_state='active',generation=generation+1 WHERE id=?", (lease.epoch, temp_path, final_path, size, existing["id"]))
                updated = conn.execute("SELECT * FROM archive_journal WHERE id=?", (existing["id"],)).fetchone()
                self._event(conn, lease, updated, "restaged", None, {"temp_path": temp_path, "final_path": final_path})
                return existing["id"]
            journal_id = new_id()
            conn.execute("INSERT INTO archive_journal(id,run_id,item_id,epoch,root_id,temp_path,final_path,sha256,bytes,state) VALUES (?,?,?,?,?,?,?,?,?,'staged')",
                         (journal_id, lease.run_id, item_id, lease.epoch, self.root_id, temp_path, final_path, sha256, size))
            return journal_id

    def _event(self, conn, lease, row, kind, code, detail):
        conn.execute("INSERT INTO archive_journal_events(journal_id,epoch,generation,kind,code,detail_json,at) VALUES (?,?,?,?,?,?,?)", (row["id"], lease.epoch, row["generation"], kind, code, canonical(detail), timestamp(self.runs.clock())))

    def commit(self, lease: Lease, journal_id: str) -> str:
        with self.runs.db.read() as conn:
            self.runs.fence(conn, lease)
            row = conn.execute("SELECT * FROM archive_journal WHERE id=? AND run_id=?", (journal_id, lease.run_id)).fetchone()
            if not row:
                raise ScoutError("JOURNAL_NOT_FOUND", "Journal does not exist")
            if row["root_id"] != self.root_id:
                raise ScoutError("ARCHIVE_ROOT_MISMATCH", "Journal is not in the configured root")
            if row["recovery_state"] == "superseded":
                raise ScoutError("JOURNAL_SUPERSEDED", "Journal was superseded by a repair")
            row = dict(row)
        if not self.paths.media.is_dir():
            raise ScoutError("ARCHIVE_ROOT_UNAVAILABLE", "Configured media root is unavailable")
        temp, final = self.paths.inside_media(row["temp_path"]), self.paths.inside_media(row["final_path"])
        # Immutable publish: never replace an existing destination. Crash after link is recoverable.
        if not final.exists():
            if row["state"] == "committed":
                raise ScoutError("ARCHIVE_TARGET_CONFLICT", "Committed target is missing; preserve asset evidence")
            try:
                self.verify(temp, row["sha256"], row["bytes"])
            except ScoutError as exc:
                raise ScoutError("ARCHIVE_STAGING_UNAVAILABLE", "Unpublished staging bytes require refetch") from exc
            with temp.open("r+b") as stream:
                os.fsync(stream.fileno())
            final.parent.mkdir(parents=True, exist_ok=True)
            if not final.parent.resolve().is_relative_to(self.paths.media):
                raise ScoutError("INVALID_PATH", "Archive parent escaped media root")
            try:
                os.link(temp, final)
            except FileExistsError:
                pass
        try:
            self.verify(final, row["sha256"], row["bytes"])
        except ScoutError as exc:
            raise ScoutError("ARCHIVE_TARGET_CONFLICT", "Immutable target differs; do not overwrite") from exc
        with self.runs.db.write() as conn:
            self.runs.fence(conn, lease)  # IO above grants no state-write authority.
            current = conn.execute("SELECT * FROM archive_journal WHERE id=?", (journal_id,)).fetchone()
            if current["generation"] != row["generation"] or current["recovery_state"] == "superseded":
                raise ScoutError("JOURNAL_CHANGED", "Journal changed during publication")
            existing = conn.execute("SELECT * FROM assets WHERE root_id=? AND relative_path=?", (self.root_id, row["final_path"])).fetchone()
            if existing and (existing["sha256"], existing["bytes"]) != (row["sha256"], row["bytes"]):
                raise ScoutError("ASSET_CONFLICT", "Immutable asset metadata differs")
            asset_id = existing["id"] if existing else new_id()
            if not existing:
                conn.execute("INSERT INTO assets(id,root_id,relative_path,sha256,bytes,state,verified_at,journal_id) VALUES (?,?,?,?,?,'verified',?,?)",
                             (asset_id, self.root_id, row["final_path"], row["sha256"], row["bytes"], timestamp(self.runs.clock()), journal_id))
            self.runs._complete_item(conn, lease, row["item_id"], {"asset_id": asset_id})
            if current["state"] != "committed":
                self._event(conn, lease, current, "committed", None, {"asset_id": asset_id})
            conn.execute("UPDATE archive_journal SET state='committed',error_code=NULL,recovery_state='active' WHERE id=?", (journal_id,))
        self.cleanup_committed(lease, journal_id)
        return asset_id

    def recover(self, lease: Lease) -> dict:
        with self.runs.db.read() as conn:
            self.runs.fence(conn, lease)
            rows = list(conn.execute("SELECT * FROM archive_journal WHERE run_id=? AND state!='committed' AND recovery_state!='superseded'", (lease.run_id,)))
            ambiguous = conn.execute('SELECT COUNT(DISTINCT root_id) FROM archive_journal WHERE run_id=?',(lease.run_id,)).fetchone()[0] > 1
        if ambiguous and not rows:
            raise ScoutError('ARCHIVE_RECOVERY_REQUIRED','历史任务含多个素材根，未选择或移动文件')
        recovered, failures, retryable, blocked, fatal = [], [], [], [], []
        for row in rows:
            try:
                if ambiguous:
                    raise ScoutError('ARCHIVE_ROOT_MISMATCH','历史任务含多个素材根，未选择或移动文件')
                self.commit(lease, row["id"])
                recovered.append(row["id"])
            except (ScoutError, OSError) as exc:
                code = exc.code if isinstance(exc, ScoutError) else "ARCHIVE_IO_ERROR"
                if code in ("STALE_LEASE", "DATABASE_BUSY", "JOURNAL_CHANGED", "JOURNAL_SUPERSEDED"):
                    raise
                kind = "retryable" if code == "ARCHIVE_STAGING_UNAVAILABLE" else "blocked"
                scope = "item" if code in ("ARCHIVE_STAGING_UNAVAILABLE", "ARCHIVE_TARGET_CONFLICT", "ASSET_CONFLICT") else "run"
                with self.runs.db.write() as conn:
                    self.runs.fence(conn, lease)
                    current = conn.execute("SELECT * FROM archive_journal WHERE id=?", (row["id"],)).fetchone()
                    if current["generation"] != row["generation"] or current["recovery_state"] == "superseded":
                        raise ScoutError("JOURNAL_CHANGED", "Journal changed during recovery")
                    if (current["state"], current["recovery_state"], current["error_code"]) != ("failed", kind, code):
                        self._event(conn, lease, current, kind, code, {"scope": scope, "temp_path": row["temp_path"], "final_path": row["final_path"], "prior_state": current["state"], "prior_error_code": current["error_code"]})
                    conn.execute("UPDATE archive_journal SET state='failed',recovery_state=?,error_code=? WHERE id=?", (kind, code, row["id"]))
                    conn.execute("UPDATE work_attempts SET state='failed' WHERE item_id=? AND state='running'", (row["item_id"],))
                    conn.execute("UPDATE work_items SET state=?,error_code=? WHERE id=? AND state!='completed'", ("pending" if kind == "retryable" else "failed", code, row["item_id"]))
                failure = {"journal_id": row["id"], "item_id": row["item_id"], "code": code,
                           "scope": scope, "action": "refetch" if kind == "retryable" else "reconcile",
                           "evidence_ref": "archive_journal:" + row["id"]}
                failures.append(failure)
                (retryable if kind == "retryable" else blocked).append(failure)
                if scope == "run":
                    fatal.append(failure)
        if ambiguous:
            return {"recovered": recovered, "failures": failures, "retryable": retryable,
                    "blocked": blocked, "fatal_failures": fatal}
        with self.runs.db.read() as conn:
            self.runs.fence(conn, lease)
            committed = [r[0] for r in conn.execute("SELECT id FROM archive_journal WHERE run_id=? AND state='committed'", (lease.run_id,))]
            temps = [r[0] for r in conn.execute("SELECT relative_path FROM owned_temps WHERE root_id=? AND run_id=? AND state!='removed'", (self.root_id, lease.run_id))]
        for journal_id in committed:
            self.cleanup_committed(lease, journal_id)
        for relative in temps:
            self.cleanup_temp(lease, relative)
        return {"recovered": recovered, "failures": failures, "retryable": retryable,
                "blocked": blocked, "fatal_failures": fatal}
