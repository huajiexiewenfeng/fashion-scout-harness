CREATE TABLE owned_temps (
    root_id TEXT NOT NULL REFERENCES storage_roots(id),
    relative_path TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(id),
    item_id TEXT NOT NULL REFERENCES work_items(id),
    epoch INTEGER NOT NULL,
    file_device TEXT,
    file_inode TEXT,
    state TEXT NOT NULL CHECK (state IN ('allocated','ready','removed','retained')),
    error_code TEXT,
    PRIMARY KEY(root_id,relative_path)
);
CREATE INDEX owned_temps_run ON owned_temps(run_id,state);
