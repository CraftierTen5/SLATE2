"""HTTP adapter over slate_core, following contracts/api-contracts.md.

Separate from backend/ on purpose (that folder holds the teammate's DB/server setup, PR #4).

Built up feature by feature: this initial version carries only the app shell
(middleware, error handlers, create_app). Feature slices mount their /v1 routes
in _mount and serve their pages from _shell.
"""
import os, sys
from contextlib import nullcontext
from typing import Optional
from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# Load local environment files without overriding values already set by the shell.
try:
    from dotenv import load_dotenv
    _ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    load_dotenv(os.path.join(_ROOT, ".env"))
    load_dotenv(os.path.join(_ROOT, "backend", ".env"))
except ImportError:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from slate_core import SlateService, SlateError  # noqa: E402

STATUS = {}  # feature slices append their error codes


def _mount(r: APIRouter, get_svc):
    """Feature slices add their /v1 routes here."""


def _shell(r: APIRouter) -> FastAPI:
    app = FastAPI(title="Slate API (core adapter)")
    app.include_router(r)

    @app.middleware("http")
    async def private_api_responses(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/v1/") or request.url.path == "/v1":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(SlateError)
    async def _slate(_: Request, e: SlateError):
        return JSONResponse(e.to_dict(), status_code=STATUS.get(e.code, 400))

    @app.exception_handler(RequestValidationError)
    async def _val(_: Request, e: RequestValidationError):
        return JSONResponse({"error": {"code": "bad_request", "message": "Request body or query is invalid."}}, status_code=422)

    return app


def create_app(service: Optional[SlateService] = None) -> FastAPI:
    """Test-fixture mode: single tenant, no auth. The served app never uses this."""
    svc = service or SlateService()
    r = APIRouter(prefix="/v1")
    _mount(r, lambda request: nullcontext(svc))
    return _shell(r)
