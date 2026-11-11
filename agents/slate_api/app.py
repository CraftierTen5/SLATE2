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
from fastapi.responses import JSONResponse, PlainTextResponse, FileResponse  # FileResponse: interview feature page
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
from slate_core.auth import AuthError  # noqa: E402
from slate_core.resume import ParseError, extract_pdf_text, MAX_PDF_BYTES  # noqa: E402

STATUS = {"resume_not_found": 404, "job_not_found": 404, "draft_not_found": 404,
          "resume_unreadable": 422, "invalid_decision": 422,
          "role_unknown": 404,
          "draft_not_approved": 403, "draft_rejected": 409, "unsupported_claim": 422}  # feature slices append their codes
STATUS.update(unauthenticated=401, invalid_token=401, auth_not_configured=503, state_conflict=409)
STATUS.setdefault("invalid_target", 422)
STATUS.setdefault("invalid_source_preservation", 422)
STATUS.setdefault("target_not_found", 404)
STATUS.setdefault("demo_reset_disabled", 403)
STATUS.setdefault("reset_not_confirmed", 422)
STATUS.setdefault("ai_not_configured", 503)  # appended, so sibling PRs editing the dict do not collide
# --- Profile feature ---
STATUS.setdefault("profile_not_confirmed", 422)
STATUS.setdefault("invalid_profile", 422)
# --- End profile feature ---
# --- Role-fit guardrail ---
STATUS.setdefault("role_change_needs_acknowledgment", 409)
# --- End role-fit guardrail ---
# --- Interview feature ---
STATUS.setdefault("session_not_found", 404)
STATUS.setdefault("mode_unsupported", 422)
STATUS.setdefault("answer_empty", 422)
STATUS.setdefault("interview_complete", 409)
STATUS.setdefault("interview_ended", 409)
# --- End interview feature ---

class ResumeIn(BaseModel):
    text: str = Field(max_length=200_000)  # plain text for now; PDF upload is an open question in the contract

class SkillReviewIn(BaseModel):
    skills: list[str] = Field(max_length=64)
    confirm: StrictBool

# --- Profile feature ---
class ProfileIn(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict, max_length=16)
    confirm: StrictBool
# --- End profile feature ---

class TargetIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    organization: str = Field(default="", max_length=160)
    rawText: str = Field(min_length=1, max_length=20_000)
    sourceUrl: str = Field(default="", max_length=2000)
    parentTargetId: Optional[str] = None

class TargetTailorIn(BaseModel):
    resumeId: str
    targetId: str
    acknowledgeRoleChange: StrictBool = False  # role-fit guardrail


class TailorIn(BaseModel):
    resumeId: str
    jobId: str
    acknowledgeRoleChange: StrictBool = False  # role-fit guardrail

class RoadmapIn(BaseModel):
    resumeId: str
    targetRole: str


class EditIn(BaseModel):
    tailoredResume: Optional[str] = None
    coverNote: Optional[str] = None

class ApprovalIn(BaseModel):
    draftId: str
    decision: str

# --- Interview feature ---
class MockIn(BaseModel):
    targetRole: str = Field(min_length=1, max_length=120)
    mode: str = "text"
    resumeId: Optional[str] = None

class AnswerIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    deliveryMetrics: Optional[dict] = None
# --- End interview feature ---


