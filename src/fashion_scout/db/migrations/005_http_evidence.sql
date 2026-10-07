CREATE TABLE collection_http_results (request_seq INTEGER PRIMARY KEY REFERENCES collection_http(seq), status INTEGER NOT NULL, retry_after TEXT, peer TEXT);
