"""Idempotent local launcher. Only verified project processes can be stopped."""
import argparse
import hashlib
import hmac
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, ProxyHandler, build_opener

import psutil

from .config import Paths
from .db import Database, environment_check
from .domain import ScoutError
from .processes import identity, owned_process
from .services.runs import Runs


def atomic_json(path: Path, value):
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def launcher_lock(paths: Paths):
    import msvcrt
    lock_path = paths.root / "control" / "launcher.lock"
    with lock_path.open("a+b") as stream:
        if stream.seek(0, 2) == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise ScoutError("LAUNCHER_BUSY", "Another launcher operation is active") from exc
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def descriptor_path(paths):
    return paths.root / "control" / "runtime.json"


def read_descriptor(paths):
    path = descriptor_path(paths)
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text("utf-8"))
        if record["schema"] != 1 or record["data_root"] != str(paths.root):
            raise ValueError()
        uuid.UUID(record["instance"])
        if not 1 <= record["port"] <= 65535 or not isinstance(record["processes"], dict):
            raise ValueError()
        return record
    except (KeyError, ValueError, TypeError) as exc:
        raise ScoutError("DESCRIPTOR_INVALID", "Runtime descriptor requires reconciliation") from exc


def process_args(paths, descriptor, role):
    args = [sys.executable, "-m", "fashion_scout." + ("health" if role == "web" else "worker"),
            "--data-root", str(paths.root), "--instance", descriptor["instance"]]
    if role == "web":
        args.extend(["--port", str(descriptor["port"])])
    return args


def verified_process(paths, descriptor, role):
    record = descriptor["processes"].get(role)
    if not record:
        return None
    expected = process_args(paths, descriptor, role)
    permitted = {Path(sys.executable).resolve(), Path(sys._base_executable).resolve()}
    if Path(record["executable"]).resolve() not in permitted or record["cmdline"][1:] != expected[1:]:
        raise ScoutError("PROCESS_IDENTITY_CONFLICT", "Descriptor does not name this application")
    return owned_process(record)


def verify_health(paths, descriptor):
    challenge = secrets.token_hex(16)
    token_path = paths.root / "control" / (descriptor["instance"] + ".key")
    token = token_path.read_text("ascii")
    request = Request(f"http://127.0.0.1:{descriptor['port']}/v1/health",
                      headers={"X-Scout-Challenge": challenge})
    # Explicitly ignore global HTTP proxy environment for loopback control requests.
    with build_opener(ProxyHandler({})).open(request, timeout=0.5) as response:
        result = json.loads(response.read(16_384))
    proof = hmac.new(token.encode(), (challenge + descriptor["instance"]).encode(), hashlib.sha256).hexdigest()
    record = descriptor["processes"]["web"]
    if (not hmac.compare_digest(result.get("proof", ""), proof)
            or result.get("app_instance_id") != descriptor["instance"]
            or result.get("pid") != record["pid"]
            or abs(result.get("born", 0) - record["born"]) > 0.01):
        raise ScoutError("PORT_IDENTITY_CONFLICT", "Port is not owned by this application")
    result.pop("proof", None)
    return result


def port_available(port: int):
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError as exc:
            raise ScoutError("PORT_IN_USE", "Configured port is occupied; no foreign process was touched") from exc


def spawn(paths, descriptor, role):
    args = process_args(paths, descriptor, role)
    ready_path = paths.root / 'control' / f"{descriptor['instance']}.{role}.json"
    ready_path.unlink(missing_ok=True)
    # Avoid importing code through inherited PYTHONPATH/PYTHONHOME.
    env = {k: v for k, v in os.environ.items() if k.upper() not in
           {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}}
    env["PYTHONUNBUFFERED"] = "1"
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    with (paths.root / "logs" / (role + ".log")).open("ab") as log:
        try:
            proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    cwd=Path(__file__).resolve().parents[2], env=env, shell=False, close_fds=True,
                    creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB)
            breakaway = True
        except OSError as exc:
            if exc.winerror != 5:
                raise
            # Host disallows job breakaway. Record the limitation; do not assert chat-exit survival.
            proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    cwd=Path(__file__).resolve().parents[2], env=env, shell=False, close_fds=True,
                    creationflags=flags)
            breakaway = False
    wrapper = identity(proc.pid)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if ready_path.exists():
            record = json.loads(ready_path.read_text('utf-8'))
            child = owned_process(record)
            if child and (child.pid == proc.pid or proc.pid in [p.pid for p in child.parents()]):
                if record['cmdline'][1:] != args[1:]:
                    raise ScoutError('PROCESS_IDENTITY_CONFLICT', 'Startup handshake command differs')
                record['job_breakaway_requested'] = breakaway
                record['wrapper_pid'] = proc.pid
                return record
        if proc.poll() is not None:
            raise ScoutError('PROCESS_START_FAILED', 'Project process exited before its identity handshake', 503)
        time.sleep(0.05)
    owned = owned_process(wrapper)
    if owned:
        # A timeout is not permission to identify unrelated children by title/PID alone.
        for child in owned.children(recursive=True):
            record = identity(child.pid)
            if record['cmdline'][1:] == args[1:]:
                verified = owned_process(record)
                if verified:
                    verified.terminate()
                    verified.wait(timeout=5)
        owned.terminate()
        owned.wait(timeout=5)
    raise ScoutError('PROCESS_START_FAILED', 'No verified startup handshake', 503)


