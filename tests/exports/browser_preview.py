"""Explicit isolated synthetic browser QA; never selects the default user root."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import webbrowser
from fashion_scout import launcher
from fashion_scout.config import Paths
from fashion_scout.db import Database
from fashion_scout.services.runs import Runs
from fashion_scout.exports.jobs import Jobs
from tests.api.helpers import seed

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['init','entry','pause-worker','ensure','evidence','stop']);parser.add_argument('root');parser.add_argument('--download')
    args=parser.parse_args();target=Path(args.root).resolve()
    assert target.parent==ROOT/'.runtime' and target.name.startswith('t5b-browser-')
    paths=Paths.at(target)
    if args.action=='init':
        assert not target.exists(),'Use a fresh explicit QA root'
        paths.prepare();runs=Runs(Database(paths.db));runs.initialize();seed(runs,paths,count=8)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        launcher.ensure(paths,port)
    descriptor=launcher.read_descriptor(paths);port=descriptor['port']
    if args.action in {'init','entry'}:
        def capture(url,**kwargs):
            (target/'browser-entry.txt').write_text(url,encoding='utf-8');return True
        webbrowser.open=capture;launcher.open_browser(paths,port)
        print(json.dumps({'root':str(target),'port':port,'entry_file':str(target/'browser-entry.txt')}))
    elif args.action=='pause-worker':
        with Database(paths.db).read() as conn:
            assert conn.execute("SELECT COUNT(*) FROM runs WHERE state IN ('queued','running','interrupted','cancelling')").fetchone()[0]==0
            assert conn.execute("SELECT COUNT(*) FROM export_jobs WHERE state IN ('queued','running')").fetchone()[0]==0
        proc=launcher.verified_process(paths,descriptor,'worker')
        if proc:proc.terminate();proc.wait(timeout=5)
        print('{"worker":"offline","web":"retained"}')
    elif args.action=='ensure':
        result=launcher.ensure(paths,port);print(json.dumps({'worker_state':result['worker_state'],'resuming_run_ids':result['resuming_run_ids']}))
    elif args.action=='stop':print(json.dumps(launcher.stop(paths)))
    elif args.action=='evidence':
        with Database(paths.db).read() as conn:
            jobs=[r[0] for r in conn.execute('SELECT id FROM export_jobs')]
            result={'root':str(target),'job_count':len(jobs),'attempt_count':conn.execute('SELECT COUNT(*) FROM export_attempts').fetchone()[0],
                'run_count':conn.execute('SELECT COUNT(*) FROM runs').fetchone()[0],
                'source_requests':conn.execute('SELECT COUNT(*) FROM collection_http').fetchone()[0],
                'favorites':conn.execute('SELECT COUNT(*) FROM product_user_state WHERE favorite=1').fetchone()[0]}
        result['exports']=[Jobs(paths).get(jid) for jid in jobs]
        if args.download:
            p=Path(args.download);sha=hashlib.sha256(p.read_bytes()).hexdigest()
            assert len(jobs)==1 and sha==result['exports'][0]['sha256']
            result['browser_download']={'path':str(p),'bytes':p.stat().st_size,'sha256':sha}
        (target/'browser-evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
