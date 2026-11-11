"""Legacy single-snapshot persistence helper.

`SqlSnapshot` stores ONE whole state document in one database row, addressed by
a fixed key. It predates per-user state: `save` rewrites the row
unconditionally, so the last writer wins with no conflict detection. The
authenticated per-user path (per-user row + atomic compare-and-set) lives in
`user_store.py`; this module stays for single-tenant fixtures and tools that
genuinely have one document.

State shape matches the service's persistence handoff (see
`SlateService(store=...)`): a JSON dict with the keys `resumes`, `texts` and
`targets`, extended by later slices with `drafts`+`draftN` and
`sessions`+`sessionN`. The store treats the document as opaque JSON and never
inspects those keys.

Imports are stdlib + SQLAlchemy only; SQLite is sufficient.
"""
import json

from sqlalchemy import Column, MetaData, String, Table, Text, create_engine, select
from sqlalchemy.exc import IntegrityError

_SNAPSHOT_KEY = "snapshot"

_metadata = MetaData()
_snapshots = Table(
    "slate_snapshot",
    _metadata,
    Column("id", String, primary_key=True),
    Column("data", Text, nullable=False),
)


def _dumps(state: dict) -> str:
    """Canonical serialization: one document always stores as the same text."""
    return json.dumps(state, sort_keys=True, separators=(",", ":"))


class SqlSnapshot:
    """Whole-document snapshot in a single row, duck type load()/save(dict).

    url is any SQLAlchemy URL, e.g. "sqlite:///slate_state.db". Unconditional
    writes: concurrent writers silently overwrite each other.
    """

    def __init__(self, url: str):
        self._engine = create_engine(url)
        _metadata.create_all(self._engine)

    def load(self):
        """The stored document, or None when nothing was saved yet."""
        with self._engine.begin() as conn:
            row = conn.execute(
                select(_snapshots.c.data).where(_snapshots.c.id == _SNAPSHOT_KEY)
            ).first()
        return json.loads(row[0]) if row is not None else None

    def save(self, state: dict):
        """Rewrite the stored document, creating the row on first save."""
        payload = _dumps(state)
        with self._engine.begin() as conn:
            updated = conn.execute(
                _snapshots.update()
                .where(_snapshots.c.id == _SNAPSHOT_KEY)
                .values(data=payload)
            )
            if updated.rowcount == 0:
                try:
                    with conn.begin_nested():
                        conn.execute(_snapshots.insert().values(id=_SNAPSHOT_KEY, data=payload))
                except IntegrityError:
                    # A concurrent first save won the insert race; rewrite it.
                    conn.execute(
                        _snapshots.update()
                        .where(_snapshots.c.id == _SNAPSHOT_KEY)
                        .values(data=payload)
                    )
