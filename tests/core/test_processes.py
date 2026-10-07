import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest

from fashion_scout.config import Paths
from fashion_scout.db import Database
from fashion_scout.domain import CreateRun, Lease, Outcome, ScoutError
from fashion_scout.launcher import read_descriptor, verified_process
from fashion_scout.processes import owned_process
from fashion_scout.services.runs import Runs

pytestmark = [pytest.mark.process, pytest.mark.skipif(os.name != "nt", reason="Windows process contract")]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def cli(paths, action, port=8765, expect=0):
    # This parent fully exits; service children must outlive its stdout pipe.
    proc = subprocess.run([sys.executable, "-m", "fashion_scout.launcher", action,
                          "--data-root", str(paths.root), "--port", str(port), "--json"],
                          capture_output=True, text=True, timeout=25, shell=False)
    assert proc.returncode == expect, (proc.stdout, proc.stderr)
    return json.loads(proc.stdout)


def wait_for(predicate, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for verified process/test state")


def test_exited_parent_idempotent_ensure_status_and_safe_stop(tmp_path):
    paths = Paths.at(tmp_path)
    port = free_port()
    try:
        first = cli(paths, "ensure", port)
        assert first["web_ready"] and first["worker_state"] == "online"
        assert first["resuming_run_ids"] == []
        recorded = read_descriptor(paths)
        original_ids = {k: v["pid"] for k, v in recorded["processes"].items()}
        # First subprocess.run parent has exited; another independent parent queries children.
        current = cli(paths, "status", port)
        assert current["web_ready"] and current["worker_state"] == "online"
        second = cli(paths, "ensure", port)
        assert second["app_instance_id"] == first["app_instance_id"]
        assert second["started_roles"] == []
        assert {k: v["pid"] for k, v in read_descriptor(paths)["processes"].items()} == original_ids
        token = (paths.root / "control" / (recorded["instance"] + ".key")).read_text("ascii")
        assert token not in json.dumps(recorded)
        assert token not in json.dumps(first)
        with Database(paths.db).read() as conn:
            assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
        assert cli(paths, "stop", port)["stopped"]
        for role in original_ids:
            assert verified_process(paths, recorded, role) is None
        assert not cli(paths, "status", port)["web_ready"]
    finally:
        if paths.root.exists():
            cli(paths, "stop", port)


def test_foreign_port_untouched(tmp_path):
    paths = Paths.at(tmp_path)
    port = free_port()
    foreign = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        def listening():
            with socket.socket() as sock:
                return sock.connect_ex(("127.0.0.1", port)) == 0
        wait_for(listening)
        result = cli(paths, "ensure", port, expect=1)
        assert result["error"]["code"] == "PORT_IN_USE"
        assert foreign.poll() is None
        assert read_descriptor(paths) is None
    finally:
        # Exact Popen object created by this test, never a discovered arbitrary PID.
        foreign.terminate()
        foreign.wait(timeout=5)


def test_live_descriptor_identity_mismatch_refuses_stop(tmp_path):
    paths = Paths.at(tmp_path)
    port = free_port()
    saved = None
    try:
        cli(paths, "ensure", port)
        saved = read_descriptor(paths)
        corrupted = json.loads(json.dumps(saved))
        corrupted["processes"]["worker"]["cmdline"][2] = "unrelated.module"
        target = paths.root / "control" / "runtime.json"
        target.write_text(json.dumps(corrupted), "utf-8")
        result = cli(paths, "stop", port, expect=1)
        assert result["error"]["code"] == "PROCESS_IDENTITY_CONFLICT"
        assert not (paths.root / "control" / (saved["instance"] + ".stop")).exists()
        assert owned_process(saved["processes"]["worker"]) is not None
    finally:
        if saved:
            (paths.root / "control" / "runtime.json").write_text(json.dumps(saved), "utf-8")
            cli(paths, "stop", port)


def test_kill_worker_restart_recovers_same_run_and_rejects_old_epoch(tmp_path):
    paths = Paths.at(tmp_path)
    paths.prepare()
    runs = Runs(Database(paths.db))
    runs.initialize()
    accepted = runs.create(CreateRun(request_key="kill-test", trigger="skill")).run
    with runs.db.write() as conn:
        legacy = accepted.snapshot.model_dump(mode="json")
        legacy["adapter_versions"]["futario"] = "not-implemented"
        conn.execute("UPDATE runs SET snapshot_json=? WHERE id=?", (json.dumps(legacy), accepted.id))
        conn.execute("INSERT INTO products(id,site_id,source_id,first_seen_at) VALUES ('p','futario','1','now')")
        conn.execute("INSERT INTO product_user_state(product_id,favorite,category_override) VALUES ('p',1,'manual')")
    helper = subprocess.Popen([sys.executable, str(Path(__file__).with_name("process_helper.py")), str(paths.root)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              creationflags=subprocess.CREATE_NO_WINDOW)
    port = free_port()
    try:
        marker = paths.root / "claimed.json"
        wait_for(marker.exists)
        claim = json.loads(marker.read_text("utf-8"))
        old = Lease.model_validate(claim["lease"])
        assert old.run_id == accepted.id
        actual = owned_process(claim["process"])
        assert actual is not None
        assert helper.pid == actual.pid or helper.pid in [p.pid for p in actual.parents()]
        actual.kill()  # Only our verified test executor at the deliberate boundary.
        actual.wait(timeout=5)
        helper.wait(timeout=5)
        started = cli(paths, "ensure", port)
        assert accepted.id in started["resuming_run_ids"]
        wait_for(lambda: runs.get(accepted.id).state == "failed")
        recovered = runs.get(accepted.id)
        assert recovered.id == accepted.id and recovered.epoch > old.epoch
        assert recovered.attempt == 2
        # Legacy adapter snapshots fail closed before any network, never silently reinterpret.
        assert recovered.issue_code == "ADAPTER_VERSION_MISMATCH"
        with pytest.raises(ScoutError) as error:
            runs.finish(old, Outcome(state="succeeded", valid_results=1, coverage_complete=True,
                                    required_complete=True, evidence_ref="obsolete-test-worker"))
        assert error.value.code == "STALE_LEASE"
        with runs.db.read() as conn:
            assert conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 1
            assert conn.execute("SELECT state,attempts FROM work_items").fetchone()[:] == ("completed", 1)
            assert conn.execute("SELECT favorite,category_override FROM product_user_state").fetchone()[:] == (1, "manual")
            assert conn.execute("SELECT COUNT(*) FROM run_events WHERE kind='recovered'").fetchone()[0] == 1
        assert paths.inside_media("originals/synthetic.bin").read_bytes() == b"test-only persisted asset"
    finally:
        (paths.root / "stop-test").touch()
        if helper.poll() is None:
            helper.wait(timeout=5)
        if read_descriptor(paths):
            cli(paths, "stop", port)


def test_readonly_status_does_not_initialize(tmp_path):
    root = tmp_path / "never-started"
    assert not root.exists()
    result = cli(Paths.at(root), "status")
    assert result["worker_state"] == "offline"
    assert not root.exists()


def test_interrupted_launcher_adopts_verified_handshake(tmp_path):
    paths = Paths.at(tmp_path)
    port = free_port()
    try:
        cli(paths, "ensure", port)
        saved = read_descriptor(paths)
        worker_pid = saved["processes"]["worker"]["pid"]
        saved["processes"].pop("worker")
        saved["starting_role"] = "worker"
        (paths.root / "control" / "runtime.json").write_text(json.dumps(saved), "utf-8")
        restored = cli(paths, "ensure", port)
        assert restored["started_roles"] == []
        assert read_descriptor(paths)["processes"]["worker"]["pid"] == worker_pid
    finally:
        cli(paths, "stop", port)


def test_interrupted_launcher_without_evidence_blocks_duplicate_spawn(tmp_path):
    import uuid
    paths = Paths.at(tmp_path)
    paths.prepare()
    saved = {"schema": 1, "instance": str(uuid.uuid4()), "data_root": str(paths.root),
             "port": free_port(), "processes": {}, "starting_role": "worker", "stopped": False}
    (paths.root / "control" / "runtime.json").write_text(json.dumps(saved), "utf-8")
    result = cli(paths, "ensure", saved["port"], expect=1)
    assert result["error"]["code"] == "STARTUP_RECOVERY_REQUIRED"
    assert not paths.db.exists()
