import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from fastmap.api.routes import router

log = logging.getLogger(__name__)

app = FastAPI(title="FastMap API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith("/api/nls-tiles"):
        return resp
    client = request.client.host if request.client else "?"
    log.info(
        "%s %s %s  %d  %s",
        request.method, request.url.path, client,
        resp.status_code, request.headers.get("user-agent", ""),
    )
    return resp
app.include_router(router)

_FRONTEND_DIR = os.environ.get(
    "FRONTEND_DIR",
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend")),
)
if os.path.isdir(_FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
