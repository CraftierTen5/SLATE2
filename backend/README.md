# Backend setup

The working Slate API is `agents/slate_api/app.py`, not `backend/main.py`.
From the repository root, install `backend/requirements.txt`, then run:

```sh
SLATE_DEV_AUTH=1 uvicorn slate_api.app:app --app-dir agents --host 127.0.0.1
```

Local development auth must never be used on a public server. For a real
provider configure Google or Supabase as described in `docs/demo.md`.
Without `SLATE_STATE_URL`, state is ephemeral. A local SQLite URL keeps state
across restarts. SQLite persistence, isolation and process-level CAS races are
tested. A live PostgreSQL connection has not been validated in this rebuild.

`backend/main.py` is a separate setup health endpoint. It reports only whether
`DATABASE_URL` is configured; it does not implement Slate or prove a working
database connection. `docker-compose.yml` is optional local PostgreSQL setup.
Its fixed sample credentials are development examples, not production secrets.
Do not expose that database port or reuse those credentials in production.
The app store uses `SLATE_STATE_URL`, not `DATABASE_URL`.

The requirements file lists the local runtime dependencies exercised in this rebuild.
Google sign-in additionally needs `google-auth`, as documented in `docs/demo.md`. Use a virtual
environment; provider availability and external services are not tested by a
successful local dependency installation. Current supported validation targets
are SQLite and PostgreSQL via SQLAlchemy, not arbitrary dialects/collations.