def reconcile_start(paths, descriptor):
    """A durable intent prevents duplicate spawning if a launcher dies mid-start."""
    role = descriptor.get("starting_role")
    if role is None:
        return
    if role not in ("web", "worker"):
        raise ScoutError("DESCRIPTOR_INVALID", "Unknown starting role")
    ready = paths.root / "control" / f"{descriptor['instance']}.{role}.json"
    if not ready.exists():
        raise ScoutError("STARTUP_RECOVERY_REQUIRED", "Startup was interrupted before identity evidence; inspect local control files")
    candidate = json.loads(ready.read_text("utf-8"))
    proposed = {**descriptor, "processes": {**descriptor["processes"], role: candidate}}
    verified_process(paths, proposed, role)  # Native PID/birth/executable/command check, even on recovery.
    descriptor["processes"][role] = candidate
    descriptor.pop("starting_role")
    atomic_json(descriptor_path(paths), descriptor)


def durable_spawn(paths, descriptor, role):
    descriptor["starting_role"] = role
    atomic_json(descriptor_path(paths), descriptor)
    record = spawn(paths, descriptor, role)
    descriptor["processes"][role] = record
    descriptor.pop("starting_role")
    atomic_json(descriptor_path(paths), descriptor)
    return record


def ensure(paths: Paths, port: int = 8765):
    if os.name != "nt":
        raise ScoutError("PLATFORM_UNSUPPORTED", "This launcher is tested on Windows only", 503)
    environment_check()
    paths.prepare()
    with launcher_lock(paths):
        descriptor = read_descriptor(paths)
        if descriptor:
            reconcile_start(paths, descriptor)
        if descriptor and not descriptor.get("stopped") and descriptor["port"] != port:
            raise ScoutError("PORT_CONFIG_CONFLICT", "Stop the recorded instance before changing its port")
        if descriptor and descriptor.get("stopped"):
            for role in ("web", "worker"):
                if verified_process(paths, descriptor, role):
                    raise ScoutError("STOP_INCOMPLETE", "Previous instance has not exited")
            descriptor = None
        if descriptor is None:
            port_available(port)
            descriptor = {"schema": 1, "data_root": str(paths.root), "instance": str(uuid.uuid4()),
                          "port": port, "processes": {}, "stopped": False}
            key = paths.root / "control" / (descriptor["instance"] + ".key")
            with key.open("x", encoding="ascii") as stream:
                stream.write(secrets.token_hex(32))
            os.chmod(key, 0o600)  # Windows directory ACL remains the local user security boundary.
            atomic_json(descriptor_path(paths), descriptor)
        elif (paths.root / "control" / (descriptor["instance"] + ".stop")).exists():
            raise ScoutError("STOP_INCOMPLETE", "Finish stop before restarting this instance")
        service = Runs(Database(paths.db))
        service.initialize()
        with service.db.read() as conn:
            resuming = [r[0] for r in conn.execute("SELECT id FROM runs WHERE state IN('queued','running','interrupted','cancelling')")]
        created = []
        try:
            web = verified_process(paths, descriptor, "web")
            if web:
                verify_health(paths, descriptor)
            else:
                port_available(port)
                durable_spawn(paths, descriptor, "web")
                created.append("web")
                atomic_json(descriptor_path(paths), descriptor)
            if not verified_process(paths, descriptor, "worker"):
                durable_spawn(paths, descriptor, "worker")
                created.append("worker")
                atomic_json(descriptor_path(paths), descriptor)
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                try:
                    result = verify_health(paths, descriptor)
                    expected_worker = descriptor["processes"]["worker"]
                    if (verified_process(paths, descriptor, "worker") and result["worker_state"] == "online"
                            and result["worker_pid"] == expected_worker["pid"]
                            and abs(result["worker_born"] - expected_worker["born"]) < 0.01):
                        return {**result, "api_base_url": f"http://127.0.0.1:{port}",
                                "resuming_run_ids": resuming, "started_roles": created}
                except (URLError, TimeoutError, ConnectionError):
                    pass
                time.sleep(0.1)
            raise ScoutError("STARTUP_TIMEOUT", "Application processes did not become ready", 503)
        except BaseException:
            # Clean only processes started by this invocation with matching birth/command.
            for role in created:
                proc = verified_process(paths, descriptor, role)
                if proc:
                    proc.terminate()
                    proc.wait(timeout=5)
            raise


