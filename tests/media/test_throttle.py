import json
import time
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import httpx
import pytest
from fashion_scout.media.http import retry_seconds
from tests.t2_helpers import setup, accept, execute, Scenario, product


@pytest.mark.parametrize("header", ["600", "http-date"])
def test_server_cooldown_survives_new_worker_retry_and_new_run(tmp_path,header):
    runs,paths=setup(tmp_path)
    if header=="http-date":
        header=format_datetime(datetime.now(timezone.utc)+timedelta(minutes=10),usegmt=True)
    scenario=Scenario([product()])
    normal=scenario.handler
    def limited(request):
        scenario.calls.append(str(request.url))
        return httpx.Response(429,headers={"Retry-After":header})
    scenario.handler=limited
    first=accept(runs)
    assert execute(runs,paths,first.id,scenario).state=="failed"
    assert len(scenario.calls)==1
    with runs.db.read() as conn:
        record=conn.execute("SELECT * FROM network_throttle").fetchone()
        assert record["not_before"] > time.time()+590 and record["mode"]=="server"
        response=conn.execute("SELECT * FROM collection_http_results").fetchone()
        assert response["status"]==429 and response["retry_after"]==header and response["received_at"]
    runs.retry(first.id,"still-waiting")
    assert execute(runs,paths,first.id,scenario).state=="failed"
    assert len(scenario.calls)==1
    second=accept(runs,"another-run")
    assert execute(runs,paths,second.id,scenario).state=="failed"
    with runs.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM collection_http").fetchone()[0]==1
        assert conn.execute("SELECT request_count FROM collection_runs WHERE run_id=?",(second.id,)).fetchone()[0]==0
    # Simulate elapsed cooldown. Only the next explicit accepted Run may send again.
    with runs.db.write() as conn:
        conn.execute("UPDATE network_throttle SET not_before=?",(time.time()-1,))
    scenario.handler=normal
    third=accept(runs,"after-expiry")
    assert execute(runs,paths,third.id,scenario).state=="succeeded"
    assert len(scenario.calls)>1


def test_unknown_legacy_wait_is_not_invented_from_fixture(tmp_path):
    runs,paths=setup(tmp_path)
    with runs.db.write() as conn:
        conn.execute("INSERT INTO network_throttle VALUES ('futario',NULL,'legacy_response_not_saved',NULL,?)",(time.time(),))
    scenario=Scenario([product()])
    run=accept(runs)
    assert execute(runs,paths,run.id,scenario).state=="failed"
    assert scenario.calls==[]
    with runs.db.read() as conn:
        assert conn.execute("SELECT code FROM issues").fetchone()[0]=="RATE_LIMIT_REVIEW_REQUIRED"
        assert conn.execute("SELECT not_before FROM network_throttle").fetchone()[0] is None


def test_http_date_and_invalid_value():
    target=datetime.now(timezone.utc)+timedelta(seconds=600)
    assert 598 < retry_seconds(format_datetime(target,usegmt=True)) <= 600
    with pytest.raises(Exception):
        retry_seconds("NaN")
