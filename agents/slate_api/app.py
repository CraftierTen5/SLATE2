"""HTTP adapter over slate_core, following contracts/api-contracts.md.

Separate from backend/ on purpose (that folder holds the teammate's DB/server setup, PR #4).

Built up feature by feature: the shell (middleware, error handlers, create_app)
plus the resume intake / skill review routes. Later slices mount their own routes.
"""
import os, sys
from contextlib import nullcontext
from typing import Optional
from fastapi import APIRouter, FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictBool

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
from slate_core.resume import ParseError, extract_pdf_text, MAX_PDF_BYTES  # noqa: E402

STATUS = {"resume_not_found": 404, "resume_unreadable": 422}  # feature slices append their codes

class ResumeIn(BaseModel):
    text: str = Field(max_length=200_000)  # plain text for now; PDF upload is an open question in the contract

class SkillReviewIn(BaseModel):
    skills: list[str] = Field(max_length=64)
    confirm: StrictBool

def _mount(r: APIRouter, get_svc):
    """The one route table. get_svc(request) -> SlateService decides whose data
    the call touches; the authenticated app derives it from the bearer token."""

    @r.post("/resume")
    def resume(request: Request, b: ResumeIn):
        with get_svc(request) as svc: return svc.upload_resume(b.text)

    @r.post("/resume/pdf")
    def resume_pdf(request: Request, file: UploadFile = File(...)):
        with get_svc(request) as svc:  # authenticate BEFORE touching the upload
            # FastAPI runs sync endpoints in its worker pool. Never hold the
            # blocking per-user lock while awaiting on the event loop.
            data = file.file.read(MAX_PDF_BYTES + 1)
            if len(data) > MAX_PDF_BYTES:
                raise SlateError("resume_unreadable", "PDF is too large (5 MB max).")
            try:
                text = extract_pdf_text(data)
            except ParseError as e:
                raise SlateError("resume_unreadable", str(e))
            result = svc.upload_resume(text)
            result["sourceText"] = text
            result["sourceTextKind"] = "original_uploaded_text_not_user_addendum"
            return result

    @r.get("/resume")
    def list_resumes(request: Request):
        with get_svc(request) as svc: return svc.list_resumes()

    @r.get("/resume/{rid}")
    def get_resume(request: Request, rid: str):
        with get_svc(request) as svc: return svc.get_resume(rid)

    @r.post("/resume/{rid}/skills/review")
    def review_skills(request: Request, rid: str, b: SkillReviewIn):
        with get_svc(request) as svc: return svc.review_resume_skills(rid, b.skills, b.confirm)

    @r.get("/jobs")
    def jobs(request: Request, query: str = "", location: str = "", resumeId: Optional[str] = None):
        with get_svc(request) as svc: return svc.jobs(query, location, resumeId)



def _shell(r: APIRouter) -> FastAPI:
    app = FastAPI(title="Slate API (core adapter)")
    from .request_limits import RequestBodyLimit
    app.add_middleware(RequestBodyLimit)
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
