"""Jobs feed: live public-board listings with provenance, bounded refresh,
stale/outage honesty, no fabricated deadlines, original apply URLs, and no
user data sent upstream. Network is faked throughout via injected fetchers.
"""
import os, sys, unittest
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
from slate_core import SlateService, SlateError
from slate_core.jobs_feed import (BOARDS, FeedCache, board_url, extract_skills,
                                  normalize_greenhouse, normalize_lever)

NOW = datetime(2026, 11, 11, 8, 0, tzinfo=timezone.utc)
LEVER = [{"id": "abc123", "text": "Backend Developer",
          "hostedUrl": "https://jobs.lever.co/meesho/abc123",
          "categories": {"location": "Bangalore", "commitment": "Full-time"},
          "workplaceType": "onsite",
          "descriptionPlain": "Work on Python and FastAPI services.",
          "createdAt": 1793000000000}]
GH = {"jobs": [{"id": 456, "title": "Data Analyst",
                "location": {"name": "Remote, India"},
                "absolute_url": "https://boards.greenhouse.io/gitlab/jobs/456",
                "content": "<p>Use SQL and Python daily.</p>",
                "updated_at": "2026-11-10T10:00:00+00:00"}]}
TEST_BOARDS = [{"source": "lever", "board": "meesho", "company": "Meesho"},
               {"source": "greenhouse", "board": "gitlab", "company": "GitLab"}]
SDE_RESUME = ("Asha Verma\nB.Tech Computer Science, IIITM Gwalior, 2027\n"
              "Intern at ExampleCo (3 months)\nSkills: Python, Git, SQL")


def fake_fetcher(payloads, calls):
    def fetch(url):
        calls.append(url)
        data = payloads[url]
        if isinstance(data, Exception):
            raise data
        return data
    return fetch


class Normalize(unittest.TestCase):
    def test_lever_shape_provenance_and_no_deadline(self):
        out = normalize_lever(TEST_BOARDS[0], LEVER, NOW.isoformat())
        self.assertEqual(len(out), 1)
        j = out[0]
        self.assertEqual(j["jobId"], "lever-meesho-abc123")
        self.assertEqual((j["source"], j["sourceId"], j["companyBoard"]), ("lever", "abc123", "meesho"))
        self.assertEqual(j["company"], "Meesho")
        self.assertIsNone(j["deadline"])  # boards state posting dates, never deadlines
        self.assertEqual(j["url"], "https://jobs.lever.co/meesho/abc123")  # original posting
        self.assertEqual(j["skillsKind"], "extracted_mentions_not_employer_structured")
        self.assertIn("python", j["skills"]) and self.assertIn("fastapi", j["skills"])
        self.assertTrue(j["updatedAt"].startswith("2026-"))

    def test_greenhouse_shape_and_remote_label_kept(self):
        out = normalize_greenhouse(TEST_BOARDS[1], GH, NOW.isoformat())
        j = out[0]
        self.assertEqual(j["jobId"], "greenhouse-gitlab-456")
        self.assertEqual(j["location"], "Remote, India")
        self.assertIsNone(j["deadline"])
        self.assertEqual(j["url"], "https://boards.greenhouse.io/gitlab/jobs/456")
        self.assertEqual(sorted(j["skills"]), ["python", "sql"])

    def test_skill_extraction_boundaries(self):
        # "postgresql" must not yield "sql"; punctuation must not hide "c++".
        self.assertNotIn("sql", extract_skills("PostgreSQL and pgadmin"))
        self.assertIn("c++", extract_skills("Modern C++."))
        self.assertEqual(extract_skills(""), [])

    def test_lever_remote_workplace_marks_location(self):
        p = dict(LEVER[0], workplaceType="remote", categories={"location": "Bangalore"})
        out = normalize_lever(TEST_BOARDS[0], [p], NOW.isoformat())
        self.assertIn("Remote", out[0]["location"])


