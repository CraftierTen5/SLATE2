"""Profile feature: confirm once, reuse, never guess unknown answers.

Covers the bounded field vocabulary, explicit confirmation, unknown-stays-
unknown semantics, resume suggestions as unconfirmed candidates, draft-header
reuse in the deterministic tailor, per-user isolation, and persistence across
a restart. No network: auth providers are dev/fake and stores are local.
"""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
from slate_core import SlateService, SlateError
from slate_core.profile import (DRAFT_NEEDS, FIELDS, normalize_answers,
                                profile_answers, suggest_from_text)

RESUME = """Asha Verma
asha@example.com | +91 98301 88035
B.Tech Computer Science, IIITM Gwalior, 2027
Intern at ExampleCo (3 months)
Skills: Python, Git, Excel, communication
https://github.com/asha-verma
"""

DATED_RESUME = """Asha Verma
B.Tech Computer Science, IIITM Gwalior, 2023-2027
Skills: Python
"""


class Suggestions(unittest.TestCase):
    def test_literal_candidates_only(self):
        s = suggest_from_text(RESUME, {"name": "Asha Verma"})
        self.assertEqual(s["email"], "asha@example.com")
        self.assertEqual(s["phone"], "+91 98301 88035")
        self.assertEqual(s["github"], "https://github.com/asha-verma")
        self.assertEqual(s["name"], "Asha Verma")
        # Not shown by the resume: no suggestion, never a guess.
        for f in ("location", "linkedin", "portfolio"):
            self.assertNotIn(f, s)

    def test_year_ranges_are_not_phone_numbers(self):
        s = suggest_from_text(DATED_RESUME, {"name": "Asha Verma"})
        self.assertNotIn("phone", s)


class Normalize(unittest.TestCase):
    def test_unknown_fields_rejected(self):
        with self.assertRaises(ValueError):
            normalize_answers({"aadhaar": "1234"})

    def test_malformed_values_rejected(self):
        with self.assertRaises(ValueError):
            normalize_answers({"email": "not-an-email"})
        with self.assertRaises(ValueError):
            normalize_answers({"phone": "call me maybe"})
        with self.assertRaises(ValueError):
            normalize_answers({"github": "not a url"})
        with self.assertRaises(ValueError):
            normalize_answers({"name": "x" * 200})

    def test_blank_stays_unknown_and_links_normalize(self):
        clean = normalize_answers({"email": "  asha@example.com ", "phone": "",
                                   "github": "github.com/asha-verma"})
        self.assertEqual(clean, {"email": "asha@example.com",
                                 "github": "https://github.com/asha-verma"})


class AnswersContract(unittest.TestCase):
    def test_missing_never_filled(self):
        profile = {"answers": {"email": "a@b.co"}}
        out = profile_answers(profile, DRAFT_NEEDS)
        self.assertEqual(out, {"answers": {"email": "a@b.co"}, "missing": ["phone"]})
        self.assertEqual(profile_answers(None, DRAFT_NEEDS)["missing"], list(DRAFT_NEEDS))


