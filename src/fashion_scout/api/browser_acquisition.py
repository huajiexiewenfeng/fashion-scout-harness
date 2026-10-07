from fastapi import Request
from fashion_scout.domain import ScoutError
from fashion_scout.domain.browser_source import Attach, Observe, Continue, AssetFailure
from fashion_scout.media.browser_intake import BrowserIntake
from fashion_scout.services.browser_acquisition import BrowserAcquisition


def install(app, paths, runs, auth, result):
    service, intake = BrowserAcquisition(runs), BrowserIntake(paths, runs)
    prefix = "/v1/runs/{run_id}/browser-source"

    def bearer(request):
        if not auth.bearer(request):
            raise ScoutError("BEARER_REQUIRED", "Source ingress requires the fixed local client", 401)

    @app.get(prefix)
    def status(run_id: str, request: Request):
        bearer(request)
        return result(request, service.status(run_id))

    @app.post(prefix + "/attach")
    def attach(run_id: str, payload: Attach, request: Request):
        bearer(request)
        return result(request, service.attach(run_id, payload))

    @app.get(prefix + "/receipts/{key}")
    def receipt(run_id: str, key: str, request: Request):
        bearer(request)
        return result(request, service.upload_receipt(run_id, key))

    @app.post(prefix + "/observations")
    def observe(run_id: str, payload: Observe, request: Request):
        bearer(request)
        return result(request, service.observe(run_id, payload), 202)

    @app.post(prefix + "/continue")
    def resume(run_id: str, payload: Continue, request: Request):
        bearer(request)
        return result(request, service.continue_run(run_id, payload), 202)

    @app.post(prefix + "/assets/{ticket_id}/failure")
    def asset_failure(run_id: str, ticket_id: str, payload: AssetFailure, request: Request):
        bearer(request)
        return result(request, service.asset_failure(run_id, ticket_id, payload))

    @app.post(prefix + "/assets/{ticket_id}/body")
    async def body(run_id: str, ticket_id: str, request: Request):
        bearer(request)
        if request.headers.get("content-type") != "application/octet-stream":
            raise ScoutError("INVALID_PAYLOAD", "Source body must be an image byte stream", 422)
        try:
            size = int(request.headers.get("x-source-bytes", ""))
        except ValueError:
            raise ScoutError("INVALID_PAYLOAD", "Source byte count is required", 422)
        transfer = intake.begin(run_id, ticket_id, request.headers.get("x-source-session", ""),
                                request.headers.get("x-request-key", ""), request.headers.get("x-source-sha256", ""), size,
                                request.headers.get("x-source-url", ""))
        return result(request, await intake.receive(request, transfer), 202)
