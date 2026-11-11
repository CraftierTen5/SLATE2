"""Facade returning the contract shapes (contracts/api-contracts.md), errors in one shape.

Built up feature by feature: this initial version carries only the shared error type
and the state-persistence plumbing that each feature slice extends.
"""

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
