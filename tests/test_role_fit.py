"""Role-fit guardrail: no blind cross-family tailoring, career switches allowed.

Covers the three labeled evidence states, the explicit acknowledgment gate on
every draft entry point (deterministic, private target, opt-in AI), the marked
draft content after acknowledgment, insufficient-evidence honesty, negation /
incidental-mention non-classification, family tie order, and the unchanged
claim gate. No network: dev auth, local stores, MockLLM.
"""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import slate_core.jobs as J
from slate_core import SlateService, SlateError
from slate_core.role_fit import (INSUFFICIENT, MISMATCH, SAME, resume_family,
                                 role_family, role_fit_review, target_family)

SDE_RESUME = ("Asha Verma\nB.Tech Computer Science, IIITM Gwalior, 2027\n"
              "Intern at ExampleCo (3 months)\nSkills: Python, Git, SQL")
RETAIL_RESUME = ("Blake Example\nWork Experience\nShop assistant, Local Store\n"
                 "Skills: Customer service, cash handling")
MGMT_JOB = {"jobId": "job_mgmt", "title": "Management Consultant",
            "company": "Example Advisory", "location": "Remote",
            "deadline": "2026-12-20", "url": "https://example.com/jobs/mgmt",
            "skills": ["strategy", "communication"]}


class Families(unittest.TestCase):
    def test_tie_order_store_manager_is_retail_not_management(self):
        self.assertEqual(role_family("store manager"), "retail_customer_service")

    def test_unknown_is_a_honest_answer_not_a_negative(self):
        self.assertEqual(role_family("florist arrangement"), "unknown")
        self.assertEqual(role_family(""), "unknown")

    def test_resume_family_scans_skills_and_titles_only(self):
        # A negation or incidental mention in prose must not classify the resume.
        parsed = {"skills": ["python"],
                  "experience": [{"title": "Software Intern"}],
                  "summary": "No management experience; reported to the engineering manager."}
        self.assertEqual(resume_family(parsed), "engineering_technology")

    def test_review_states(self):
        eng = {"skills": ["python"], "experience": []}
        self.assertEqual(role_fit_review(eng, "Management Consultant")["kind"], MISMATCH)
        same = role_fit_review(eng, "Backend Developer", ["python", "fastapi"])
        self.assertEqual(same["kind"], SAME)
        self.assertIn("not a fit assessment", same["note"])
        ins = role_fit_review({"skills": ["excel"], "experience": []}, "Backend Developer")
        self.assertEqual(ins["kind"], INSUFFICIENT)
        self.assertIn("insufficient evidence", ins["note"].lower())
        self.assertNotIn("fit", ins["note"].lower().split("insufficient evidence")[0])


