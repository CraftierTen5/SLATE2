# Web workspace

Plain HTML/CSS/JavaScript pages served by `agents.slate_api.app:app`.
Run the API with an auth provider configured, or use `SLATE_DEV_AUTH=1` only for local development.
The workspace preserves source text, separates targets from evidence, and requires human approval before export.
No database URL means ephemeral per-user memory; set `SLATE_STATE_URL` for durable state.
