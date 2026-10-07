-- Export-only persistent local jobs. Existing collection and user tables unchanged.
ALTER TABLE export_jobs ADD COLUMN roots_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE export_jobs ADD COLUMN snapshot_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE export_jobs ADD COLUMN created_at TEXT;
ALTER TABLE export_jobs ADD COLUMN finished_at TEXT;
ALTER TABLE export_jobs ADD COLUMN owner TEXT REFERENCES workers(id);
ALTER TABLE export_jobs ADD COLUMN epoch INTEGER NOT NULL DEFAULT 0;
ALTER TABLE export_jobs ADD COLUMN lease_until REAL;
ALTER TABLE export_jobs ADD COLUMN heartbeat_at REAL;
ALTER TABLE export_jobs ADD COLUMN attempt INTEGER NOT NULL DEFAULT 1;
ALTER TABLE export_jobs ADD COLUMN result_json TEXT;
ALTER TABLE export_jobs ADD COLUMN issue_code TEXT;
ALTER TABLE export_jobs ADD COLUMN resumed_at TEXT;
CREATE TABLE export_attempts (export_id TEXT NOT NULL REFERENCES export_jobs(id), number INTEGER NOT NULL, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, state TEXT NOT NULL, result_json TEXT, PRIMARY KEY(export_id,number));
CREATE TABLE export_requests (request_key TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, export_id TEXT NOT NULL REFERENCES export_jobs(id), action TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX export_queue ON export_jobs(state,created_at,id);
