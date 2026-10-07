import hashlib
import platform
import sqlite3
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from fashion_scout.domain.errors import ScoutError


def environment_check():
    if platform.python_implementation() != "CPython" or sys.version_info[:2] != (3, 13) or sys.maxsize <= 2**32:
        raise ScoutError("ENVIRONMENT_INCOMPATIBLE", "Requires project CPython 3.13 x64", 503)
    if sqlite3.sqlite_version_info < (3, 51, 3):
        raise ScoutError("ENVIRONMENT_INCOMPATIBLE", "Requires SQLite >= 3.51.3 for WAL", 503)
    return {"python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version}


class Database:
    def __init__(self, path: Path, busy_ms: int = 5000, attempts: int = 3):
        if busy_ms < 0 or attempts < 1:
            raise ValueError("Database requires nonnegative busy timeout and at least one attempt")
        self.path = Path(path)
        self.busy_ms, self.attempts = busy_ms, attempts

    def connect(self):
        environment_check()
        conn = sqlite3.connect(self.path, timeout=self.busy_ms / 1000, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute(f"PRAGMA busy_timeout={int(self.busy_ms)}")
        return conn

    @contextmanager
    def read(self):
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def write(self):
        conn = self.connect()
        try:
            for attempt in range(self.attempts):
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    break
                except sqlite3.OperationalError as exc:
                    if getattr(exc, "sqlite_errorcode", None) not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                        raise
                    if attempt + 1 == self.attempts:
                        raise ScoutError("DATABASE_BUSY", "Database busy; retry this operation later", 503) from exc
                    time.sleep(0.02 * (attempt + 1))
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        finally:
            conn.close()

    def initialize(self):
        environment_check()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.read() as conn:
            mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if mode.lower() != "wal":
                raise ScoutError("WAL_UNAVAILABLE", "Local WAL mode could not be enabled", 503)
        with self.write() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, sha256 TEXT NOT NULL)")
            migrations = sorted((Path(__file__).parent / "migrations").glob("*.sql"))
            known = {int(p.name.split("_")[0]): p for p in migrations}
            if any(row[0] not in known for row in conn.execute("SELECT version FROM schema_migrations")):
                raise ScoutError("SCHEMA_TOO_NEW", "Database schema is newer than this runtime", 503)
            for version, path in known.items():
                sql = path.read_text("utf-8")
                digest = hashlib.sha256(sql.encode()).hexdigest()
                prior = conn.execute("SELECT sha256 FROM schema_migrations WHERE version=?", (version,)).fetchone()
                if prior:
                    if prior[0] != digest:
                        raise ScoutError("MIGRATION_CHANGED", "Applied migration checksum changed", 503)
                    continue
                statement = ""
                for line in sql.splitlines(keepends=True):
                    statement += line
                    if sqlite3.complete_statement(statement):
                        conn.execute(statement)
                        statement = ""
                if statement.strip():
                    raise ScoutError("INVALID_MIGRATION", "Incomplete SQL statement", 503)
                conn.execute("INSERT INTO schema_migrations VALUES (?,?)", (version, digest))
