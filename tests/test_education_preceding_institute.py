"""Audit F10 pins (10-sample internet audit, 2026-11-11): some templates put
the institute line BEFORE the degree line. The backward join must never steal
a previous entry's line or the candidate's own name. Synthetic fixtures
modeled on the public samples; no personal data."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

from slate_core.resume import parse_resume


def test_institute_before_degree_with_label_date_line():
    r = parse_resume(
        "Lee Example\nlee@example.com\nEducation\n"
        "University of Example State, Example City\n"
        "Expected Graduation: June 2016\n"
        "Bachelor of Arts, Business Administration\nGPA: 3.5")
    edu = r["education"][0]
    assert edu["institute"] == "University of Example State, Example City"
    assert edu["degree"] == "Bachelor of Arts"
    assert edu["gpa"] == {"label": "GPA", "value": "3.5"}


def test_name_line_is_never_an_institute():
    r = parse_resume(
        "Mohit Example\nAcademic Qualifications\n"
        "MBA (HR), Example University, 2025, 7.9 CGPA\nB.Com, 2023\n")
    bcom = next(e for e in r["education"] if e["degree"] == "B.Com")
    assert bcom["institute"] == ""


def test_previous_entry_line_is_never_stolen():
    r = parse_resume(
        "Sam Example\ns@example.com\nEducation\n"
        "B.Sc, Example College, 2020\nM.Sc, 2022\n")
    msc = next(e for e in r["education"] if e["degree"] == "M.Sc")
    assert msc["institute"] == ""
