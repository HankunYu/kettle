"""HTTP API and web UI."""

import hmac
import ipaddress
import json
import re
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import service, store
from .config import WEB_DIR, ConfigError, load_config
from .jobs import JobRunner
from .scheduler import Scheduler

MAX_BODY = 64 * 1024


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _is_loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class Api:
    """Route table and handlers. Handlers return (status, payload)."""

    def __init__(self, jobs, scheduler):
        self.jobs = jobs
        self.scheduler = scheduler
        self.routes = [
            ("GET", r"/api/questions", self.list_questions),
            ("POST", r"/api/questions", self.add_question),
            ("PATCH", r"/api/questions/(?P<qid>[^/]+)", self.update_question),
            ("DELETE", r"/api/questions/(?P<qid>[^/]+)", self.delete_question),
            ("POST", r"/api/questions/(?P<qid>[^/]+)/probe", self.probe),
            ("POST", r"/api/questions/(?P<qid>[^/]+)/reset", self.reset),
            ("GET", r"/api/questions/(?P<qid>[^/]+)/history", self.history),
            ("POST", r"/api/analyze", self.analyze),
            ("GET", r"/api/jobs", self.list_jobs),
            ("GET", r"/api/jobs/(?P<job_id>[^/]+)", self.get_job),
            ("GET", r"/api/schedule", self.get_schedule),
        ]

    def dispatch(self, method, path, query, body):
        allowed = False
        for route_method, pattern, handler in self.routes:
            m = re.fullmatch(pattern, path)
            if not m:
                continue
            allowed = True
            if route_method == method:
                return handler(body=body, query=query, **m.groupdict())
        if allowed:
            raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, f"{method} not allowed on {path}")
        raise ApiError(HTTPStatus.NOT_FOUND, f"no route: {path}")

    @staticmethod
    def _question_or_404(qid):
        q = store.get_question(qid)
        if q is None:
            raise ApiError(HTTPStatus.NOT_FOUND, f"未找到问题 id: {qid}")
        return q

    def list_questions(self, **_):
        return HTTPStatus.OK, {"questions": service.list_views()}

    def add_question(self, body, **_):
        q = store.add_question({
            "id": body.get("id"),
            "question": body.get("question", ""),
            "criteria": body.get("criteria", ""),
        })
        return HTTPStatus.CREATED, {"question": service.question_view(q)}

    def update_question(self, qid, body, **_):
        self._question_or_404(qid)
        q = store.update_question(qid, {k: v for k, v in body.items() if k in store.EDITABLE_FIELDS})
        return HTTPStatus.OK, {"question": service.question_view(q)}

    def delete_question(self, qid, **_):
        self._question_or_404(qid)
        store.delete_question(qid)
        return HTTPStatus.OK, {"deleted": qid}

    def probe(self, qid, body, **_):
        q = self._question_or_404(qid)
        running = self.jobs.active_for("probe", "id", qid)
        if running:
            return HTTPStatus.ACCEPTED, {"job": running}
        do_notify = bool(body.get("notify", True))

        def task():
            outcome = service.probe_one(load_config(), q, do_notify=do_notify)
            if "error" in outcome:
                raise RuntimeError(outcome["error"])
            return outcome

        return HTTPStatus.ACCEPTED, {"job": self.jobs.submit("probe", {"id": qid}, task)}

    def reset(self, qid, **_):
        q = self._question_or_404(qid)
        service.reset(qid)
        return HTTPStatus.OK, {"question": service.question_view(q)}

    def history(self, qid, query, **_):
        self._question_or_404(qid)
        try:
            limit = int(query.get("limit", ["50"])[0])
        except ValueError:
            raise ApiError(HTTPStatus.BAD_REQUEST, "limit 必须是整数") from None
        return HTTPStatus.OK, {"history": store.read_history(qid, limit)}

    def analyze(self, body, **_):
        intent = str(body.get("intent", "")).strip()
        if not intent:
            raise ApiError(HTTPStatus.BAD_REQUEST, "缺少字段: intent")
        do_notify = bool(body.get("notify", True))
        job = self.jobs.submit(
            "analyze",
            {"intent": intent},
            lambda: service.analyze_and_add(load_config(), intent, do_notify=do_notify),
        )
        return HTTPStatus.ACCEPTED, {"job": job}

    def list_jobs(self, **_):
        return HTTPStatus.OK, {"jobs": self.jobs.list()}

    def get_job(self, job_id, **_):
        job = self.jobs.get(job_id)
        if job is None:
            raise ApiError(HTTPStatus.NOT_FOUND, f"未找到 job: {job_id}")
        return HTTPStatus.OK, {"job": job}

    def get_schedule(self, **_):
        return HTTPStatus.OK, {"schedule": self.scheduler.status()}


def make_handler(api, token):
    class Handler(BaseHTTPRequestHandler):
        server_version = "kettle"

        def _send(self, status, payload):
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self):
            if not token:
                return True
            supplied = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            return hmac.compare_digest(supplied.encode(), token.encode())

        def _read_body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body too large")
            if not length:
                return {}
            try:
                body = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise ApiError(HTTPStatus.BAD_REQUEST, "body 必须是 JSON") from None
            if not isinstance(body, dict):
                raise ApiError(HTTPStatus.BAD_REQUEST, "body 必须是 JSON object")
            return body

        def _serve_index(self):
            data = (WEB_DIR / "index.html").read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _handle(self, method):
            url = urlparse(self.path)
            path = url.path.rstrip("/") or "/"
            if method == "GET" and path in ("/", "/index.html"):
                return self._serve_index()
            try:
                if not path.startswith("/api/"):
                    raise ApiError(HTTPStatus.NOT_FOUND, f"no route: {path}")
                if not self._authorized():
                    raise ApiError(HTTPStatus.UNAUTHORIZED, "token 无效")
                body = self._read_body() if method in ("POST", "PATCH") else {}
                status, payload = api.dispatch(method, path, parse_qs(url.query), body)
            except ApiError as e:
                status, payload = e.status, {"error": str(e)}
            except store.StoreError as e:
                status, payload = HTTPStatus.BAD_REQUEST, {"error": str(e)}
            except Exception as e:
                print(f"{method} {path} failed: {e!r}", file=sys.stderr)
                status, payload = HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(e)}
            self._send(status, payload)

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_PATCH(self):
            self._handle("PATCH")

        def do_DELETE(self):
            self._handle("DELETE")

        def log_message(self, fmt, *args):
            print(f"{self.address_string()} {fmt % args}", file=sys.stderr)

    return Handler


def serve(host=None, port=None):
    try:
        cfg = load_config()
    except ConfigError as e:
        sys.exit(str(e))
    server_cfg = cfg.get("server", {})
    host = host or server_cfg.get("host", "127.0.0.1")
    port = port or server_cfg.get("port", 8730)
    token = server_cfg.get("token", "")
    if not token and not _is_loopback(host):
        sys.exit(f"监听非本机地址 {host} 时必须在 config.toml 的 [server] 里设置 token")

    scheduler = Scheduler()
    api = Api(JobRunner(workers=server_cfg.get("workers", 1)), scheduler)
    httpd = ThreadingHTTPServer((host, port), make_handler(api, token))
    scheduler.start()
    print(f"kettle web listening on http://{host}:{port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.stop()
        httpd.server_close()
