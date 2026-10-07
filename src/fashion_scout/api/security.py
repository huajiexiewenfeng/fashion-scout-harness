"""Volatile one-use browser grants. The instance key never reaches browser code."""
import hmac
import secrets
import threading
import time
import uuid
from starlette.responses import JSONResponse


def error(code, message, status, request_id=None, details=None):
    return JSONResponse({"error": {"code": code, "message": message,
                         "retryable": status == 503, "details": details or {}},
                         "request_id": request_id or uuid.uuid4().hex}, status_code=status)


class BrowserAuth:
    def __init__(self, token, instance, port, clock=time.time):
        self.token, self.clock = token, clock
        self.origin = f"http://127.0.0.1:{port}"
        self.host = f"127.0.0.1:{port}"
        self.cookie = "scout_" + str(port) + "_" + instance.replace("-", "")[:12]
        self.grants, self.sessions, self.lock = {}, {}, threading.Lock()

    def bearer(self, request):
        auth = request.headers.get("authorization", "")
        return auth.startswith("Bearer ") and hmac.compare_digest(auth[7:], self.token)

    def prune(self):
        now = self.clock()
        self.grants = {k: v for k, v in self.grants.items() if v > now}
        self.sessions = {k: v for k, v in self.sessions.items() if v["expires"] > now}

    def issue(self):
        with self.lock:
            self.prune()
            if len(self.grants) >= 128:
                self.grants.pop(next(iter(self.grants)))
            code = secrets.token_urlsafe(32)
            self.grants[code] = self.clock() + 60
            return code

    def exchange(self, code):
        with self.lock:
            self.prune()
            if self.grants.pop(code, None) is None:
                return None
            if len(self.sessions) >= 128:
                self.sessions.pop(next(iter(self.sessions)))
            sid = secrets.token_urlsafe(32)
            session = {"csrf": secrets.token_urlsafe(32), "expires": self.clock() + 8 * 3600}
            self.sessions[sid] = session
            return sid, session

    def session(self, request):
        with self.lock:
            self.prune()
            return self.sessions.get(request.cookies.get(self.cookie, ""))

    async def middleware(self, request, call_next):
        request.state.request_id = uuid.uuid4().hex
        rid = request.state.request_id
        if request.headers.get("host") != self.host:
            return error("INVALID_HOST", "仅允许当前本机地址", 400, rid)
        unsafe = request.method not in ("GET", "HEAD", "OPTIONS")
        origin = request.headers.get("origin")
        if origin and origin != self.origin:
            return error("INVALID_ORIGIN", "不允许跨来源请求", 403, rid)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return error("INVALID_ORIGIN", "不允许跨来源请求", 403, rid)
        path = request.url.path
        public = path in ("/", "/bootstrap", "/v1/health") or path.startswith("/static/")
        exchange = path == "/v1/session/exchange"
        if exchange:
            if origin != self.origin:
                return error("INVALID_ORIGIN", "请从本机启动入口打开", 403, rid)
        elif not public:
            bearer = self.bearer(request)
            session = self.session(request)
            if not bearer and not session:
                return error("AUTH_REQUIRED", "请通过本机启动入口打开页面", 401, rid)
            if unsafe and not bearer:
                if origin != self.origin or not hmac.compare_digest(request.headers.get("x-csrf-token", ""), session["csrf"]):
                    return error("CSRF_REQUIRED", "页面验证已失效，请重新打开", 403, rid)
        response = await call_next(request)
        response.headers.update({
            "X-Request-ID": rid, "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        })
        return response
