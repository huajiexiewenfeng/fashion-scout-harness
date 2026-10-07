"""Test-only pause boundaries around the actual Worker/ZIP engine, never production flags."""
import argparse
import json
from pathlib import Path
import time
from fashion_scout.config import Paths
from fashion_scout.processes import identity
from fashion_scout.worker import Worker
from fashion_scout.exports import runner,engine


def main():
    parser=argparse.ArgumentParser();parser.add_argument('root');parser.add_argument('mode',choices=['after_publish','during_copy'])
    args=parser.parse_args();root=Path(args.root)
    original=runner.export_zip
    def mark():
        (root/'export-paused.json').write_text(json.dumps({'process':identity(),'mode':args.mode}),encoding='utf-8')
        while not (root/'export-release').exists():
            if (root/'export-stop').exists():raise runner.ExportInterrupted()
            time.sleep(.05)
    def wrapped(*a,**kw):
        if args.mode=='during_copy':
            callback=kw['checkpoint'];called=[]
            def checkpoint():
                callback()
                called.append(1)
                # First boundary is before the asset; second is after its first
                # source chunk has actually been read into the staging copy.
                if len(called)==2:mark()
            kw['checkpoint']=checkpoint
        result=original(*a,**kw)
        if args.mode=='after_publish':mark()
        return result
    runner.export_zip=wrapped
    Worker(Paths.at(root),(root/'export-stop').exists).run()


if __name__=='__main__':main()
