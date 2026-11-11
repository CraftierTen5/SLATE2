"""Audit F8 pins (10-sample internet audit, 2026-11-11): role-fit family
vocabulary covers mechanical engineering, support/operations and business.
The matcher stays substring-based and the gate messaging unchanged; only the
vocabulary grew. Synthetic fixtures modeled on the public samples."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

from slate_core.role_fit import (INSUFFICIENT, MISMATCH, SAME, resume_family,
                                 role_family, role_fit_review)


def test_mechanical_family_from_titles_and_skills():
    assert role_family("Mechanical Design Engineer II") == "mechanical_engineering"
    assert role_family("solidworks ansys gd&t dfmea") == "mechanical_engineering"


def test_mechanical_beats_generic_engineer_token():
    assert role_family("mechanical engineer") == "mechanical_engineering"


def test_support_operations_family():
    assert role_family("support operations ticket triage") == "support_operations"
    assert role_family("Technical Support Specialist") == "support_operations"


def test_support_phrases_outrank_generic_tech_tokens():
    # A support-ops resume that also lists JavaScript is visibly support-ops.
    assert role_family("javascript node.js support operations ticket triage") == "support_operations"


def test_business_family():
    assert role_family("business administration marketing") == "business"
    assert role_family("Human Resources Recruiter") == "business"


def test_substring_unsafe_words_stay_unknown():
    # 'fea' is not in the vocabulary because it is a substring of 'features';
    # this guards the absence so nobody adds it without boundary handling.
    assert role_family("features feasibility") == "unknown"


def test_mechanical_resume_vs_software_target_is_a_labeled_mismatch():
    parsed = {"skills": ["solidworks", "ansys", "gd&t"],
              "experience": [{"title": "Mechanical Engineer"}]}
    r = role_fit_review(parsed, "Backend Developer")
    assert r["kind"] == MISMATCH and r["resumeFamily"] == "mechanical_engineering"
    same = role_fit_review(parsed, "Mechanical Design Engineer")
    assert same["kind"] == SAME and "not a fit assessment" in same["note"]


def test_business_student_with_no_business_titles_stays_honest_unknown():
    parsed = {"skills": ["communication", "excel"], "experience": []}
    r = role_fit_review(parsed, "Backend Developer")
    assert r["kind"] == INSUFFICIENT