class ServiceGate(unittest.TestCase):
    def setUp(self):
        self.saved = J.JOBS
        J.JOBS = J.JOBS + [MGMT_JOB]
        self.s = SlateService()

    def tearDown(self):
        J.JOBS = self.saved

    def _rid(self, text=SDE_RESUME):
        return self.s.upload_resume(text)["resumeId"]

    def test_mismatch_blocks_before_any_draft(self):
        rid = self._rid()
        with self.assertRaises(SlateError) as ctx:
            self.s.tailor(rid, "job_mgmt")
        self.assertEqual(ctx.exception.code, "role_change_needs_acknowledgment")
        self.assertIn("No draft was created yet", str(ctx.exception))
        self.assertEqual(self.s.list_drafts()["totalCount"], 0)

    def test_acknowledged_switch_creates_marked_draft(self):
        rid = self._rid()
        d = self.s.tailor(rid, "job_mgmt", True)
        self.assertEqual(d["roleGuardrail"]["kind"], MISMATCH)
        self.assertEqual(d["roleGuardrail"]["reviewKind"], "keyword_review_not_a_fit_assessment")
        content = self.s.get_draft(d["draftId"])["content"]
        self.assertTrue(content["roleChangeAcknowledgedByUser"])
        # Facts stay original: the draft is built from the same source, and the
        # claim gate still rejects invented content on an acknowledged draft.
        self.assertIn("Asha Verma", d["tailoredResume"])
        with self.assertRaises(SlateError) as ctx:
            self.s.edit_draft(d["draftId"], coverNote="I am an expert in FastAPI.")
        self.assertEqual(ctx.exception.code, "unsupported_claim")

    def test_same_family_drafts_without_ack(self):
        rid = self._rid()
        d = self.s.tailor(rid, "job_001")
        self.assertEqual(d["roleGuardrail"]["kind"], SAME)
        self.assertNotIn("roleChangeAcknowledgedByUser", self.s.get_draft(d["draftId"])["content"])

    def test_insufficient_evidence_drafts_and_is_labeled(self):
        rid = self._rid("Casey Example\nWork Experience\nFlorist, Local Shop\nSkills: Excel")
        d = self.s.tailor(rid, "job_001")
        self.assertEqual(d["roleGuardrail"]["kind"], INSUFFICIENT)

    def test_target_route_gated_the_same_way(self):
        rid = self._rid()
        t = self.s.create_target("Management Consultant", "Example Advisory",
                                 "Strategy and operations requirements.", "")["target"]
        with self.assertRaises(SlateError) as ctx:
            self.s.tailor_target(rid, t["targetId"])
        self.assertEqual(ctx.exception.code, "role_change_needs_acknowledgment")
        d = self.s.tailor_target(rid, t["targetId"], True)
        self.assertTrue(self.s.get_draft(d["draftId"])["content"]["roleChangeAcknowledgedByUser"])

    def test_retail_resume_vs_engineering_job_also_gated(self):
        rid = self._rid(RETAIL_RESUME)
        with self.assertRaises(SlateError) as ctx:
            self.s.tailor(rid, "job_001")
        self.assertEqual(ctx.exception.code, "role_change_needs_acknowledgment")


class AIGate(unittest.TestCase):
    def test_gate_fires_before_any_model_call(self):
        from slate_core.ai_service import AISlateService
        from slate_core.llm import MockLLM
        saved = J.JOBS
        J.JOBS = J.JOBS + [MGMT_JOB]
        try:
            llm = MockLLM("RESUME\nx [S1]\n\nCOVER NOTE\ny [S1]")
            s = AISlateService(llm_client=llm)
            rid = s.upload_resume(SDE_RESUME)["resumeId"]
            with self.assertRaises(SlateError) as ctx:
                s.tailor_ai(rid, "job_mgmt")
            self.assertEqual(ctx.exception.code, "role_change_needs_acknowledgment")
            self.assertEqual(llm.prompts, [])  # no model call happened
            d = s.tailor_ai(rid, "job_mgmt", acknowledge_role_change=True)
            self.assertTrue(llm.prompts)  # acknowledged: the model ran
            self.assertEqual(d["roleGuardrail"]["kind"], MISMATCH)
        finally:
            J.JOBS = saved


class ApiContract(unittest.TestCase):
    def test_http_409_and_ack_flow(self):
        from fastapi.testclient import TestClient
        from slate_api.app import create_app
        saved = J.JOBS
        J.JOBS = J.JOBS + [MGMT_JOB]
        try:
            c = TestClient(create_app(SlateService()))
            rid = c.post("/v1/resume", json={"text": SDE_RESUME}).json()["resumeId"]
            r = c.post("/v1/tailor", json={"resumeId": rid, "jobId": "job_mgmt"})
            self.assertEqual(r.status_code, 409)
            self.assertEqual(r.json()["error"]["code"], "role_change_needs_acknowledgment")
            self.assertEqual(c.get("/v1/drafts").json().get("drafts", []), [])
            r = c.post("/v1/tailor",
                       json={"resumeId": rid, "jobId": "job_mgmt", "acknowledgeRoleChange": True})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["roleGuardrail"]["kind"], MISMATCH)
            r = c.post("/v1/tailor",
                       json={"resumeId": rid, "jobId": "job_mgmt", "acknowledgeRoleChange": "yes"})
            self.assertEqual(r.status_code, 422)  # StrictBool: strings rejected
            r = c.post("/v1/tailor", json={"resumeId": rid, "jobId": "job_001"})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["roleGuardrail"]["kind"], SAME)
        finally:
            J.JOBS = saved


if __name__ == "__main__":
    unittest.main()