class ResetIn(BaseModel):
    confirm: str = ""

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

    # --- Profile feature ---
    @r.get("/profile")
    def get_profile(request: Request):
        with get_svc(request) as svc: return svc.get_profile()

    @r.get("/profile/suggestions")
    def profile_suggestions(request: Request, resumeId: str):
        with get_svc(request) as svc: return svc.profile_suggestions(resumeId)

    @r.post("/profile")
    def save_profile(request: Request, b: ProfileIn):
        with get_svc(request) as svc: return svc.save_profile(b.answers, b.confirm)
    # --- End profile feature ---

    @r.get("/jobs")
    def jobs(request: Request, query: str = "", location: str = "", resumeId: Optional[str] = None):
        with get_svc(request) as svc: return svc.jobs(query, location, resumeId)

    @r.post("/targets")
    def create_target(request: Request, b: TargetIn):
        with get_svc(request) as svc:
            return svc.create_target(b.title, b.organization, b.rawText, b.sourceUrl, b.parentTargetId)

    @r.get("/targets")
    def list_targets(request: Request):
        with get_svc(request) as svc: return svc.list_targets()

    @r.get("/targets/{target_id}")
    def get_target(request: Request, target_id: str):
        with get_svc(request) as svc: return svc.get_target(target_id)

    @r.post("/tailor/target")
    def tailor_target(request: Request, b: TargetTailorIn):
        with get_svc(request) as svc: return svc.tailor_target(b.resumeId, b.targetId, b.acknowledgeRoleChange)


    @r.post("/tailor")
    def tailor(request: Request, b: TailorIn):
        with get_svc(request) as svc: return svc.tailor(b.resumeId, b.jobId, b.acknowledgeRoleChange)

    @r.post("/tailor/ai")
    def tailor_ai(request: Request, b: TailorIn):
        # Opt-in AI drafting: off unless the server has a key AND the service supports it.
        with get_svc(request) as svc:  # authenticate first
            fn = getattr(svc, "tailor_ai", None)
            if fn is None or not os.getenv("LLM_API_KEY"):
                raise SlateError("ai_not_configured",
                                 "AI tailoring is off on this server. Set LLM_API_KEY to enable it.")
            return fn(b.resumeId, b.jobId, acknowledge_role_change=b.acknowledgeRoleChange)

    @r.get("/drafts")
    def list_drafts(request: Request):
        with get_svc(request) as svc: return svc.list_drafts()

    @r.get("/drafts/{draft_id}")
    def get_draft(request: Request, draft_id: str):
        with get_svc(request) as svc: return svc.get_draft(draft_id)

    @r.get("/drafts/{draft_id}/download")
    def download(request: Request, draft_id: str):
        with get_svc(request) as svc:
            text = svc.download_draft(draft_id)
            # Generated ids are not accepted as arbitrary header text.
            import re
            safe = re.sub(r"[^A-Za-z0-9_-]", "_", draft_id)[:80]
            return PlainTextResponse(text, headers={"Content-Disposition": 'attachment; filename="slate-' + safe + '.txt"'})

    @r.post("/drafts/{draft_id}/edit")
    def edit(request: Request, draft_id: str, b: EditIn):
        with get_svc(request) as svc: return svc.edit_draft(draft_id, **b.model_dump(exclude_none=True))

    @r.get("/drafts/{draft_id}/export")
    def export(request: Request, draft_id: str):
        with get_svc(request) as svc: return svc.export_draft(draft_id)

    @r.post("/roadmap")
    def roadmap(request: Request, b: RoadmapIn):
        with get_svc(request) as svc: return svc.roadmap(b.resumeId, b.targetRole)

    @r.post("/approvals")
    def approvals(request: Request, b: ApprovalIn):
        with get_svc(request) as svc: return svc.decide(b.draftId, b.decision)



    # --- Interview feature ---
    @r.get("/config")
    def config():
        """What the login UI needs. Client ids / anon keys are public by design;
        this endpoint exposes no user data and needs no token. Token
        verification is enforced in create_authenticated_app. create_app is
        single-tenant test-fixture mode only."""
        gid = os.getenv("GOOGLE_CLIENT_ID")
        surl, skey = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_ANON_KEY")
        if gid:
            return {"mode": "google", "googleClientId": gid}
        if surl and skey:
            return {"mode": "supabase", "supabaseUrl": surl, "supabaseAnonKey": skey}
        if os.getenv("SLATE_DEV_AUTH") == "1":
            return {"mode": "dev"}
        return {"mode": "unconfigured"}

    @r.post("/interview/mock")
    def mock(request: Request, b: MockIn):
        with get_svc(request) as svc:
            return svc.start_interview(b.targetRole, b.mode, b.resumeId)

    @r.post("/interview/{sid}/answer")
    def answer(request: Request, sid: str, b: AnswerIn):
        with get_svc(request) as svc:
            return svc.answer_interview(sid, b.text, b.deliveryMetrics)

    @r.post("/interview/{sid}/end")
    def end_interview(request: Request, sid: str):
        with get_svc(request) as svc:
            return svc.end_interview(sid)

    @r.get("/interview/{sid}/feedback")
    def feedback(request: Request, sid: str):
        with get_svc(request) as svc:
            return svc.interview_feedback(sid)
    # --- End interview feature ---


    @r.post("/demo/reset")
    def demo_reset(request: Request, b: ResetIn):
        # Off unless the local demo server opts in: SLATE_DEMO_RESET=1 uvicorn ...
        # In the authenticated app this wipes ONLY the caller's own data.
        if os.getenv("SLATE_DEMO_RESET") != "1":
            raise SlateError("demo_reset_disabled",
                             "Demo reset is off. Start the local demo with SLATE_DEMO_RESET=1 to enable it.")
        with get_svc(request) as svc: return svc.reset_demo(b.confirm)


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

    @app.exception_handler(AuthError)
    async def _auth(_: Request, e: AuthError):
        return JSONResponse({"error": {"code": e.code, "message": e.message}}, status_code=STATUS.get(e.code, 401))

    @app.exception_handler(RequestValidationError)
    async def _val(_: Request, e: RequestValidationError):
        return JSONResponse({"error": {"code": "bad_request", "message": "Request body or query is invalid."}}, status_code=422)

    # --- Interview feature ---
    web_root = os.path.join(os.path.dirname(__file__), "..", "..", "web")
    web_interview = os.path.join(web_root, "interview.html")
    web_index = os.path.join(web_root, "index.html")
    web_ai = os.path.join(web_root, "ai.html")

    @app.get("/resume", include_in_schema=False)
    @app.get("/targets", include_in_schema=False)
    @app.get("/draft", include_in_schema=False)
    @app.get("/comparisons", include_in_schema=False)
    @app.get("/roadmap", include_in_schema=False)
    @app.get("/", include_in_schema=False)
    def index_page():
        return FileResponse(web_index)

    @app.get("/ai", include_in_schema=False)
    def ai_page():
        return FileResponse(web_ai)


    @app.get("/interview", include_in_schema=False)
    def interview_page():
        return FileResponse(web_interview) if os.path.exists(web_interview) else JSONResponse({"message": "Interview page not found"})
    # --- End interview feature ---

    return app


