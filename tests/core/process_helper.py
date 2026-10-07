"""Explicit test-only executor. Never imported by production launcher."""
import hashlib
import json
import sys
import time
from pathlib import Path

from fashion_scout.config import Paths
from fashion_scout.db import Database
from fashion_scout.db.archive import Archive
from fashion_scout.domain import Outcome
from fashion_scout.processes import identity
from fashion_scout.services.runs import Runs
from fashion_scout.worker import Worker

paths = Paths.at(sys.argv[1])
runs = Runs(Database(paths.db))


def synthetic(context):
    # One real archived file completes before the deliberate process-kill boundary.
    item = context.runs.ensure_item(context.lease, "synthetic-archive")
    if context.runs.start_item(context.lease, item):
        content = b"test-only persisted asset"
        temp = paths.inside_media("temp/synthetic.bin")
        temp.parent.mkdir(parents=True, exist_ok=True)
        temp.write_bytes(content)
        journal = Archive(paths, context.runs)
        intent = journal.stage(context.lease, item, "temp/synthetic.bin", "originals/synthetic.bin",
                               hashlib.sha256(content).hexdigest(), len(content))
        journal.commit(context.lease, intent)
    (paths.root / "claimed.json").write_text(json.dumps({
        "lease": context.lease.model_dump(), "process": identity()}), "utf-8")
    while not (paths.root / "release-test").exists():
        context.checkpoint()
        time.sleep(0.02)
    return Outcome(state="succeeded", valid_results=1, coverage_complete=True,
                   required_complete=True, evidence_ref="synthetic-test-only")


Worker(paths, (paths.root / "stop-test").exists, executor=synthetic,
       heartbeat_seconds=0.15, lease_seconds=0.7, poll_seconds=0.05).run()
