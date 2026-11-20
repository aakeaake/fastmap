import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from fastmap import __version__
from fastmap.api import routes
from fastmap.api.routes import router
from fastmap.services import mml_source

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Don't let queued renders or tile downloads delay exit; their results die
    # with the process.
    routes.jobs.shutdown()
    mml_source.shutdown_tile_pool()


app = FastAPI(title="FastMap API", version=__version__, lifespan=lifespan)

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
        "%s %s %s  %d",
        request.method,
        request.url.path,
        client,
        resp.status_code,
    )
    return resp


app.include_router(router)


class FrontendFiles(StaticFiles):
    """Static frontend that browsers must revalidate before reusing.

    The UI is plain ES modules with fixed URLs (no build step, no hashed file
    names). Without a Cache-Control header browsers cache them heuristically,
    so after a deploy a page could run a mix of old and new modules.
    "no-cache" keeps the files cached but checks them on every load; with the
    ETag / Last-Modified that StaticFiles already sends, an unchanged file
    costs a 304 with no body. Other files (favicon) keep default caching.
    """

    REVALIDATE = (".html", ".css", ".js", ".mjs")

    def file_response(self, full_path, *args, **kwargs):
        response = super().file_response(full_path, *args, **kwargs)
        if str(full_path).endswith(self.REVALIDATE):
            response.headers["Cache-Control"] = "no-cache"
        return response


_FRONTEND_DIR = os.environ.get(
    "FRONTEND_DIR",
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend")),
)
if os.path.isdir(_FRONTEND_DIR):
    app.mount("/", FrontendFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
