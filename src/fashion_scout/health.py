"""T1 minimum health server. T3 owns future API routes and browser authentication."""
import argparse
import hashlib
import hmac
import threading
import time

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Paths
from .db import Database
from .processes import identity, publish_identity


def create_app(paths: Paths, instance: str, port: int):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1"])
    token = (paths.root / "control" / (instance + ".key")).read_text("ascii")
    who = identity()

    @app.get("/v1/health")
    def health(request: Request, x_scout_challenge: str = Header(default="")):
        if len(x_scout_challenge) > 128:
            raise HTTPException(422, "Challenge too long")
        with Database(paths.db).read() as conn:
            worker = conn.execute("SELECT heartbeat_at,pid,born FROM workers WHERE state='online' ORDER BY heartbeat_at DESC LIMIT 1").fetchone()
            version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        result = {"request_id": request.state.request_id, "app_instance_id": instance, "schema_version": version, "web_ready": True,
                  "worker_state": "online" if worker and time.time() - worker["heartbeat_at"] < 30 else "offline",
                  "heartbeat_at": worker["heartbeat_at"] if worker else None,
                  "worker_pid": worker["pid"] if worker else None,
                  "worker_born": worker["born"] if worker else None,
                  "pid": who["pid"], "born": who["born"],
                  "source_adapter": "futario-json-v1"}
        if x_scout_challenge:
            result["proof"] = hmac.new(token.encode(), (x_scout_challenge + instance).encode(), hashlib.sha256).hexdigest()
        return result
    from .api.routes import install
    install(app, paths, instance, port, token)
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    paths = Paths.at(args.data_root)
    publish_identity(paths, args.instance, 'web')
    stop_file = paths.root / "control" / (args.instance + ".stop")
    server = uvicorn.Server(uvicorn.Config(create_app(paths, args.instance, args.port),
                             host="127.0.0.1", port=args.port, workers=1, log_level="warning",
                             access_log=False))
    def watch():
        while not server.should_exit:
            if stop_file.exists():
                server.should_exit = True
                return
            time.sleep(0.1)
    threading.Thread(target=watch, daemon=True).start()
    server.run()


if __name__ == "__main__":
    main()
