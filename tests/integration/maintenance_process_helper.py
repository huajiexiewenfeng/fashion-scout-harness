"""Test-only pause around actual maintenance engine boundaries."""
import argparse
import json
from pathlib import Path
import time
from fashion_scout.config import Paths
from fashion_scout.processes import identity
from fashion_scout.worker import Worker
from fashion_scout.maintenance import runner


def main():
    p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('mode',choices=['during_copy','after_publish']);args=p.parse_args();root=Path(args.root)
    original=runner.backup
    def pause():
        (root/'maintenance-paused.json').write_text(json.dumps({'process':identity(),'mode':args.mode}),encoding='utf-8')
        while not (root/'maintenance-release').exists():
            if (root/'maintenance-stop').exists():raise runner.Interrupted()
            time.sleep(.03)
    def wrapped(paths,jid,checkpoint):
        marked=[]
        def check():
            checkpoint()
            if args.mode=='during_copy' and not marked and any((root/'maintenance'/jid).glob('stage-*/assets/*.bin')):
                marked.append(1);pause()
        result=original(paths,jid,check)
        if args.mode=='after_publish':pause()
        return result
    runner.backup=wrapped
    Worker(Paths.at(root),(root/'maintenance-stop').exists).run()


if __name__=='__main__':main()
