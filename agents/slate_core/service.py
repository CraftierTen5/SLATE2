"""Facade returning the contract shapes (contracts/api-contracts.md), errors in one shape.

Built up feature by feature: shared error type and store plumbing, plus the
resume intake / skill review feature. Later slices add their own sections.
"""
from . import jobs as J
from .resume import parse_resume, ParseError

class SlateError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message

    def to_dict(self):
        return {"error": {"code": self.code, "message": self.message}}

class SlateService:
    """One entry point for the copilot core.

    store= is the persistence handoff: any object with load() -> dict | None and
    save(state: dict). State keys are resumes, texts and targets; the drafts and
    interview slices extend the load/save wiring for their own state.
    """
    def __init__(self, store=None):
        self._resumes = {}
        self._texts = {}
        self._targets = {}
        self._store = store
        if store is not None:
            st = store.load()
            if st:
                self._resumes, self._texts = st["resumes"], st["texts"]
                self._targets = st.get("targets", {})

    def _persist(self):
        if self._store is not None:
            self._store.save({"resumes": self._resumes, "texts": self._texts,
                              "targets": self._targets})

    def _resume(self, rid):
        r = self._resumes.get(rid)
        if r is None:
            raise SlateError("resume_not_found", "No resume with that id.")
        return r

    def _upload_resume(self, text) -> dict:
        try:
            parsed = parse_resume(text)
        except ParseError as e:
            raise SlateError("resume_unreadable", str(e))
        rid = f"res_{len(self._resumes) + 1:03d}"
        self._resumes[rid] = parsed
        self._texts[rid] = text
        return {"resumeId": rid, "parsed": parsed}

    def list_resumes(self):
        """Only this service's verified user's snapshots, newest first."""
        return {"totalCount": len(self._resumes), "resumes": [{"resumeId": rid, "name": parsed.get("name", "Unknown"),
                             "reviewStatus": parsed.get("skillReview", {}).get("status", "extracted_candidates"),
                             "parentResumeId": parsed.get("skillReview", {}).get("parentResumeId"),
                             "skillCount": len(parsed.get("skills", []))}
                            for rid, parsed in list(reversed(list(self._resumes.items())))[:100]]}

    def get_resume(self, resume_id):
        import copy
        parsed = self._resume(resume_id)
        original = parsed.get("skillReview", {}).get("originalResumeId", resume_id)
        return {"resumeId": resume_id, "parsed": copy.deepcopy(parsed),
                "sourceText": self._texts[original],
                "sourceTextKind": "original_uploaded_text_not_user_addendum"}

    def review_resume_skills(self, resume_id, skills, confirm=False):
        """A correction is a new immutable source snapshot, never silent reapproval."""
        from .resume_review import reviewed_snapshot
        parent = self._resume(resume_id)
        try:
            parsed = reviewed_snapshot(parent, skills, confirm)
        except ValueError as e:
            raise SlateError("invalid_skill_review", str(e))
        rid = f"res_{len(self._resumes) + 1:03d}"
        root_id = parent.get("skillReview", {}).get("originalResumeId", resume_id)
        original_text = self._texts[root_id]
        parsed["skillReview"] = {"parentResumeId": resume_id, "originalResumeId": root_id,
                               "status": "user_reviewed_not_independently_verified"}
        additions = [e["skill"] for e in parsed["skillEvidence"] if e["source"] == "user_statement"]
        # Additional claims are explicit user statements, not extracted PDF evidence.
        # Keep the original source snapshot intact. AI/draft gates still use the
        # new bound source, which labels the addendum and never implies work history.
        text = original_text + ("\n\nUser-provided skill statements (not independently verified):\nSkills: " + ", ".join(additions) if additions else "")
        self._resumes[rid], self._texts[rid] = parsed, text
        self._persist()
        # Draft invalidation on resume correction arrives with the drafts slice.
        return {"resumeId": rid, "parsed": parsed, "invalidatedDraftIds": []}


    def jobs(self, query="", location="", resume_id=None) -> dict:
        skills = self._resume(resume_id)["skills"] if resume_id else []
        return {"jobs": J.search_jobs(query, location, skills)}

    def upload_resume(self, *a, **k):
        r = self._upload_resume(*a, **k)
        self._persist()
        return r
