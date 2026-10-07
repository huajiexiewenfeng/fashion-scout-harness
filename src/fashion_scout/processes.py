import os
import json
import uuid
from pathlib import Path

import psutil

from .domain import ScoutError


def publish_identity(paths, instance: str, role: str):
    uuid.UUID(instance)
    target = paths.root / 'control' / f'{instance}.{role}.json'
    temp = target.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as stream:
        json.dump(identity(), stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, target)


def identity(pid: int | None = None) -> dict:
    proc = psutil.Process(pid or os.getpid())
    return {"pid": proc.pid, "born": proc.create_time(), "executable": proc.exe(),
            "cmdline": proc.cmdline()}


def is_dead(record: dict) -> bool:
    """Unknown/access-denied is NOT dead. PID reuse is confirmed by birth identity."""
    try:
        proc = psutil.Process(record["pid"])
        return abs(proc.create_time() - record["born"]) > 0.01 or not proc.is_running()
    except psutil.NoSuchProcess:
        return True
    except psutil.AccessDenied:
        return False


def owned_process(record: dict):
    try:
        proc = psutil.Process(record["pid"])
        if abs(proc.create_time() - record["born"]) > 0.01:
            return None
        if Path(proc.exe()).resolve() != Path(record["executable"]).resolve() or proc.cmdline() != record["cmdline"]:
            raise ScoutError("PROCESS_IDENTITY_CONFLICT", "Recorded process identity does not match")
        return proc
    except psutil.NoSuchProcess:
        return None
    except psutil.AccessDenied as exc:
        raise ScoutError("PROCESS_UNVERIFIABLE", "Process identity cannot be verified") from exc
