ALTER TABLE archive_journal ADD COLUMN recovery_state TEXT NOT NULL DEFAULT 'active' CHECK(recovery_state IN('active','retryable','blocked','superseded'));
ALTER TABLE archive_journal ADD COLUMN generation INTEGER NOT NULL DEFAULT 0;
CREATE TABLE archive_journal_events (seq INTEGER PRIMARY KEY, journal_id TEXT NOT NULL REFERENCES archive_journal(id), epoch INTEGER NOT NULL, generation INTEGER NOT NULL, kind TEXT NOT NULL, code TEXT, detail_json TEXT NOT NULL, at TEXT NOT NULL);
