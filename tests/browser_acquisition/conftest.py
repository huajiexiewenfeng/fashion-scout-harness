import secrets
import threading
import time
from contextlib import contextmanager
import pytest
from fastapi.testclient import TestClient
from fashion_scout.config import Paths
from fashion_scout.db import Database
from fashion_scout.health import create_app
from fashion_scout.services.runs import Runs
from fashion_scout.worker import Worker


def eventually(check, timeout=8):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        result=check()
        if result:return result
        time.sleep(.05)
    raise AssertionError('Condition did not become true')


@pytest.fixture
def env(tmp_path):
    paths=Paths.at(tmp_path);paths.prepare()
    runs=Runs(Database(paths.db));runs.initialize()
    token=secrets.token_hex(32)
    (paths.root/'control'/'test.key').write_text(token,'ascii')
    app=create_app(paths,'test',18765)
    with TestClient(app,base_url='http://127.0.0.1:18765',headers={'Authorization':'Bearer '+token}) as client:
        yield client,runs,paths,app


@contextmanager
def worker(paths):
    stopped=threading.Event()
    value=Worker(paths,stopped.is_set,heartbeat_seconds=.1,lease_seconds=2,poll_seconds=.05)
    thread=threading.Thread(target=value.run,daemon=True);thread.start()
    try:yield value
    finally:
        stopped.set();thread.join(8)
        assert not thread.is_alive()