def create_app(service: Optional[SlateService] = None) -> FastAPI:
    """Test-fixture mode: single tenant, no auth. The served app never uses this."""
    svc = service or SlateService()
    r = APIRouter(prefix="/v1")
    _mount(r, lambda request: nullcontext(svc))
    return _shell(r)


def create_authenticated_app(auth, user_store, llm_client=None) -> FastAPI:
    """The production construction: bearer token -> verified user -> that user's
    service, built fresh per request from the per-user store. A user id is never
    read from the request; demo reset wipes only the caller's own data."""
    from contextlib import contextmanager
    from slate_core.ai_service import AISlateService
    from slate_core.user_store import WriteConflict
    from .user_snapshot import RequestSnapshot, request_locked

    @contextmanager
    def get_svc(request: Request):
        if auth is None:
            raise SlateError("auth_not_configured",
                             "Sign-in is not configured on this server. Set GOOGLE_CLIENT_ID "
                             "(or SUPABASE_URL + SUPABASE_ANON_KEY), or SLATE_DEV_AUTH=1 for local dev.")
        user = auth.authenticate(request.headers.get("authorization"))
        with request_locked(user.id):  # separate from stores' own locks; avoids nested-lock deadlock
            try:
                yield AISlateService(RequestSnapshot(user_store, user.id), llm_client=llm_client)
            except WriteConflict:
                raise SlateError("state_conflict", "Your saved data changed in another request. Nothing from this request was saved. Reopen the latest version and try again.") from None

    r = APIRouter(prefix="/v1")

    _mount(r, get_svc)
    return _shell(r)

def _build_auth():
    """Exactly one provider. A real provider always wins over the dev flag, so a
    misconfigured deployment cannot silently fall into dev sign-in."""
    from slate_core.auth import DevAuth, GoogleAuth, SupabaseAuth
    gid = os.getenv("GOOGLE_CLIENT_ID")
    surl, skey = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_ANON_KEY")
    if gid:
        return GoogleAuth(gid)
    if surl and skey:
        return SupabaseAuth(surl, skey)
    if os.getenv("SLATE_DEV_AUTH") == "1":
        return DevAuth()
    return None  # app still imports/serves pages; /v1 data calls answer 503

def _build_store():
    from slate_core.user_store import MemUserStore, SqlUserStore
    url = os.getenv("SLATE_STATE_URL")  # postgres (TLS) in production; sqlite locally; unset = ephemeral
    return SqlUserStore(url) if url else MemUserStore()

app = create_authenticated_app(_build_auth(), _build_store())
