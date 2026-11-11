import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
from slate_core import SlateService, SlateError

RESUME = """Asha Verma
B.Tech Computer Science, IIITM Gwalior, 2027
Intern at ExampleCo (3 months)
Skills: Python, Git, Excel. Scored 8.1 CGPA, 72% in class 12.
"""

class Claims(unittest.TestCase):
    def setUp(self):
        self.s = SlateService()
        self.rid = self.s.upload_resume(RESUME)["resumeId"]
        self.d = self.s.tailor(self.rid, "job_001")["draftId"]

    def reject(self, **upd):
        with self.assertRaises(SlateError) as c:
            self.s.edit_draft(self.d, **upd)
        self.assertEqual(c.exception.code, "unsupported_claim")
        return c.exception.message

    def test_supported_edit_is_accepted(self):
        new = self.s.edit_draft(self.d, coverNote="I know Python and Excel and finished a 3 month internship. 8.1 CGPA.")
        self.assertNotEqual(new["draftId"], self.d)

    def test_unsupported_skill(self):
        self.assertIn("'sql'", self.reject(coverNote="Strong in SQL and Python."))
        self.assertIn("'react'", self.reject(tailoredResume="Skills: React"))

    def test_inflated_experience(self):
        self.assertIn("exceeds", self.reject(coverNote="I have 3 years of experience."))
        self.assertIn("exceeds", self.reject(coverNote="6 months of industry work"))
        self.assertIn("exceeds", self.reject(coverNote="2+ yrs experience"))

    def test_numbers_not_in_resume(self):
        self.assertIn("percentage", self.reject(coverNote="Improved accuracy by 40%"))
        self.assertIn("GPA", self.reject(coverNote="CGPA 9.4"))
        self.assertIn("degree", self.reject(coverNote="MBA graduate"))

    def test_failed_edit_creates_no_draft(self):
        n = len(self.s.approvals._drafts)
        self.reject(coverNote="10 years of Java")
        self.assertEqual(len(self.s.approvals._drafts), n)

    def test_approve_and_export_revalidate(self):
        """Even if content is changed behind the service's back, approve and export fail closed."""
        self.s.approvals._drafts[self.d]["content"]["coverNote"] = "Expert in SQL"
        with self.assertRaises(SlateError):
            self.s.decide(self.d, "approve")
        self.s.approvals._drafts[self.d]["status"] = "approved"
        with self.assertRaises(SlateError):
            self.s.export_draft(self.d)

    def test_known_gaps_are_not_detected(self):
        """Documented limit: paraphrase and named employers are NOT caught by the rule check."""
        new = self.s.edit_draft(self.d, coverNote="I led engineering at Google.")
        self.assertTrue(new["draftId"])

if __name__ == "__main__":
    unittest.main()


class TargetReferenceMentions(unittest.TestCase):
    """The target's own title/company quoted in a draft are references, not claims."""

    NO_ML_RESUME = ("Kavya Menon\nSkills\nPython, Statistics, SQL, Pytorch\n"
                    "Experience\nData Intern, ClearInsights\nEducation\nB.Tech CSE, 2026\n")

    def setUp(self):
        self.s = SlateService()
        self.rid = self.s.upload_resume(self.NO_ML_RESUME)["resumeId"]

    def test_job_title_in_generated_draft_is_not_a_claim(self):
        # Regression: tailoring to "Machine Learning Engineer" (job_004) used to
        # fail the claim check because the cover note quotes the job title.
        r = self.s.tailor(self.rid, "job_004")
        self.assertIn("Machine Learning Engineer", r["coverNote"])
        did = r["draftId"]
        self.s.decide(did, "approve")
        exported = self.s.export_draft(did)  # re-validation at export must also pass
        self.assertIn("Machine Learning Engineer", exported["coverNote"])

    def test_actual_ml_claim_in_cover_note_still_rejected(self):
        did = self.s.tailor(self.rid, "job_004")["draftId"]
        with self.assertRaises(SlateError) as c:
            self.s.edit_draft(did, coverNote="I have two years of machine learning experience.")
        self.assertEqual(c.exception.code, "unsupported_claim")
        self.assertIn("machine learning", c.exception.message)

    def test_actual_ml_claim_in_resume_text_still_rejected(self):
        did = self.s.tailor(self.rid, "job_004")["draftId"]
        with self.assertRaises(SlateError) as c:
            self.s.edit_draft(did, tailoredResume="Kavya Menon\nSkills: python, machine learning")
        self.assertEqual(c.exception.code, "unsupported_claim")

    def test_validate_strips_only_exact_allowed_mentions(self):
        from slate_core.claims import validate
        parsed = self.s.get_resume(self.rid)["parsed"]
        ok = validate(parsed, self.NO_ML_RESUME,
                      "Target role: Machine Learning Engineer at Northwind AI",
                      "Hello Northwind AI team, I am applying for the Machine Learning Engineer role.",
                      allowed_mentions=["Machine Learning Engineer", "Northwind AI"])
        self.assertEqual(ok, [])
        bad = validate(parsed, self.NO_ML_RESUME, "",
                       "I build machine learning models.",
                       allowed_mentions=["Machine Learning Engineer", "Northwind AI"])
        self.assertTrue(any("machine learning" in v for v in bad))

    def test_first_person_assertion_with_exact_title_still_rejected_in_note(self):
        did = self.s.tailor(self.rid, "job_004")["draftId"]
        with self.assertRaises(SlateError) as c:
            self.s.edit_draft(did, coverNote="Previously worked as a Machine Learning Engineer.")
        self.assertEqual(c.exception.code, "unsupported_claim")
        self.assertIn("machine learning", c.exception.message)

    def test_first_person_assertion_with_exact_title_still_rejected_in_resume(self):
        did = self.s.tailor(self.rid, "job_004")["draftId"]
        with self.assertRaises(SlateError) as c:
            self.s.edit_draft(did, tailoredResume="Kavya Menon\nExperience: Machine Learning Engineer, OldCo")
        self.assertEqual(c.exception.code, "unsupported_claim")

    def test_reference_context_and_real_claim_in_same_note(self):
        from slate_core.claims import validate
        parsed = self.s.get_resume(self.rid)["parsed"]
        bad = validate(parsed, self.NO_ML_RESUME, "",
                       "I am applying for the Machine Learning Engineer role and I know machine learning.",
                       allowed_mentions=["Machine Learning Engineer", "Northwind AI"])
        self.assertTrue(any("machine learning" in v for v in bad))
