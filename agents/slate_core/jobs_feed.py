"""Live job listings from public ATS board endpoints (the feature-3 jobs feed).

Sources are public, keyless read endpoints, each verified reachable on
2026-11-11 with India-based or remote-friendly listings at that time:

- Lever Postings API: GET https://api.lever.co/v0/postings/{site}?mode=json
  Official docs (github.com/lever/postings-api README): reads need no key;
  the only documented rate limit is 2 application POST requests/second, and
  this feature only ever GETs.
- Greenhouse Job Board API: GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs
  Official docs (developers.greenhouse.io, Job Board API): "Job Board data is
  publicly available, so authentication is not required for any GET endpoints."
  Only the application-submission POST needs auth, and this feature never POSTs.

Boundaries (enforced here, stated in contracts/api-contracts.md):
- Fetches are plain GETs of fixed board URLs. No resume text, profile answer,
  or any other user data ever leaves this server: there is no code path that
  could send it, only a URL from BOARDS.
- Deadlines are never fabricated. Boards publish posting dates, not
  application deadlines, so feed listings carry deadline=None and freshness
  comes from the existing curation layer (observed-present semantics).
- Apply links are the original posting URLs on the employer's own board.
- Refresh is bounded: each board is refetched at most once per
  REFRESH_SECONDS. A failed refresh serves the last good data labeled stale;
  a board that has never loaded contributes nothing and reports its error.
  The feed NEVER falls back to sample fixtures: live and sample listings are
  separate lists, always labeled.

Seed boards below are starting points verified on 2026-11-11 (listing counts
and India/remote fit noted from that day's fetch); edit freely - a board that
stops responding is reported in the feed status, not hidden.
"""
import json, threading, urllib.request
from datetime import datetime, timezone

from .sample_data import KNOWN_SKILLS

REFRESH_SECONDS = 3600  # at most one refetch per board per hour

BOARDS = [
    # Lever boards (api.lever.co/v0/postings/{board}?mode=json)
    {"source": "lever", "board": "meesho", "company": "Meesho"},      # 49 listings, 48 in India
    {"source": "lever", "board": "zeta", "company": "Zeta"},          # 28 listings, 23 in India
    {"source": "lever", "board": "cred", "company": "CRED"},          # 14 listings, 13 in India
    # Greenhouse boards (boards-api.greenhouse.io/v1/boards/{board}/jobs)
    {"source": "greenhouse", "board": "stripe", "company": "Stripe"},     # 779, 44 India + remote
    {"source": "greenhouse", "board": "gitlab", "company": "GitLab"},     # 252, 35 India incl Remote-India
    {"source": "greenhouse", "board": "coinbase", "company": "Coinbase"}, # 286, 11 India + remote
    {"source": "greenhouse", "board": "canonical", "company": "Canonical"},  # 316, remote (Home Based)
]

USER_AGENT = "SLATE/1.0 (student project; https://github.com/Suieey/SLATE)"


def board_url(board) -> str:
    if board["source"] == "lever":
        return "https://api.lever.co/v0/postings/%s?mode=json" % board["board"]
    if board["source"] == "greenhouse":
        return "https://boards-api.greenhouse.io/v1/boards/%s/jobs" % board["board"]
    raise ValueError("unknown board source: %r" % (board["source"],))


