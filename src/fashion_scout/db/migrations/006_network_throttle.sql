ALTER TABLE collection_http_results ADD COLUMN received_at REAL;
CREATE TABLE network_throttle (site_id TEXT PRIMARY KEY REFERENCES sites(id), not_before REAL, mode TEXT NOT NULL, request_seq INTEGER REFERENCES collection_http(seq), recorded_at REAL NOT NULL);
