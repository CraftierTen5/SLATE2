"""Store slice tests: persistence.SqlSnapshot and user_store (SQL + memory).

Covers the required roundtrip, stale WriteConflict and memory/SQL parity,
plus per-user isolation, restart durability, the UserSnapshot facade against
SlateService, the per-user process lock and SLATE_STATE_URL config. SQLite
temp files only; no network, no other services.
"""
import json
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))
from slate_core.persistence import SqlSnapshot
from slate_core.user_store import (
    MemUserStore,
    SqlUserStore,
    UserSnapshot,
    WriteConflict,
    locked,
    user_store_from_env,
)

STATE = {"resumes": {"r1": {"name": "Asha Verma"}}, "texts": {"r1": "Skills: Python, Git"},
         "targets": {}, "drafts": {}, "draftN": 0, "sessions": {}, "sessionN": 0}


def sql_store(tmp_path):
    return SqlUserStore("sqlite:///" + str(tmp_path / "state.db"))


# --- SqlSnapshot (legacy single-document helper) ---

def test_sql_snapshot_roundtrip_and_restart(tmp_path):
    url = "sqlite:///" + str(tmp_path / "snap.db")
    snap = SqlSnapshot(url)
    assert snap.load() is None
    snap.save(STATE)
    assert snap.load() == STATE
    changed = dict(STATE, draftN=3)
    snap.save(changed)
    # A fresh instance over the same file sees the rewrite (restart durability).
    assert SqlSnapshot(url).load() == changed


# --- SqlUserStore ---

def test_sql_user_store_roundtrip_isolation_and_delete(tmp_path):
    store = sql_store(tmp_path)
    assert store.load("u1") is None
    store.save("u1", STATE)
    store.save("u2", dict(STATE, draftN=7))
    assert store.load("u1") == STATE
    assert store.load("u2")["draftN"] == 7
    store.save("u1", dict(STATE, sessionN=2))
    assert store.load("u1")["sessionN"] == 2 and store.load("u2")["sessionN"] == 0
    store.delete("u1")
    assert store.load("u1") is None
    assert store.load("u2")["draftN"] == 7  # other users untouched
    store.delete("u1")  # deleting an absent user is a no-op


def test_sql_user_store_survives_restart(tmp_path):
    store = sql_store(tmp_path)
    store.save("u1", STATE)
    assert sql_store(tmp_path).load("u1") == STATE


def test_save_if_current_stale_write_conflict(tmp_path):
    store = sql_store(tmp_path)
    store.save("u1", STATE)
    # Two requests load the same snapshot; the first save wins.
    snap_a, snap_b = store.load_snapshot("u1"), store.load_snapshot("u1")
    winner = dict(STATE, draftN=1)
    store.save_if_current("u1", snap_a, winner)
    with pytest.raises(WriteConflict):
        store.save_if_current("u1", snap_b, dict(STATE, draftN=2))
    assert store.load("u1") == winner  # nothing from the loser persisted
    # The winner's own follow-up save against the new snapshot succeeds.
    store.save_if_current("u1", store.load_snapshot("u1"), dict(winner, sessionN=1))
    assert store.load("u1")["sessionN"] == 1


def test_save_if_current_insert_and_delete_edges(tmp_path):
    store = sql_store(tmp_path)
    # expected=None requires no stored document.
    store.save_if_current("u1", None, STATE)
    with pytest.raises(WriteConflict):
        store.save_if_current("u1", None, dict(STATE, draftN=9))
    # A snapshot taken before a delete no longer matches.
    snap = store.load_snapshot("u1")
    store.delete("u1")
    with pytest.raises(WriteConflict):
        store.save_if_current("u1", snap, STATE)
    # After the delete, expected=None is current again.
    store.save_if_current("u1", None, STATE)
    assert store.load("u1") == STATE


def test_load_snapshot_is_exact_stored_text(tmp_path):
    store = sql_store(tmp_path)
    store.save("u1", STATE)
    raw = store.load_snapshot("u1")
    assert isinstance(raw, str) and json.loads(raw) == STATE
    # A reserialized approximation (same value, different text) is rejected.
    approx = json.dumps(json.loads(raw))
    assert approx != raw  # canonical storage is compact, sorted JSON
    with pytest.raises(WriteConflict):
        store.save_if_current("u1", approx, dict(STATE, draftN=1))
    # The exact stored text is accepted.
    store.save_if_current("u1", raw, dict(STATE, draftN=1))
    assert store.load("u1")["draftN"] == 1


# --- Memory/SQL parity ---

def test_memory_sql_parity(tmp_path):
    stores = [sql_store(tmp_path), MemUserStore()]

    def step(op, *args):
        outcomes = []
        for store in stores:
            try:
                outcomes.append((True, getattr(store, op)("u", *args)))
            except WriteConflict:
                outcomes.append((False, "WriteConflict"))
        assert outcomes[0] == outcomes[1], (op, outcomes)
        return outcomes[0]

    assert step("load") == (True, None)
    step("save", STATE)
    assert step("load") == (True, STATE)
    snap = step("load_snapshot")[1]
    step("save_if_current", snap, dict(STATE, draftN=1))
    assert step("save_if_current", snap, dict(STATE, draftN=2)) == (False, "WriteConflict")
    assert step("load")[1]["draftN"] == 1
    step("delete")
    assert step("load") == (True, None)
    assert step("save_if_current", snap, STATE) == (False, "WriteConflict")
    step("save_if_current", None, STATE)
    assert step("load") == (True, STATE)


# --- UserSnapshot facade against SlateService ---

def test_user_snapshot_facade_service_restart_and_isolation(tmp_path):
    from slate_core import SlateService

    store = sql_store(tmp_path)
    svc = SlateService(store=UserSnapshot(store, "u1"))
    rid = svc.upload_resume("Asha Verma\nSkills: Python, Git")["resumeId"]
    # Restart: a fresh service over the same store and user keeps the state.
    again = SlateService(store=UserSnapshot(store, "u1"))
    assert again.get_resume(rid)["parsed"]
    # Another user on the same database does not see u1's resume.
    from slate_core import SlateError
    other = SlateService(store=UserSnapshot(store, "u2"))
    with pytest.raises(SlateError) as not_found:
        other.get_resume(rid)
    assert not_found.value.code == "resume_not_found"


# --- Per-user process lock ---

def test_locked_serializes_same_user_only():
    counter = {"n": 0}

    def bump(user):
        for _ in range(200):
            with locked(user):
                counter["n"] += 1

    threads = [threading.Thread(target=bump, args=("u1",)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert counter["n"] == 800
    # Distinct users get distinct locks; the same user shares one.
    assert locked("u1") is locked("u1") and locked("u1") is not locked("u2")


# --- SLATE_STATE_URL config ---

def test_user_store_from_env(tmp_path):
    assert isinstance(user_store_from_env({}), MemUserStore)
    url = "sqlite:///" + str(tmp_path / "env.db")
    store = user_store_from_env({"SLATE_STATE_URL": url})
    assert isinstance(store, SqlUserStore)
    store.save("u1", STATE)
    assert store.load("u1") == STATE
