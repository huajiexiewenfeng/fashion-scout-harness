import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .domain.errors import ScoutError


def stored_media(root):
    db=root/'scout.sqlite3'
    if not db.exists():return None
    conn=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=5)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='storage_preferences'").fetchone():return None
        row=conn.execute('SELECT media_root FROM storage_preferences WHERE id=1').fetchone()
        return Path(row[0]) if row else None
    finally:conn.close()


@dataclass(frozen=True)
class Paths:
    root: Path
    _media: Path
    _fixed: bool = False

    @property
    def media(self):
        return self._media if self._fixed else stored_media(self.root) or self._media

    def freeze_media(self):
        return Paths(self.root,self.media,True)

    def for_run(self,run_id):
        # Completed/retryable journals pin explicit old-Run repairs to their root.
        conn=sqlite3.connect(self.db)
        try:
            rows=conn.execute('SELECT DISTINCT s.path FROM archive_journal j JOIN storage_roots s ON s.id=j.root_id WHERE j.run_id=?',(run_id,)).fetchall()
            if len(rows)>1:return self.freeze_media()  # Archive rejects ambiguity before journal file IO.
            return Paths(self.root,Path(rows[0][0]) if rows else self.media,True)
        finally:conn.close()

    @classmethod
    def at(cls, root: str | Path | None = None):
        path = Path(root) if root else Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FashionScout"
        if not path.is_absolute():
            raise ScoutError("INVALID_ROOT", "Data root must be absolute", 422)
        path = path.resolve()
        # Once present, the DB authority wins; stale app.json is not dual-written.
        config = path / "app.json"
        media = stored_media(path)
        if media is None:media = Path(json.loads(config.read_text("utf-8"))["media_root"]) if config.exists() else path / "media"
        if not media.is_absolute():
            raise ScoutError("INVALID_ROOT", "Media root must be absolute", 422)
        return cls(path, media.resolve())

    @property
    def db(self):
        return self.root / "scout.sqlite3"

    def prepare(self):
        for path in (self.root, self.media, self.root / "logs", self.root / "control"):
            path.mkdir(parents=True, exist_ok=True)

    def inside_media(self, relative: str) -> Path:
        candidate = (self.media / relative).resolve()
        if Path(relative).is_absolute() or not candidate.is_relative_to(self.media) or candidate == self.media:
            raise ScoutError("INVALID_PATH", "Asset path must stay inside media root", 422)
        return candidate
