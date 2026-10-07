CREATE TABLE settings (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, plan_json TEXT NOT NULL);
CREATE TABLE sites (id TEXT PRIMARY KEY, entry TEXT NOT NULL, adapter_version TEXT NOT NULL, enabled INTEGER NOT NULL CHECK(enabled IN(0,1)), baseline_complete INTEGER NOT NULL DEFAULT 0);
CREATE TABLE runs (
 id TEXT PRIMARY KEY, state TEXT NOT NULL CHECK(state IN('queued','running','interrupted','cancelling','cancelled','succeeded','partial','failed')),
 snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, resumed_at TEXT,
 epoch INTEGER NOT NULL DEFAULT 0, owner TEXT, lease_until REAL, heartbeat_at REAL,
 attempt INTEGER NOT NULL DEFAULT 1, cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN(0,1)),
 issue_code TEXT, valid_results INTEGER NOT NULL DEFAULT 0, outcome_json TEXT
);
CREATE UNIQUE INDEX one_active_run ON runs((1)) WHERE state IN('queued','running','interrupted','cancelling');
CREATE TABLE run_requests (request_key TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES runs(id), response_json TEXT NOT NULL);
CREATE TABLE run_attempts (run_id TEXT NOT NULL REFERENCES runs(id), number INTEGER NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, result_state TEXT, reason TEXT, PRIMARY KEY(run_id,number));
CREATE TABLE operation_requests (key TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES runs(id));
CREATE TABLE run_events (seq INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), kind TEXT NOT NULL, at TEXT NOT NULL, epoch INTEGER NOT NULL, detail TEXT NOT NULL);
CREATE TABLE workers (id TEXT PRIMARY KEY, pid INTEGER NOT NULL, born REAL NOT NULL, executable TEXT NOT NULL, heartbeat_at REAL NOT NULL, state TEXT NOT NULL);
CREATE TABLE work_items (id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), item_key TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN('pending','running','completed','failed','cancelled')), attempts INTEGER NOT NULL DEFAULT 0, output_json TEXT, error_code TEXT, UNIQUE(run_id,item_key));
CREATE TABLE work_attempts (item_id TEXT NOT NULL REFERENCES work_items(id), number INTEGER NOT NULL, epoch INTEGER NOT NULL, state TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY(item_id,number));
CREATE TABLE storage_roots (id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, purpose TEXT NOT NULL);
CREATE TABLE archive_journal (id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), item_id TEXT NOT NULL REFERENCES work_items(id), epoch INTEGER NOT NULL, root_id TEXT NOT NULL REFERENCES storage_roots(id), temp_path TEXT NOT NULL, final_path TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN('staged','committed','failed')), error_code TEXT, UNIQUE(run_id,item_id,sha256));
