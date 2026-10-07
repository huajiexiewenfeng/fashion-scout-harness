import secrets
import pytest
from fastapi.testclient import TestClient
from fashion_scout.config import Paths
from fashion_scout.db import Database
from fashion_scout.services.runs import Runs
from fashion_scout.health import create_app


@pytest.fixture
def api_env(tmp_path):
    paths=Paths.at(tmp_path);paths.prepare()
    runs=Runs(Database(paths.db));runs.initialize()
    token=secrets.token_hex(32)
    (paths.root/'control'/'test.key').write_text(token,'ascii')
    app=create_app(paths,'test',18765)
    client=TestClient(app,base_url='http://127.0.0.1:18765',headers={'Authorization':'Bearer '+token})
    with client:
        yield client, app, runs, paths, token
