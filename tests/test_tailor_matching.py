"""Regression tests: tailoring must use the same skill matching as the match
explanation (PR #14 made scoring case/whitespace-insensitive and dedupe repeats;
the tailor draft and claim check must agree with it)."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
from slate_core.tailor import build_draft, check_claims
from slate_core.resume import parse_resume
from slate_core import SlateService

RESUME_TEXT = ("Asha Verma\nB.Tech Computer Science, IIITM Gwalior, 2027\n"
               "Intern at ExampleCo (3 months)\nSkills: Python, Git, Excel, communication")


class TailorMatching(unittest.TestCase):
    def test_capitalized_job_skill_is_matched_not_a_gap(self):
        d = build_draft({"name": "A", "skills": ["python"], "experience": [], "education": []},
                        {"title": "Backend Engineer", "company": "C", "skills": ["Python", "FastAPI"]})
        self.assertEqual(d["claims"], ["Python"])
        self.assertEqual(d["gaps"], ["FastAPI"])

    def test_repeated_and_messy_job_skills_count_once(self):
        d = build_draft({"name": "A", "skills": [" PYTHON "], "experience": [], "education": []},
                        {"title": "T", "company": "C", "skills": ["python", "Python", " sql "]})
        self.assertEqual(d["claims"], ["python"])
        self.assertEqual(d["gaps"], ["sql"])

    def test_check_claims_ignores_case_and_whitespace(self):
        parsed = {"skills": ["python", "sql"]}
        self.assertEqual(check_claims(parsed, ["Python", " sql "]), [])
        self.assertEqual(check_claims(parsed, ["Ruby"]), ["Ruby"])


class EndToEndConsistency(unittest.TestCase):
    def test_jobs_explanation_and_tailor_draft_agree(self):
        import slate_core.jobs as J
        from slate_core import SlateService
        saved = J.JOBS
        J.JOBS = [{"jobId": "jx", "title": "Backend Engineer", "company": "C",
                   "location": "Indore", "deadline": "2026-12-01", "url": "u",
                   "skills": ["Python", "FastAPI"]}]
        try:
            svc = SlateService()
            rid = svc.upload_resume(RESUME_TEXT)["resumeId"]
            job = next(x for x in svc.jobs("", "", rid)["jobs"] if x["jobId"] == "jx")
            d = svc.tailor(rid, "jx")
            self.assertEqual(job["matchedSkills"], d["claimsChecked"])
            self.assertEqual(job["missingSkills"], d["skillGaps"])
        finally:
            J.JOBS = saved


if __name__ == "__main__":
    unittest.main()


class UnknownNameHandling(unittest.TestCase):
    """An unparseable name is never printed as 'Unknown'; it goes to confirmation."""

    NO_NAME_RESUME = "Contact: x@example.com\nSkills\nPython, SQL, Git\nExperience\nData Intern, ClearInsights\nEducation\nB.Sc Maths, 2025\n"

    def test_unknown_name_omitted_and_surfaced_as_profile_gap(self):
        s = SlateService()
        rid = s.upload_resume(self.NO_NAME_RESUME)["resumeId"]
        r = s.tailor(rid, "job_001")
        self.assertNotIn("Unknown", r["tailoredResume"])
        self.assertIn("Target role: Data Analyst at ExampleCo", r["tailoredResume"])
        self.assertIn("name", r["profileGaps"])

    def test_confirmed_name_flows_into_the_draft(self):
        s = SlateService()
        rid = s.upload_resume(self.NO_NAME_RESUME)["resumeId"]
        s.save_profile({"name": "Ritika Sen"}, True)
        r = s.tailor(rid, "job_001")
        self.assertTrue(r["tailoredResume"].startswith("Ritika Sen\n"), r["tailoredResume"])
        self.assertNotIn("name", r["profileGaps"])

    def test_parseable_name_untouched_and_no_name_gap(self):
        s = SlateService()
        rid = s.upload_resume("Asha Verma\nSkills: Python, Git, SQL\n")["resumeId"]
        r = s.tailor(rid, "job_001")
        self.assertTrue(r["tailoredResume"].startswith("Asha Verma\n"))
        self.assertNotIn("name", r["profileGaps"])


class EducationRendering(unittest.TestCase):
    """Draft education lines preserve source facts without inflating them."""

    def test_structured_degree_renders_institute_and_year(self):
        parsed = parse_resume("Asha Verma\nEducation\nB.Tech Computer Science, IIITM Gwalior, 2027\nSkills: Python, Git, SQL\n")
        d = build_draft(parsed, {"title": "Data Analyst", "company": "ExampleCo", "skills": ["Python"]})
        self.assertIn("Education: B.Tech, IIITM Gwalior (2027)", d["tailoredResume"])

    def test_prose_study_subject_is_labeled_study_not_degree(self):
        parsed = parse_resume("Priya Nair is a final-year student with AutoCAD skills.\n"
                              "She studied Mechanical Engineering at NIT Trichy, graduating 2026.\n"
                              "She interned at MechDesign Labs as a CAD Intern.")
        d = build_draft(parsed, {"title": "Data Analyst", "company": "ExampleCo", "skills": ["Python"]})
        self.assertIn("Education: Studied Mechanical Engineering, NIT Trichy (2026)", d["tailoredResume"])


class GpaPreservation(unittest.TestCase):
    """GPA/CGPA is carried only when literally stated, label and scale as written."""

    JOB = {"title": "Data Analyst", "company": "ExampleCo", "skills": ["Python"]}

    def test_cgpa_with_scale_preserved_verbatim(self):
        parsed = parse_resume("Asha Verma\nEducation\nB.Tech Computer Science, IIITM Gwalior, CGPA 8.9/10, 2027\nSkills: Python, Git, SQL\n")
        d = build_draft(parsed, self.JOB)
        self.assertIn("Education: B.Tech, IIITM Gwalior, CGPA 8.9/10 (2027)", d["tailoredResume"])

    def test_no_gpa_means_no_gpa_line(self):
        parsed = parse_resume("Asha Verma\nEducation\nB.Tech Computer Science, IIITM Gwalior, 2027\nSkills: Python, Git, SQL\n")
        d = build_draft(parsed, self.JOB)
        self.assertNotIn("GPA", d["tailoredResume"])
        self.assertNotIn("gpa", parsed["education"][0])

    def test_orphan_gpa_mention_not_promoted_to_education(self):
        parsed = parse_resume("Asha Verma\nMy GPA was 3.9 overall.\nSkills: Python, Git, SQL\nExperience\nIntern, ExampleCo\n")
        self.assertEqual(parsed["education"], [])

    def test_prose_study_line_carries_literal_gpa(self):
        parsed = parse_resume("Priya Nair is a final-year student.\n"
                              "She studied Mechanical Engineering at NIT Trichy, graduating 2026, CGPA 8.1.\n"
                              "She interned at MechDesign Labs as a CAD Intern.")
        d = build_draft(parsed, self.JOB)
        self.assertIn("Education: Studied Mechanical Engineering, NIT Trichy, CGPA 8.1 (2026)", d["tailoredResume"])
