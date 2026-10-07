-- Maintenance/storage only; existing migrations and collection semantics unchanged.
CREATE TABLE storage_preferences (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, media_root TEXT NOT NULL);
ALTER TABLE maintenance_jobs ADD COLUMN request_key TEXT;
ALTER TABLE maintenance_jobs ADD COLUMN created_at TEXT;
ALTER TABLE maintenance_jobs ADD COLUMN finished_at TEXT;
ALTER TABLE maintenance_jobs ADD COLUMN owner TEXT REFERENCES workers(id);
ALTER TABLE maintenance_jobs ADD COLUMN epoch INTEGER NOT NULL DEFAULT 0;
ALTER TABLE maintenance_jobs ADD COLUMN lease_until REAL;
ALTER TABLE maintenance_jobs ADD COLUMN heartbeat_at REAL;
ALTER TABLE maintenance_jobs ADD COLUMN result_json TEXT;
ALTER TABLE maintenance_jobs ADD COLUMN output_hash TEXT;
ALTER TABLE maintenance_jobs ADD COLUMN issue_code TEXT;
ALTER TABLE maintenance_jobs ADD COLUMN resumed_at TEXT;
CREATE TABLE maintenance_requests (request_key TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES maintenance_jobs(id));
CREATE TABLE maintenance_findings (object_id TEXT NOT NULL, code TEXT NOT NULL, category TEXT NOT NULL, last_job_id TEXT NOT NULL REFERENCES maintenance_jobs(id), checked_at TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(object_id,code));
CREATE TABLE restore_audit (id TEXT PRIMARY KEY, restored_at TEXT NOT NULL, backup_id TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, state TEXT NOT NULL, detail_json TEXT NOT NULL);
CREATE INDEX maintenance_queue ON maintenance_jobs(state,created_at,id);