class ServiceFlow(unittest.TestCase):
    def setUp(self):
        self.s = SlateService()
        self.rid = self.s.upload_resume(RESUME)["resumeId"]

    def test_not_started_then_confirm_required(self):
        self.assertEqual(self.s.get_profile()["status"], "not_started")
        self.assertEqual(self.s.get_profile()["unknownFields"], list(FIELDS))
        with self.assertRaises(SlateError) as c:
            self.s.save_profile({"email": "asha@example.com"}, False)
        self.assertEqual(c.exception.code, "profile_not_confirmed")
        self.assertEqual(self.s.get_profile()["status"], "not_started")

    def test_save_confirmed_and_unknown_listed(self):
        view = self.s.save_profile({"email": "asha@example.com",
                                    "phone": "+91 98301 88035"}, True)
        self.assertEqual(view["status"], "user_confirmed")
        self.assertEqual(view["source"], "user_confirmed_answers_not_independently_verified")
        self.assertEqual(view["answers"], {"email": "asha@example.com",
                                           "phone": "+91 98301 88035"})
        self.assertIn("location", view["unknownFields"])

    def test_invalid_profile_error_code(self):
        with self.assertRaises(SlateError) as c:
            self.s.save_profile({"email": "nope"}, True)
        self.assertEqual(c.exception.code, "invalid_profile")

    def test_suggestions_endpoint_shape(self):
        s = self.s.profile_suggestions(self.rid)
        self.assertEqual(s["resumeId"], self.rid)
        self.assertEqual(s["suggestionsKind"], "literal_candidates_from_resume_not_confirmed")
        self.assertEqual(s["suggestions"]["email"], "asha@example.com")
        with self.assertRaises(SlateError) as c:
            self.s.profile_suggestions("res_999")
        self.assertEqual(c.exception.code, "resume_not_found")

    def test_draft_unchanged_without_profile(self):
        d = self.s.tailor(self.rid, "job_001")
        lines = d["tailoredResume"].splitlines()
        self.assertEqual(lines[0], "Asha Verma")
        self.assertTrue(lines[1].startswith("Target role:"))
        self.assertEqual(d["profileGaps"], list(DRAFT_NEEDS))

    def test_draft_reuses_confirmed_answers_only(self):
        self.s.save_profile({"email": "asha@example.com",
                             "github": "github.com/asha-verma"}, True)
        d = self.s.tailor(self.rid, "job_001")
        lines = d["tailoredResume"].splitlines()
        self.assertEqual(lines[1], "Contact: asha@example.com")
        self.assertEqual(lines[2], "Links: https://github.com/asha-verma")
        self.assertEqual(d["profileGaps"], ["phone"])  # still unknown, not guessed
        # The claim gate still passes on the draft it generated, and the
        # approval/export path keeps working with the profile lines present.
        self.s.decide(d["draftId"], "approve")
        self.assertIn("Contact: asha@example.com",
                      self.s.export_draft(d["draftId"])["tailoredResume"])

    def test_profile_persists_through_store(self):
        from slate_core.user_store import MemUserStore
        store = MemUserStore()
        from slate_api.user_snapshot import RequestSnapshot
        s1 = SlateService(store=RequestSnapshot(store, "u1"))
        s1.save_profile({"email": "asha@example.com"}, True)
        s2 = SlateService(store=RequestSnapshot(store, "u1"))
        self.assertEqual(s2.get_profile()["answers"], {"email": "asha@example.com"})
        s3 = SlateService(store=RequestSnapshot(store, "u2"))
        self.assertEqual(s3.get_profile()["status"], "not_started")


import pytest
pytest.importorskip("fastapi"); pytest.importorskip("httpx")
from fastapi.testclient import TestClient
from slate_api.app import create_authenticated_app
from slate_core.auth import DevAuth
from slate_core.user_store import SqlUserStore

HA = {"Authorization": "Bearer dev:asha@example.com"}
HB = {"Authorization": "Bearer dev:rohan@example.com"}


@pytest.fixture()
def c(tmp_path):
    store = SqlUserStore(f"sqlite:///{tmp_path}/state.db")
    return TestClient(create_authenticated_app(DevAuth(), store))


def test_profile_routes_require_a_token(c):
    assert c.get("/v1/profile").status_code == 401
    assert c.get("/v1/profile/suggestions", params={"resumeId": "res_001"}).status_code == 401
    assert c.post("/v1/profile", json={"answers": {}, "confirm": True}).status_code == 401


def test_profile_api_roundtrip_and_isolation(c):
    rid = c.post("/v1/resume", json={"text": RESUME}, headers=HA).json()["resumeId"]
    sug = c.get("/v1/profile/suggestions", params={"resumeId": rid}, headers=HA).json()
    assert sug["suggestions"]["github"] == "https://github.com/asha-verma"

    bad = c.post("/v1/profile", json={"answers": {"email": "asha@example.com"},
                                      "confirm": False}, headers=HA)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "profile_not_confirmed"

    saved = c.post("/v1/profile", json={"answers": sug["suggestions"], "confirm": True},
                   headers=HA).json()
    assert saved["status"] == "user_confirmed"
    assert saved["answers"]["email"] == "asha@example.com"

    # The other signed-in user sees none of it.
    other = c.get("/v1/profile", headers=HB).json()
    assert other["status"] == "not_started" and other["answers"] == {}

    # Drafts reuse this user's confirmed answers only.
    d = c.post("/v1/tailor", json={"resumeId": rid, "jobId": "job_001"}, headers=HA).json()
    assert "Contact: asha@example.com | +91 98301 88035" in d["tailoredResume"]
    rid_b = c.post("/v1/resume", json={"text": RESUME}, headers=HB).json()["resumeId"]
    d_b = c.post("/v1/tailor", json={"resumeId": rid_b, "jobId": "job_001"}, headers=HB).json()
    assert "Contact:" not in d_b["tailoredResume"]
    assert d_b["profileGaps"] == list(DRAFT_NEEDS)


def test_profile_survives_restart(tmp_path):
    url = f"sqlite:///{tmp_path}/state.db"
    c1 = TestClient(create_authenticated_app(DevAuth(), SqlUserStore(url)))
    c1.post("/v1/profile", json={"answers": {"email": "asha@example.com"},
                                 "confirm": True}, headers=HA)
    c2 = TestClient(create_authenticated_app(DevAuth(), SqlUserStore(url)))
    assert c2.get("/v1/profile", headers=HA).json()["answers"] == {"email": "asha@example.com"}


if __name__ == "__main__":
    unittest.main()