def fetch_json(url: str, timeout: float = 6.0):
    """Plain GET of one fixed board URL. No user data is ever attached."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _plain(html_or_text) -> str:
    import re
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_or_text or "")).strip()


def extract_skills(text):
    """Skills literally named in the text, from the repo's known-skill list.

    These are extracted mentions, not the employer's structured skill list;
    the listing keeps that provenance in `skillsKind`.
    """
    import re
    norm = " " + re.sub(r"[^a-z0-9+#]+", " ", (text or "").lower()) + " "
    return [s for s in KNOWN_SKILLS if " " + s + " " in norm]


def _iso_from_ms(ms) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def normalize_lever(board, data, fetched_at) -> list:
    out = []
    for p in data if isinstance(data, list) else []:
        cats = p.get("categories") or {}
        loc = cats.get("location") or "Not stated"
        if (p.get("workplaceType") or "").lower() == "remote" and "remote" not in loc.lower():
            loc = "Remote" if loc == "Not stated" else loc + " (Remote)"
        updated = p.get("updatedAt") or p.get("createdAt")
        out.append({
            "jobId": "lever-%s-%s" % (board["board"], p.get("id")),
            "source": "lever", "sourceId": str(p.get("id")),
            "company": board["company"], "companyBoard": board["board"],
            "title": p.get("text") or "(untitled)",
            "location": loc,
            "deadline": None,  # boards state posting dates, never deadlines
            "url": p.get("hostedUrl") or "",
            "skills": extract_skills((p.get("text") or "") + " " + _plain(p.get("descriptionPlain"))),
            "skillsKind": "extracted_mentions_not_employer_structured",
            "updatedAt": _iso_from_ms(updated) if isinstance(updated, (int, float)) else None,
            "fetchedAt": fetched_at,
        })
    return out


def normalize_greenhouse(board, data, fetched_at) -> list:
    out = []
    for j in (data or {}).get("jobs", []):
        out.append({
            "jobId": "greenhouse-%s-%s" % (board["board"], j.get("id")),
            "source": "greenhouse", "sourceId": str(j.get("id")),
            "company": board["company"], "companyBoard": board["board"],
            "title": j.get("title") or "(untitled)",
            "location": (j.get("location") or {}).get("name") or "Not stated",
            "deadline": None,  # boards state posting dates, never deadlines
            "url": j.get("absolute_url") or "",
            "skills": extract_skills((j.get("title") or "") + " " + _plain(j.get("content"))),
            "skillsKind": "extracted_mentions_not_employer_structured",
            "updatedAt": j.get("updated_at"),
            "fetchedAt": fetched_at,
        })
    return out


NORMALIZERS = {"lever": normalize_lever, "greenhouse": normalize_greenhouse}


class FeedCache:
    """Bounded-refresh cache over the seed boards.

    One refetch per board per REFRESH_SECONDS at most. A failed refresh keeps
    the last good listings (labeled stale in the status); a board that never
    loaded contributes nothing and reports its error. The feed never falls
    back to fixtures.
    """

    def __init__(self, boards=None, fetcher=None, refresh_seconds=REFRESH_SECONDS):
        self._boards = list(boards if boards is not None else BOARDS)
        self._fetch = fetcher or fetch_json
        self._refresh = refresh_seconds
        self._listings, self._fetched_at = {}, {}
        self._last_attempt, self._errors = {}, {}
        self._lock = threading.Lock()

    def _refresh_due(self, now):
        now_iso = now.isoformat()
        for b in self._boards:
            last = self._last_attempt.get(b["board"])
            if last and (now - last).total_seconds() < self._refresh:
                continue
            self._last_attempt[b["board"]] = now
            try:
                data = self._fetch(board_url(b))
                self._listings[b["board"]] = NORMALIZERS[b["source"]](b, data, now_iso)
                self._fetched_at[b["board"]] = now_iso
                self._errors.pop(b["board"], None)
            except Exception as e:  # network, HTTP, JSON, shape: serve stale if any
                self._errors[b["board"]] = "%s: %s" % (type(e).__name__, e)

    def listings(self, now=None):
        """(current live listings, feed status). Never raises for board failures."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            self._refresh_due(now)
            boards = []
            for b in self._boards:
                got = self._listings.get(b["board"], [])
                err = self._errors.get(b["board"])
                boards.append({"source": b["source"], "board": b["board"],
                               "company": b["company"], "count": len(got),
                               "fetchedAt": self._fetched_at.get(b["board"]),
                               "stale": bool(err and got), "error": err})
            out = [l for b in self._boards for l in self._listings.get(b["board"], [])]
            status = {"boards": boards,
                      "totalListings": len(out),
                      "available": bool(out),
                      "anyStale": any(b["stale"] for b in boards),
                      "refreshSeconds": self._refresh,
                      "sourceKind": "live_public_boards_lever_greenhouse"}
            return out, status

    def lookup(self, job_id):
        """One cached listing by id, without triggering a refresh (or None)."""
        with self._lock:
            for items in self._listings.values():
                for l in items:
                    if l["jobId"] == job_id:
                        return l
        return None


_DEFAULT_FEED = None
_DEFAULT_LOCK = threading.Lock()


def default_feed() -> FeedCache:
    """The one process-wide cache of PUBLIC board listings.

    Listings are not user data, so every per-user service shares one cache:
    a listing loaded by the jobs route must be findable by the tailor route's
    fresh service instance, and N users must never cause N upstream fetches.
    """
    global _DEFAULT_FEED
    with _DEFAULT_LOCK:
        if _DEFAULT_FEED is None:
            _DEFAULT_FEED = FeedCache()
        return _DEFAULT_FEED
