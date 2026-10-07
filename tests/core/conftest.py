import pytest
from fashion_scout.config import Paths
from fashion_scout.db import Database
from fashion_scout.services.runs import Runs
from fashion_scout.processes import identity


@pytest.fixture
def service(tmp_path):
    paths = Paths.at(tmp_path)
    paths.prepare()
    runs = Runs(Database(paths.db))
    runs.initialize()
    return runs, paths


@pytest.fixture
def claimed(service):
    from fashion_scout.domain import CreateRun
    runs, paths = service
    run = runs.create(CreateRun(request_key="first", trigger="skill")).run
    who = identity()
    runs.register_worker("one", who["pid"], who["born"], who["executable"])
    return runs, paths, runs.claim("one"), run
