import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .db import connect
from .errors import ApiError

log = logging.getLogger("hisaabbol")
app = FastAPI(title="HisaabBol API", version="1.0.0",
              description="Voice-first personal finance tracker backend. Payments log themselves; you say what each was for.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], expose_headers=["Retry-After"])
app.include_router(router)

STATIC = os.path.join(os.path.dirname(__file__), "..", "static")


@app.exception_handler(ApiError)
async def api_error(_: Request, e: ApiError):
    headers = {"Retry-After": str(e.extra["retry_after"])} if "retry_after" in e.extra else None
    return JSONResponse({"error": {"code": e.code, "message": e.message, **e.extra}}, status_code=e.status, headers=headers)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, e: RequestValidationError):
    det = [{"field": ".".join(str(x) for x in err["loc"][1:]), "problem": err["msg"]} for err in e.errors()]
    return JSONResponse({"error": {"code": "validation_error", "message": "Invalid request", "details": det}}, status_code=422)


@app.exception_handler(Exception)
async def unhandled(_: Request, e: Exception):
    log.exception("unhandled error")  # no request bodies are logged (they may contain payment details)
    return JSONResponse({"error": {"code": "internal", "message": "Something went wrong on the server."}}, status_code=500)


@app.middleware("http")
async def access_log(request: Request, call_next):
    t0 = time.time()
    resp = await call_next(request)
    path = request.url.path
    if path.startswith("/api/v1") and not path.endswith("/health"):
        uid = getattr(request.state, "user_id", None)
        if uid:
            try:
                route = request.scope.get("route")
                db = connect()
                db.execute("INSERT INTO api_log(user_id,route,method,status,latency_ms,created_at) VALUES (?,?,?,?,?,?)",
                           (uid, getattr(route, "path", path), request.method, resp.status_code, int((time.time() - t0) * 1000),
                            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
                db.commit(); db.close()
            except Exception:
                pass
    return resp


if os.path.isdir(STATIC):
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    NOCACHE = {"Cache-Control": "no-cache"}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(os.path.join(STATIC, "index.html"), headers=NOCACHE)

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():  # must be served from the root so it can control "/"
        return FileResponse(os.path.join(STATIC, "sw.js"), media_type="text/javascript", headers={**NOCACHE, "Service-Worker-Allowed": "/"})

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        return FileResponse(os.path.join(STATIC, "manifest.webmanifest"), media_type="application/manifest+json", headers=NOCACHE)
