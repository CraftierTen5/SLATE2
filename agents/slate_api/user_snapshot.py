"""Request-scoped compare-and-set adapter over the store slice's public API.

The store's UserSnapshot facade is intentionally unconditional. HTTP requests
use this adapter instead, preserving the exact loaded text as their CAS token.
Request locks are separate from the store's own locks: memory CAS takes its own
lock and must never nest the same non-reentrant lock.
"""
import json
import threading

_guard = threading.Lock()
_locks = {}


def request_locked(user_id):
    """Serialize this user's requests in one process, not across processes."""
    with _guard:
        return _locks.setdefault(user_id, threading.Lock())


class RequestSnapshot:
    def __init__(self, store, user_id):
        self._store, self._user_id = store, user_id
        self._expected = None

    def load(self):
        self._expected = self._store.load_snapshot(self._user_id)
        return json.loads(self._expected) if self._expected is not None else None

    def save(self, state):
        self._store.save_if_current(self._user_id, self._expected, state)
        # Both public stores persist this canonical format. Do not reload here:
        # another process could save between our CAS and that read, giving us
        # a newer token for state we never loaded.
        self._expected = json.dumps(state, sort_keys=True, separators=(",", ":"))
