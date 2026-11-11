"""Per-user snapshot stores for the Slate state document.

Each user's state is ONE JSON document in one row of `slate_user_state`
(`user_id`, `data`), rewritten after each change. The document is opaque to
the store: keys are `resumes`/`texts`/`targets` now, with `drafts`+`draftN`
and `sessions`+`sessionN` persisted by the slices that own them.

The concurrency path is document-value compare-and-set, not a revision or
event ledger:

1. `load_snapshot(user_id)` returns the exact stored JSON text (or None).
2. The caller parses, mutates, and calls
   `save_if_current(user_id, expected, state)` with that exact text.
3. The update is a single statement guarded by `WHERE data = :expected`, so
   the comparison uses the exact stored JSON, not a reserialized
   approximation. A changed, deleted or never-existing document raises
   `WriteConflict` and persists nothing; the caller reloads before any
   deliberate retry. Automatic retry is avoided on purpose: a request may
   already have called a model.

The conditional update is atomic at the database, including across processes.
`locked(user_id)` additionally serializes same-user request threads in ONE
process (so the losing thread is stopped before doing model work, not after);
it is a process-local lock and makes no multi-process claim.

`SqlUserStore.save` (unconditional) and `persistence.SqlSnapshot` are the
legacy paths and are NOT the authenticated concurrency path. `MemUserStore`
mirrors the same surface in memory: single-process, lost on restart.

Config: `user_store_from_env()` reads SLATE_STATE_URL - any SQLAlchemy URL;
unset means an in-memory store (state lost on restart).
"""
import json
import os
import threading

from sqlalchemy import Column, MetaData, String, Table, Text, create_engine, select
from sqlalchemy.exc import IntegrityError


class WriteConflict(Exception):
    """save_if_current found the stored document changed since load_snapshot.

    Nothing from the conflicting snapshot is persisted. Reopen the latest
    state before deliberately retrying; the server does not replay
    automatically.
    """


_locks_guard = threading.Lock()
_locks = {}


def locked(user_id: str):
    """The per-user process lock as a context manager.

    Serializes same-user request threads in this process only; a
    multi-process deployment needs the database compare-and-set above (and
    real row locking for stronger guarantees, which is not claimed).
    """
    with _locks_guard:
        lock = _locks.get(user_id)
        if lock is None:
            lock = _locks[user_id] = threading.Lock()
    return lock


def _dumps(state: dict) -> str:
    """Canonical serialization: one document always stores as the same text."""
    return json.dumps(state, sort_keys=True, separators=(",", ":"))


_metadata = MetaData()
_user_state = Table(
    "slate_user_state",
    _metadata,
    Column("user_id", String, primary_key=True),
    Column("data", Text, nullable=False),
)


class SqlUserStore:
    """Per-user JSON documents in `slate_user_state`, any SQLAlchemy URL.

    SQLite is sufficient; Postgres works through the same SQLAlchemy layer
    (not yet run against the hosted setup).
    """

    def __init__(self, url: str):
        self._engine = create_engine(url)
        _metadata.create_all(self._engine)

    def load_snapshot(self, user_id: str):
        """The exact stored JSON text for this user, or None if absent.

        Pass the returned value unchanged as `expected` to save_if_current.
        """
        with self._engine.begin() as conn:
            row = conn.execute(
                select(_user_state.c.data).where(_user_state.c.user_id == user_id)
            ).first()
        return row[0] if row is not None else None

    def load(self, user_id: str):
        """The user's stored document parsed, or None if absent."""
        raw = self.load_snapshot(user_id)
        return json.loads(raw) if raw is not None else None

    def save(self, user_id: str, state: dict):
        """Unconditionally rewrite the user's document (legacy path).

        Last writer wins with no conflict detection; the authenticated path
        uses save_if_current.
        """
        payload = _dumps(state)
        with self._engine.begin() as conn:
            updated = conn.execute(
                _user_state.update()
                .where(_user_state.c.user_id == user_id)
                .values(data=payload)
            )
            if updated.rowcount == 0:
                try:
                    # Savepoint: a failed insert must not abort the outer
                    # transaction (Postgres would reject the retry below).
                    with conn.begin_nested():
                        conn.execute(_user_state.insert().values(user_id=user_id, data=payload))
                except IntegrityError:
                    # A concurrent first save won the insert race; rewrite it.
                    conn.execute(
                        _user_state.update()
                        .where(_user_state.c.user_id == user_id)
                        .values(data=payload)
                    )

    def save_if_current(self, user_id: str, expected, state: dict):
        """Atomically replace the document only if it still equals `expected`.

        `expected` is the exact text an earlier load_snapshot returned, or
        None to require that the user has no stored document yet. Raises
        WriteConflict - persisting nothing - when the stored document differs,
        was deleted, or (for expected=None) already exists.
        """
        payload = _dumps(state)
        with self._engine.begin() as conn:
            if expected is None:
                try:
                    conn.execute(_user_state.insert().values(user_id=user_id, data=payload))
                except IntegrityError:
                    raise WriteConflict(
                        "State for this user already exists; reload before saving."
                    ) from None
            else:
                updated = conn.execute(
                    _user_state.update()
                    .where(_user_state.c.user_id == user_id)
                    .where(_user_state.c.data == expected)
                    .values(data=payload)
                )
                if updated.rowcount == 0:
                    raise WriteConflict(
                        "Stored state changed since it was loaded; reload before saving."
                    )

    def delete(self, user_id: str):
        """Remove the user's document; deleting an absent user is a no-op."""
        with self._engine.begin() as conn:
            conn.execute(_user_state.delete().where(_user_state.c.user_id == user_id))


class MemUserStore:
    """In-memory store with the same surface as SqlUserStore.

    Single-process and lost on restart; conflicts are still detected so the
    memory path exercises the same protocol as the SQL one.
    """

    def __init__(self):
        self._docs = {}  # user_id -> exact JSON text, as stored

    def load_snapshot(self, user_id: str):
        return self._docs.get(user_id)

    def load(self, user_id: str):
        raw = self._docs.get(user_id)
        return json.loads(raw) if raw is not None else None

    def save(self, user_id: str, state: dict):
        with locked(user_id):
            self._docs[user_id] = _dumps(state)

    def save_if_current(self, user_id: str, expected, state: dict):
        with locked(user_id):
            if self._docs.get(user_id) != expected:
                raise WriteConflict(
                    "Stored state changed since it was loaded; reload before saving."
                )
            self._docs[user_id] = _dumps(state)

    def delete(self, user_id: str):
        with locked(user_id):
            self._docs.pop(user_id, None)


class UserSnapshot:
    """Per-user facade with the service's store duck type: load()/save(dict).

    One UserSnapshot stands in for one user's snapshot; SlateService cannot
    tell it apart from a whole-document store. `save` is the unconditional
    write - request-scoped compare-and-set uses the store's
    load_snapshot/save_if_current directly.
    """

    def __init__(self, store, user_id: str):
        self._store = store
        self._user_id = user_id

    def load(self):
        return self._store.load(self._user_id)

    def save(self, state: dict):
        self._store.save(self._user_id, state)


def user_store_from_env(environ=None):
    """The configured user store: SLATE_STATE_URL, or in-memory when unset."""
    env = os.environ if environ is None else environ
    url = env.get("SLATE_STATE_URL")
    return SqlUserStore(url) if url else MemUserStore()