def status(paths: Paths):
    descriptor = read_descriptor(paths)
    if descriptor is None:
        return {"web_ready": False, "worker_state": "offline", "resuming_run_ids": []}
    web = verified_process(paths, descriptor, "web")
    worker = verified_process(paths, descriptor, "worker")
    result = {"app_instance_id": descriptor["instance"], "web_ready": False,
              "worker_state": "online" if worker else "offline", "resuming_run_ids": []}
    if web:
        try:
            result.update(verify_health(paths, descriptor))
        except (URLError, TimeoutError, ConnectionError):
            result["web_ready"] = False
    if not worker:
        result["worker_state"] = "offline"
    return result


def stop(paths: Paths, timeout: float = 15):
    if not descriptor_path(paths).exists():
        return {"stopped": True, "forced_roles": []}
    with launcher_lock(paths):
        descriptor = read_descriptor(paths)
        if descriptor is None:
            return {"stopped": True, "forced_roles": []}
        reconcile_start(paths, descriptor)
        for role in ("worker", "web"):
            verified_process(paths, descriptor, role)  # All identities before any signal.
        (paths.root / "control" / (descriptor["instance"] + ".stop")).touch()
        deadline = time.monotonic() + timeout
        forced = []
        for role in ("worker", "web"):
            proc = verified_process(paths, descriptor, role)
            if proc:
                try:
                    proc.wait(timeout=max(0.1, deadline - time.monotonic()))
                except psutil.TimeoutExpired:
                    # Keep an explicit incomplete outcome instead of killing a busy archive writer.
                    forced.append(role)
        if forced:
            raise ScoutError("STOP_TIMEOUT", "Verified processes have not reached a safe stop point")
        descriptor["stopped"] = True
        atomic_json(descriptor_path(paths), descriptor)
        return {"stopped": True, "forced_roles": []}


def open_browser(paths: Paths, port: int = 8765):
    """Verify the owned instance, exchange its local key for one 60-second grant."""
    import webbrowser
    result = ensure(paths, port)
    descriptor = read_descriptor(paths)
    verify_health(paths, descriptor)
    token = (paths.root / "control" / (descriptor["instance"] + ".key")).read_text("ascii")
    request = Request(f"http://127.0.0.1:{port}/v1/session/bootstrap", data=b"{}",
                      headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"}, method="POST")
    with build_opener(ProxyHandler({})).open(request, timeout=5) as response:
        grant = json.load(response)
    url = grant["bootstrap_url"]
    if not url.startswith(f"http://127.0.0.1:{port}/bootstrap#"):
        raise ScoutError("INVALID_BOOTSTRAP", "Owned instance returned an invalid browser entry")
    opened = webbrowser.open(url, new=2)
    return {**result, "browser_opened": bool(opened)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["ensure", "status", "stop", "open"])
    parser.add_argument("--data-root")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--graceful", action="store_true")
    args = parser.parse_args()
    try:
        paths = Paths.at(args.data_root)
        result = open_browser(paths, args.port) if args.action == "open" else ensure(paths, args.port) if args.action == "ensure" else status(paths) if args.action == "status" else stop(paths)
        print(json.dumps(result, ensure_ascii=False))
    except ScoutError as exc:
        print(json.dumps({"error": {"code": exc.code, "message": exc.message}}, ensure_ascii=False))
        raise SystemExit(1)
    except Exception:
        print(json.dumps({"error": {"code": "RUNTIME_ERROR", "message": "Inspect the local runtime environment; no process was assumed owned"}}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
