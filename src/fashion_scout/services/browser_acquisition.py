"""Authenticated durable inbox, independent of the foreground browser lifetime."""
import json
from fashion_scout.domain import ScoutError
from fashion_scout.domain.browser_source import ADAPTER_VERSION
from fashion_scout.services.runs import canonical, digest, new_id, timestamp


class SourceWait(Exception):
    pass


class BrowserAcquisition:
    def __init__(self, runs):
        self.runs, self.db = runs, runs.db

    def run(self, conn, run_id):
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        view = self.runs._view(row)
        if (view.snapshot.source_mode != "browser" or
                view.snapshot.adapter_versions.get("futario") != ADAPTER_VERSION):
            raise ScoutError("SOURCE_MODE_CONFLICT", "Run does not accept the browser adapter")
        return row, view

    def ensure(self, conn, run_id):
        conn.execute("INSERT OR IGNORE INTO browser_runs(run_id,last_activity) VALUES (?,?)", (run_id, self.runs.clock()))

    def replay(self, conn, run_id, key, payload):
        if conn.execute("SELECT 1 FROM browser_uploads WHERE request_key=?", (key,)).fetchone():
            raise ScoutError("REQUEST_KEY_CONFLICT", "Source key was used for an upload")
        row = conn.execute("SELECT * FROM browser_requests WHERE request_key=?", (key,)).fetchone()
        if row:
            if row["run_id"] != run_id or row["payload_hash"] != digest(payload):
                raise ScoutError("REQUEST_KEY_CONFLICT", "Source request key has different parameters")
            return json.loads(row["response_json"])

    def receipt(self, conn, run_id, key, payload, result):
        conn.execute("INSERT INTO browser_requests VALUES (?,?,?,?)", (key, run_id, digest(payload), canonical(result)))
        return result

    def session(self, conn, run_id, session_id, *, touch=False):
        row, view = self.run(conn, run_id)
        session = conn.execute("SELECT * FROM browser_sessions WHERE id=? AND run_id=?", (session_id, run_id)).fetchone()
        target = row["epoch"] + (1 if row["state"] == "queued" else 0)
        if (not session or session["state"] != "active" or session["run_epoch"] != target
                or row["state"] not in ("queued", "running") or row["cancel_requested"]):
            raise ScoutError("STALE_SOURCE_SESSION", "Source session no longer owns this Run epoch")
        if self.runs.clock() - session["created_at"] >= view.snapshot.browser.host_seconds:
            raise ScoutError("SOURCE_HOST_BUDGET", "Frozen foreground session time allowance reached")
        if touch:
            conn.execute("UPDATE browser_sessions SET last_activity=? WHERE id=?", (self.runs.clock(), session_id))
            conn.execute("UPDATE browser_runs SET last_activity=?,phase='receiving' WHERE run_id=?", (self.runs.clock(), run_id))
        return row, view

    def attach(self, run_id, request):
        payload = {"verb": "attach", **request.model_dump(mode="json", exclude={"request_key"})}
        with self.db.write() as conn:
            prior = self.replay(conn, run_id, request.request_key, payload)
            if prior is not None:
                return prior
            row, view = self.run(conn, run_id)
            if row["state"] not in ("queued", "running") or row["cancel_requested"]:
                raise ScoutError("SOURCE_CONTINUE_REQUIRED", "Use explicit browser-continue for a suspended source")
            self.ensure(conn, run_id)
            target = row["epoch"] + (1 if row["state"] == "queued" else 0)
            session = conn.execute("SELECT * FROM browser_sessions WHERE run_id=? AND state='active'", (run_id,)).fetchone()
            if session and session["run_epoch"] != target:
                conn.execute("UPDATE browser_sessions SET state='closed' WHERE id=?", (session["id"],))
                session = None
            if session and self.runs.clock() - session["created_at"] >= view.snapshot.browser.host_seconds:
                raise ScoutError("SOURCE_HOST_BUDGET", "Session budget reached; suspend before continuing")
            sid = session["id"] if session else new_id()
            if session is None:
                conn.execute("INSERT INTO browser_sessions VALUES (?,?,?,'active',?,?,?)",
                             (sid, run_id, target, self.runs.clock(), self.runs.clock(), ADAPTER_VERSION))
            self.session(conn, run_id, sid, touch=True)
            return self.receipt(conn, run_id, request.request_key, payload,
                {"run_id": run_id, "session_id": sid, "run_epoch": target, "adapter_version": ADAPTER_VERSION,
                 "coverage_scope": "browser.gallery", "limits": view.snapshot.browser.model_dump(),
                 "network_accounting": "browser_background_requests_bytes_and_peer_unknown"})

    def observe(self, run_id, request):
        payload = {"verb": "observe", **request.model_dump(mode="json", exclude={"request_key"})}
        with self.db.write() as conn:
            prior = self.replay(conn, run_id, request.request_key, payload)
            if prior is not None:
                return prior
            _, view = self.session(conn, run_id, request.session_id, touch=True)
            state = conn.execute("SELECT * FROM browser_runs WHERE run_id=?", (run_id,)).fetchone()
            if state["finish_received"]:
                raise ScoutError("SOURCE_FINISHED", "Source submission was already closed")
            if state["observations"] >= view.snapshot.browser.max_observations:
                raise ScoutError("SOURCE_OBSERVATION_BUDGET", "Frozen source observation allowance reached")
            mid = new_id()
            conn.execute("INSERT INTO browser_messages(id,run_id,session_id,sequence,observation_json) VALUES (?,?,?,?,?)",
                         (mid, run_id, request.session_id, state["observations"] + 1, request.observation.model_dump_json()))
            conn.execute("UPDATE browser_runs SET observations=observations+1,finish_received=? WHERE run_id=?",
                         (int(request.observation.kind == "finish"), run_id))
            return self.receipt(conn, run_id, request.request_key, payload, {"run_id": run_id, "message_id": mid, "state": "pending"})

    def asset_failure(self, run_id, ticket_id, request):
        payload = {"verb": "asset-failure", "ticket_id": ticket_id, **request.model_dump(mode="json", exclude={"request_key"})}
        with self.db.write() as conn:
            prior = self.replay(conn, run_id, request.request_key, payload)
            if prior is not None:
                return prior
            self.session(conn, run_id, request.session_id, touch=True)
            ticket = conn.execute("SELECT * FROM browser_assets WHERE id=? AND run_id=?", (ticket_id, run_id)).fetchone()
            if not ticket:
                raise ScoutError("SOURCE_TICKET_NOT_FOUND", "Worker has not qualified this image", 404)
            if ticket["state"] not in ("pending", "failed"):
                raise ScoutError("SOURCE_TICKET_BUSY", "Image is already received or being processed")
            conn.execute("UPDATE browser_assets SET state='failed',issue_code=? WHERE id=?", (request.code, ticket_id))
            return self.receipt(conn, run_id, request.request_key, payload, {"ticket_id": ticket_id, "state": "failed"})

    def status(self, run_id):
        with self.db.read() as conn:
            row, view = self.run(conn, run_id)
            state = conn.execute("SELECT * FROM browser_runs WHERE run_id=?", (run_id,)).fetchone()
            messages = [dict(r) for r in conn.execute("SELECT id,sequence,state,issue_code FROM browser_messages WHERE run_id=? ORDER BY sequence", (run_id,))]
            tickets = [dict(r) for r in conn.execute("SELECT id,product_id,source_image_id,source_url,state,bytes,sha256,issue_code FROM browser_assets WHERE run_id=? ORDER BY product_id,source_image_id", (run_id,))]
            products = [dict(r) for r in conn.execute("SELECT product_id,eligible,rule,detail_error FROM collection_products WHERE run_id=? ORDER BY product_id", (run_id,))]
            return {"run_id": run_id, "state": row["state"], "epoch": row["epoch"],
                    "phase": state["phase"] if state else "waiting_host", "coverage_scope": "browser.gallery",
                    "requires_foreground_host": True, "messages": messages, "tickets": tickets, "products": products,
                    "received_bytes": state["received_bytes"] if state else 0,
                    "selected_assets": state["selected_assets"] if state else 0,
                    "limits": view.snapshot.browser.model_dump(),
                    "network_accounting": "browser_background_requests_bytes_and_peer_unknown"}

    def upload_receipt(self, run_id, key):
        with self.db.read() as conn:
            self.run(conn, run_id)
            row = conn.execute("SELECT * FROM browser_uploads WHERE request_key=? AND run_id=?", (key, run_id)).fetchone()
            if row and row["state"] == "received":
                return json.loads(row["response_json"])
            if row and row["state"] == "uploading":
                ticket=conn.execute("SELECT * FROM browser_assets WHERE id=?", (row["ticket_id"],)).fetchone()
                from fashion_scout.media.browser_intake import receiver_dead
                if not receiver_dead(ticket):
                    raise ScoutError("SOURCE_UPLOAD_IN_PROGRESS", "Original receiver still owns this upload")
            raise ScoutError("SOURCE_RECEIPT_NOT_FOUND", "No completed upload receipt exists", 404)

    def suspend(self, lease):
        """Release only after local inbox/Archive processing reaches a safe boundary."""
        with self.db.write() as conn:
            self.runs.fence(conn, lease)
            self.ensure(conn, lease.run_id)
            conn.execute("UPDATE browser_sessions SET state='closed' WHERE run_id=? AND state='active'", (lease.run_id,))
            conn.execute("UPDATE browser_runs SET phase='waiting_host',source_wait=1 WHERE run_id=?", (lease.run_id,))
            conn.execute("UPDATE runs SET state='interrupted',issue_code='SOURCE_HOST_REQUIRED',owner=NULL,lease_until=NULL,epoch=epoch+1 WHERE id=?", (lease.run_id,))
            self.runs._event(conn, lease.run_id, "waiting_host", lease.epoch + 1)

    def continue_run(self, run_id, request):
        payload = {"verb": "browser-continue"}
        with self.db.write() as conn:
            prior = self.replay(conn, run_id, request.request_key, payload)
            if prior is not None:
                return prior
            row, _ = self.run(conn, run_id)
            state = conn.execute("SELECT source_wait FROM browser_runs WHERE run_id=?", (run_id,)).fetchone()
            if row["state"] != "interrupted" or not state or not state[0] or row["lease_until"] is not None:
                raise ScoutError("SOURCE_CONTINUE_NOT_ALLOWED", "Continue requires a safely suspended browser Run")
            self.runs._requeue(conn, row, "source_continued")
            return self.receipt(conn, run_id, request.request_key, payload, {"run_id": run_id, "state": "queued", "same_run": True})