class Cache(unittest.TestCase):
    def _cache(self, payloads, calls, **kw):
        return FeedCache(boards=TEST_BOARDS, fetcher=fake_fetcher(payloads, calls), **kw)

    def test_refresh_bounded_per_board(self):
        calls = []
        c = self._cache({board_url(b): (LEVER if b["source"] == "lever" else GH) for b in TEST_BOARDS}, calls)
        c.listings(NOW)
        c.listings(NOW + timedelta(minutes=30))
        self.assertEqual(len(calls), 2)  # one fetch per board in the window
        c.listings(NOW + timedelta(hours=1, seconds=1))
        self.assertEqual(len(calls), 4)

    def test_failed_refresh_serves_stale_last_good(self):
        calls = []
        good = {board_url(b): (LEVER if b["source"] == "lever" else GH) for b in TEST_BOARDS}
        c = self._cache(good, calls)
        listings, status = c.listings(NOW)
        self.assertEqual(len(listings), 2) and self.assertFalse(status["anyStale"])
        c._fetch = fake_fetcher({u: OSError("boom") for u in good}, calls)
        listings, status = c.listings(NOW + timedelta(hours=2))
        self.assertEqual(len(listings), 2)  # last good data survives the outage
        self.assertTrue(status["anyStale"])
        self.assertTrue(all(b["stale"] and b["error"] for b in status["boards"]))

    def test_total_outage_without_cache_reports_unavailable_no_fixtures(self):
        calls = []
        bad = {board_url(b): OSError("down") for b in TEST_BOARDS}
        c = self._cache(bad, calls)
        listings, status = c.listings(NOW)
        self.assertEqual(listings, [])  # never silently fixture data
        self.assertFalse(status["available"])
        self.assertTrue(all(b["error"] and b["count"] == 0 for b in status["boards"]))

    def test_lookup_only_sees_cached(self):
        calls = []
        good = {board_url(TEST_BOARDS[0]): LEVER}
        c = FeedCache(boards=TEST_BOARDS[:1], fetcher=fake_fetcher(good, calls))
        self.assertIsNone(c.lookup("lever-meesho-abc123"))
        c.listings(NOW)
        self.assertEqual(c.lookup("lever-meesho-abc123")["company"], "Meesho")


