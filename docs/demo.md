# Running the MVP demo locally

Needs Python 3.10+. From the repo root:

    python3 -m venv .venv && . .venv/bin/activate
    pip install -r backend/requirements.txt
    pip install httpx pytest
    python -m pytest tests -q
    SLATE_DEV_AUTH=1 SLATE_STATE_URL=sqlite:///slate_state.db \
      uvicorn slate_api.app:app --app-dir agents --port 8000

Open http://localhost:8000 (the classic page) or http://localhost:8000/ai (opt-in AI draft page).
Both pages ask you to sign in first; in `SLATE_DEV_AUTH=1` mode enter any email - this is a local
dev identity so the multi-user behavior can be tried without any external account. It is NOT
security: never run a deployed server this way.

Every `/v1` data call needs a bearer token (`/v1/config` is public) and only ever touches the signed-in user's own data:
resumes, drafts/approvals, interview sessions and roadmap are scoped per user and stored per user,
so two people can use the same server without seeing each other's data, and each person's data
survives a restart (with `SLATE_STATE_URL` set; unset = in-memory and lost on restart).

## Sign-in modes

The served app picks exactly one, from the environment:

| Env | Mode |
| --- | --- |
| `GOOGLE_CLIENT_ID` | Real Google sign-in (verifies Google ID tokens server-side; needs `pip install google-auth`) |
| `SUPABASE_URL` + `SUPABASE_ANON_KEY` | Supabase Auth (managed variant; currently on hold) |
| `SLATE_DEV_AUTH=1` | Local dev identity, no security - local runs/tests only |
| none of the above | API stays up but `/v1` data calls answer 503 `auth_not_configured` |

A real provider always wins over the dev flag, so a misconfigured deploy cannot fall into dev sign-in.

## Runtime surfaces

The working API is `agents/slate_api/app.py`; the website and stdlib CLI use
its `/v1` routes. `backend/main.py` is a separate health/setup endpoint only.
`backend/docker-compose.yml` is optional local PostgreSQL scaffolding, not
proof of a connected database or a production deployment.

## Persistence and security, honestly

`SLATE_STATE_URL` selects a SQLAlchemy store. Validation targets are SQLite
and PostgreSQL; do not infer support for arbitrary dialects or collations.
Each user's state is one JSON document in a per-user row (`slate_user_state`).
SQLite restart durability, isolation and spawned-process conflict races have
been tested. A live PostgreSQL setup has not been run.

Same-user HTTP requests are serialized by a separate per-user request lock
in ONE process. The authenticated request adapter also uses atomic database
compare-and-set against the exact loaded JSON text, detecting stale writes
across processes. A conflict returns409 and does not automatically replay a
mutation or a model call. The store's `UserSnapshot` facade is an unconditional
legacy helper; authenticated routes use `RequestSnapshot` instead. Memory
state is single-process and lost on restart. Input caps:200 KB resume text,
5 MB PDF,8 KB tokens.

Google sign-in (when configured) is stateless: the ID token is verified per request (signature,
issuer, audience, expiry via google-auth) and the user id is the token's `sub`. There is no session
store, so sign-out is client-side and a stolen token works until it expires (~1h, Google's clock).
The token lives in sessionStorage: any successful XSS on our pages could read it.

## Limits

Sample jobs only. The claim check is rule based and catches unsupported skills, inflated
years/months, unlisted percentages, GPA values and degrees; it does not catch paraphrase or invented
employers or projects. AI drafts add mechanical grounding checks (citations to resume/job blocks);
still not a fact check. Interview coaching uses Gemini when configured and available, otherwise a labeled deterministic fallback. Browser microphone/camera and live providers were not validated in this rebuild. Nothing was deployed.
