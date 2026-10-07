import io
import json
import time
from pathlib import Path
from typing import Literal

from fastapi import Request, Query
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from PIL import Image, UnidentifiedImageError
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.staticfiles import StaticFiles

from fashion_scout.db import Database
from fashion_scout.domain import ScoutError, CreateRun, DefaultPlan
from fashion_scout.services.runs import Runs
from fashion_scout.services.presentation import Presentation
from .models import CreateRunRequest, Operation, Retry, PlanPatch, UserPatch, ViewEvent, BootstrapExchange, EmptyRequest
from .security import BrowserAuth, error


def install(app, paths, instance, port, token):
    db = Database(paths.db)
    runs, presentation = Runs(db), Presentation(db)
    auth = BrowserAuth(token, instance, port)
    app.state.auth, app.state.presentation = auth, presentation
    app.middleware("http")(auth.middleware)
    package = Path(__file__).parent.parent
    app.mount("/static", StaticFiles(directory=package / "static"), name="static")

    def result(request, value, status=200):
        return JSONResponse({**value, "request_id": request.state.request_id}, status_code=status)

    @app.exception_handler(ScoutError)
    async def scout_error(request, exc):
        return error(exc.code, exc.message, exc.status, request.state.request_id)

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def validation_error(request, exc):
        # Never echo payloads, cookies, bootstrap codes or source HTML in errors.
        return error("INVALID_PAYLOAD", "输入字段或类型不符合接口要求", 422, request.state.request_id,
                     {"fields": [".".join(map(str, e["loc"])) for e in exc.errors()]})

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error("NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR", "请求不可用", exc.status_code, request.state.request_id)

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        return error("LOCAL_SERVICE_ERROR", "本机服务暂时无法完成请求", 500, getattr(request.state, "request_id", None))

    @app.get("/")
    def index():
        return FileResponse(package / "templates" / "index.html", media_type="text/html")

    @app.get("/bootstrap")
    def bootstrap_page():
        return FileResponse(package / "templates" / "bootstrap.html", media_type="text/html")

    @app.post("/v1/session/bootstrap")
    def bootstrap(payload: EmptyRequest, request: Request):
        if not auth.bearer(request):
            raise ScoutError("BEARER_REQUIRED", "只能由本机启动器建立页面会话", 401)
        return result(request, {"bootstrap_url": auth.origin + "/bootstrap#" + auth.issue(), "expires_in": 60})

    @app.post("/v1/session/exchange")
    def exchange(payload: BootstrapExchange, request: Request):
        grant = auth.exchange(payload.code)
        if grant is None:
            raise ScoutError("BOOTSTRAP_EXPIRED", "打开链接已使用或失效，请从本机启动入口重新打开", 401)
        sid, session = grant
        response = result(request, {"ok": True})
        # HTTP loopback cannot reliably send Secure cookies in every browser.
        response.set_cookie(auth.cookie, sid, max_age=8 * 3600, httponly=True,
                            secure=False, samesite="strict", path="/")
        return response

    @app.get("/v1/session")
    def session(request: Request):
        current = auth.session(request)
        return result(request, {"csrf_token": current["csrf"] if current else None})

    def run_detail(run):
        value = run.model_dump(mode="json")
        with db.read() as conn:
            worker = conn.execute("SELECT heartbeat_at FROM workers WHERE state='online' ORDER BY heartbeat_at DESC LIMIT 1").fetchone()
            counts = {row["state"]: row["n"] for row in conn.execute("SELECT state,COUNT(*) n FROM work_items WHERE run_id=? GROUP BY state", (run.id,))}
            coverage = [dict(r) for r in conn.execute("SELECT site_id,coverage_json FROM site_runs WHERE run_id=?", (run.id,))]
            issues = [dict(r) for r in conn.execute("SELECT code,retryable FROM issues WHERE run_id=? ORDER BY id", (run.id,))]
            stage = conn.execute("SELECT kind FROM run_events WHERE run_id=? ORDER BY seq DESC LIMIT 1", (run.id,)).fetchone()
        source = {}
        if run.snapshot.source_mode == "browser":
            from fashion_scout.services.browser_acquisition import BrowserAcquisition
            source = {"browser_source": BrowserAcquisition(runs).status(run.id)}
        return {**value, **source, "stage": stage[0] if stage else "accepted", "counts": counts,
                "plan_revision": run.snapshot.plan_revision,
                "worker_state": "online" if worker and time.time() - worker[0] < 30 else "offline",
                "coverage": [{"site_id": c["site_id"], **json.loads(c["coverage_json"])} for c in coverage],
                "issues": [{**i, "retryable": bool(i["retryable"])} for i in issues]}

    def latest():
        with db.read() as conn:
            row = conn.execute("SELECT * FROM runs ORDER BY created_at DESC,id DESC LIMIT 1").fetchone()
            completed = conn.execute("SELECT MAX(finished_at) FROM runs WHERE state IN ('succeeded','partial','failed','cancelled')").fetchone()[0]
            success = conn.execute("SELECT MAX(finished_at) FROM runs WHERE state='succeeded'").fetchone()[0]
        return {"latest_run": run_detail(runs._view(row)) if row else None,
                "latest_completed_at": completed, "latest_successful_at": success}

    @app.get("/v1/settings/default-plan")
    def default(request: Request):
        revision, plan = runs.default_plan()
        return result(request, {"revision": revision, "plan": plan.model_dump(mode="json"),
                                "available": {"window_days": [7, 14], "unknown_date_policy": ["include", "exclude"]}})

    @app.patch("/v1/settings/default-plan")
    def patch_default(payload: PlanPatch, request: Request):
        revision, plan = runs.default_plan()
        if revision != payload.expected_revision:
            raise ScoutError("REVISION_CONFLICT", "默认方案已改变，请刷新", 409)
        merged = plan.model_dump(mode="json")
        merged.update(payload.model_dump(exclude_unset=True, exclude={"expected_revision"}, mode="json"))
        new_plan = DefaultPlan.model_validate(merged)
        revision = runs.save_default(new_plan, payload.expected_revision)
        return result(request, {"revision": revision, "plan": new_plan.model_dump(mode="json")})

    @app.get("/v1/sites")
    def sites(request: Request):
        with db.read() as conn:
            rows = [dict(r) for r in conn.execute("SELECT id,entry,adapter_version,enabled,baseline_complete FROM sites")]
        return result(request, {"items": rows, "capability_notes": [{"scope": "product.images", "status": "supported"}, {"scope": "other_media", "status": "unknown"}],
            "source_modes": {"http": {"adapter_version": "futario-json-v1", "coverage_scope": "product.images"},
                             "browser": {"adapter_version": "futario-browser-host-v1", "coverage_scope": "browser.gallery", "full_product_images": "unknown", "requires_foreground_host": True}}})

    @app.post("/v1/runs")
    def create_run(payload: CreateRunRequest, request: Request):
        created = runs.create(payload)
        return result(request, {**created.model_dump(mode="json"), "run": run_detail(created.run)}, 200 if created.reused else 202)

    @app.get("/v1/runs/latest")
    def latest_run(request: Request):
        return result(request, latest())

    @app.get("/v1/runs/by-request/{key}")
    def by_request(key: str, request: Request):
        return result(request, {"run": run_detail(runs.by_request(key))})

    @app.get("/v1/runs/{run_id}")
    def get_run(run_id: str, request: Request):
        return result(request, {"run": run_detail(runs.get(run_id))})

    @app.post("/v1/runs/{run_id}/cancel")
    def cancel(run_id: str, payload: Operation, request: Request):
        runs.cancel(run_id, payload.request_key)
        return result(request, {"run": run_detail(runs.get(run_id))})

    @app.post("/v1/runs/{run_id}/retry")
    def retry(run_id: str, payload: Retry, request: Request):
        if payload.item_ids is not None:
            raise ScoutError("SELECTIVE_RETRY_UNAVAILABLE", "当前支持重试此巡检的全部失败项，暂不支持指定单项", 501)
        runs.retry(run_id, payload.request_key)
        return result(request, {"run": run_detail(runs.get(run_id))})

    @app.get("/v1/products")
    def products(request: Request, view: Literal["new", "favorites"] = "new", category: str | None = None,
                 cursor: str | None = Query(default=None, max_length=2048), limit: int = Query(default=40, ge=1, le=100)):
        return result(request, {**presentation.listing(view, category, cursor, limit), "latest_run_summary": latest()})

    @app.get("/v1/products/{pid}")
    def product(pid: str, request: Request, version_id: str | None = None, version_revision: int | None = Query(default=None, gt=0)):
        if version_revision is not None and version_id is None:
            raise ScoutError("INVALID_PAYLOAD", "历史修订需要图集标识", 422)
        return result(request, {"product": presentation.detail(pid, version_id, version_revision)})

    @app.patch("/v1/products/{pid}/user-state")
    def user_state(pid: str, payload: UserPatch, request: Request):
        return result(request, {"user_state": presentation.patch(pid, payload)})

    @app.post("/v1/products/{pid}/view-events")
    def viewed(pid: str, payload: ViewEvent, request: Request):
        return result(request, presentation.view_event(pid, payload))

    @app.get("/v1/assets/{aid}")
    def asset(aid: str, rendition: Literal["preview", "original"] = "preview"):
        row, path = presentation.asset(aid)
        media = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}.get(row["format"])
        if not media:
            raise ScoutError("ASSET_MISSING", "图片格式不可用", 404)
        if rendition == "original":
            return FileResponse(path, media_type=media)
        try:
            with Image.open(path) as image:
                image.thumbnail((800, 1000))
                output = io.BytesIO()
                image.convert("RGB").save(output, "JPEG", quality=85)
            return Response(output.getvalue(), media_type="image/jpeg")
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
            raise ScoutError("ASSET_MISSING", "图片无法显示", 404) from None

    from .exports import install_exports
    install_exports(app, paths, result)

    from .browser_acquisition import install as install_browser_acquisition
    install_browser_acquisition(app, paths, runs, auth, result)

    from .maintenance import install_maintenance
    install_maintenance(app, paths, result)