class Service(unittest.TestCase):
    def _svc(self, payloads, calls):
        c = FeedCache(boards=TEST_BOARDS, fetcher=fake_fetcher(payloads, calls))
        return SlateService(feed=c)

    def test_default_unchanged_sample_label(self):
        s = self._svc({}, [])
        r = s.jobs()
        self.assertEqual(r["sourceLabel"], "sample_fixtures")
        self.assertTrue(any(j["jobId"] == "job_001" for j in r["jobs"]))
        self.assertNotIn("feedStatus", r)

    def test_live_source_provenance_and_no_mixing(self):
        calls = []
        s = self._svc({board_url(b): (LEVER if b["source"] == "lever" else GH) for b in TEST_BOARDS}, calls)
        rid = s.upload_resume(SDE_RESUME)["resumeId"]
        r = s.jobs(resume_id=rid, source="live")
        self.assertEqual(r["sourceLabel"], "live_public_boards")
        ids = [j["jobId"] for j in r["jobs"]]
        self.assertEqual(sorted(ids), ["greenhouse-gitlab-456", "lever-meesho-abc123"])
        self.assertFalse(any(i.startswith("job_") for i in ids))  # no fixtures mixed in
        for j in r["jobs"]:
            self.assertIsNone(j["deadline"])
            self.assertIn(j["source"], ("lever", "greenhouse"))
            self.assertTrue(j["url"].startswith("https://"))
        # No user data upstream: only the fixed board URLs were ever requested.
        self.assertEqual(sorted(calls), sorted(board_url(b) for b in TEST_BOARDS))
        for u in calls:
            self.assertNotIn("Asha", u) and self.assertNotIn("resume", u.lower())

    def test_live_matching_and_location_filter(self):
        s = self._svc({board_url(b): (LEVER if b["source"] == "lever" else GH) for b in TEST_BOARDS}, [])
        rid = s.upload_resume(SDE_RESUME)["resumeId"]
        r = s.jobs(location="Bangalore", resume_id=rid, source="live")
        self.assertEqual([j["jobId"] for j in r["jobs"]], ["lever-meesho-abc123"])
        self.assertEqual(r["jobs"][0]["matchedSkills"], ["python"])

    def test_live_reason_describes_extracted_mentions_not_required_skills(self):
        s = self._svc({board_url(b): (LEVER if b["source"] == "lever" else GH) for b in TEST_BOARDS}, [])
        rid = s.upload_resume(SDE_RESUME)["resumeId"]
        r = s.jobs(resume_id=rid, source="live")
        self.assertTrue(r["jobs"])
        for j in r["jobs"]:
            self.assertIn("mentions", j["reason"])
            self.assertIn("not the employer's required-skill list", j["reason"])
            self.assertNotIn("required skill", j["reason"].replace("required-skill", ""))

    def test_invalid_source_rejected(self):
        s = self._svc({}, [])
        with self.assertRaises(SlateError) as ctx:
            s.jobs(source="indeed-scrape")
        self.assertEqual(ctx.exception.code, "invalid_source")

    def test_tailor_live_listing_with_guardrails(self):
        s = self._svc({board_url(b): (LEVER if b["source"] == "lever" else GH) for b in TEST_BOARDS}, [])
        rid = s.upload_resume(SDE_RESUME)["resumeId"]
        s.jobs(source="live")  # loads the cache
        d = s.tailor(rid, "lever-meesho-abc123")
        self.assertEqual(d["status"], "draft")
        self.assertEqual(d["roleGuardrail"]["kind"], "same_keyword_family_not_a_fit_assessment")
        # Claim gate still binds the draft to the resume's own facts.
        with self.assertRaises(SlateError) as ctx:
            s.edit_draft(d["draftId"], coverNote="I am an expert in FastAPI.")
        self.assertEqual(ctx.exception.code, "unsupported_claim")

    def test_default_feed_shared_across_service_instances(self):
        # Regression: the API builds a fresh service per request, so a per-service
        # feed made tailoring a live listing answer job_not_found on the next
        # request. The default feed is process-wide (public, non-user data).
        from slate_core import jobs_feed
        calls = []
        c = FeedCache(boards=TEST_BOARDS, fetcher=fake_fetcher(
            {board_url(b): (LEVER if b["source"] == "lever" else GH) for b in TEST_BOARDS}, calls))
        saved = jobs_feed._DEFAULT_FEED
        jobs_feed._DEFAULT_FEED = c
        try:
            SlateService().jobs(source="live")  # first request's service loads the cache
            s2 = SlateService()                  # a later request gets a fresh service
            rid = s2.upload_resume(SDE_RESUME)["resumeId"]
            d = s2.tailor(rid, "lever-meesho-abc123")
            self.assertEqual(d["status"], "draft")
            self.assertEqual(len(calls), 2)  # one fetch per board, never per service
        finally:
            jobs_feed._DEFAULT_FEED = saved

    def test_uncached_live_listing_is_job_not_found(self):
        s = self._svc({}, [])
        rid = s.upload_resume(SDE_RESUME)["resumeId"]
        with self.assertRaises(SlateError) as ctx:
            s.tailor(rid, "lever-meesho-abc123")
        self.assertEqual(ctx.exception.code, "job_not_found")


class Api(unittest.TestCase):
    def test_routes(self):
        from fastapi.testclient import TestClient
        from slate_api.app import create_app
        calls = []
        c = FeedCache(boards=TEST_BOARDS, fetcher=fake_fetcher(
            {board_url(b): (LEVER if b["source"] == "lever" else GH) for b in TEST_BOARDS}, calls))
        app = create_app(SlateService(feed=c))
        h = TestClient(app)
        r = h.get("/v1/jobs", params={"source": "live"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["sourceLabel"], "live_public_boards")
        r = h.get("/v1/jobs/feed")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["totalListings"], 2)
        self.assertEqual(r.json()["sourceKind"], "live_public_boards_lever_greenhouse")
        r = h.get("/v1/jobs", params={"source": "scrape-everything"})
        self.assertEqual(r.json()["error"]["code"], "invalid_source")
        r = h.get("/v1/jobs")
        self.assertEqual(r.json()["sourceLabel"], "sample_fixtures")


if __name__ == "__main__":
    unittest.main()
