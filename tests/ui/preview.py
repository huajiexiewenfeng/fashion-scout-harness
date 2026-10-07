"""Explicit isolated browser QA entry; no production fake-success switch."""
import argparse
import json
import socket
from pathlib import Path
from unittest.mock import patch
from fashion_scout.config import Paths
from fashion_scout.db import Database
from fashion_scout.services.runs import Runs
from fashion_scout.launcher import open_browser, stop
from tests.api.helpers import seed


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['empty','seed','stop','entry'])
    parser.add_argument('--root',required=True)
    args=parser.parse_args()
    root=Path(args.root).resolve()
    # QA must explicitly stay inside this checkout's dedicated T3 area.
    expected=Path(__file__).resolve().parents[2]/'.runtime'/'t3-browser'
    if root!=expected.resolve():raise RuntimeError('Use the dedicated isolated T3 browser root')
    paths=Paths.at(root)
    if args.action=='stop':print(json.dumps(stop(paths)));return
    if args.action=='seed':
        runs=Runs(Database(paths.db))
        seed(runs,paths)
        print('Seeded 8 explicit synthetic products; no external requests')
        return
    if args.action=='empty':
        if root.exists():raise RuntimeError('Do not overwrite an existing QA root')
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    else:
        from fashion_scout.launcher import read_descriptor
        port=read_descriptor(paths)['port']
    captured=[]
    with patch('webbrowser.open',side_effect=lambda url,**kwargs: captured.append(url) or True):
        result=open_browser(paths,port)
    print(json.dumps({'port':port,'browser_entry':captured[0],'web_ready':result['web_ready'],'resuming_run_ids':result['resuming_run_ids']}))


if __name__=='__main__':main()
