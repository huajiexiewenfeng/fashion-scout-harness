CREATE TABLE browser_runs (
 run_id TEXT PRIMARY KEY REFERENCES runs(id), phase TEXT NOT NULL DEFAULT 'waiting_host',
 received_bytes INTEGER NOT NULL DEFAULT 0, selected_assets INTEGER NOT NULL DEFAULT 0,
 observations INTEGER NOT NULL DEFAULT 0, last_activity REAL NOT NULL,
 finish_received INTEGER NOT NULL DEFAULT 0, source_wait INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE browser_sessions (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), run_epoch INTEGER NOT NULL,
 state TEXT NOT NULL, created_at REAL NOT NULL, last_activity REAL NOT NULL,
 adapter_version TEXT NOT NULL
);
CREATE UNIQUE INDEX browser_live_session ON browser_sessions(run_id) WHERE state='active';
CREATE TABLE browser_requests (
 request_key TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
 payload_hash TEXT NOT NULL, response_json TEXT NOT NULL
);
CREATE TABLE browser_messages (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), session_id TEXT NOT NULL REFERENCES browser_sessions(id),
 sequence INTEGER NOT NULL, observation_json TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
 issue_code TEXT, UNIQUE(run_id,sequence)
);
CREATE TABLE browser_assets (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
 product_id TEXT NOT NULL REFERENCES products(id), source_image_id TEXT NOT NULL,
 item_id TEXT NOT NULL REFERENCES work_items(id), source_url TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending', body_path TEXT, sha256 TEXT, bytes INTEGER,
 upload_key TEXT, receiver_pid INTEGER, receiver_born REAL, issue_code TEXT,
 UNIQUE(run_id,product_id,source_image_id)
);
CREATE TABLE browser_uploads (
 request_key TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), ticket_id TEXT NOT NULL REFERENCES browser_assets(id),
 payload_hash TEXT NOT NULL, state TEXT NOT NULL, response_json TEXT
);
