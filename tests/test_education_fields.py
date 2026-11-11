"""Pin education field extraction: right value in the right field, as written.

A GPA/score segment is never an institute, degree text is not truncated, and a
field-of-study segment is a subject, not an institute.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

from slate_core.resume import _education_entry


def test_dot_separator_segments_and_score_not_institute():
    e = _education_entry(
        "B.E., Computer Engineering · Savitribai Phule Pune University "
        "(affiliated college) · CGPA 8.1/10 (till 7th semester), no backlogs"
    )
    assert e["degree"] == "B.E."
    assert e["institute"] == "Savitribai Phule Pune University (affiliated college)"
    assert e["subject"] == "Computer Engineering"
    assert e["gpa"] == {"label": "CGPA", "value": "8.1/10"}


def test_bs_degree_token_recognized():
    e = _education_entry(
        "B.S., Mechanical Engineering · The Ohio State University · "
        "Senior design: low-cost irrigation pump"
    )
    assert e is not None
    assert e["degree"] == "B.S."
    assert e["institute"] == "The Ohio State University"
    assert e["subject"] == "Mechanical Engineering"


def test_gpa_segment_never_becomes_institute():
    e = _education_entry("Bachelor of Science in Computer Science - 3.8 GPA")
    assert e["institute"] != "3.8 GPA"
    assert "3.8" not in e["institute"]


def test_bachelor_of_subject_not_truncated():
    e = _education_entry("Bachelor of Arts, Business Administration")
    assert e["degree"] == "Bachelor of Arts"
    assert e["subject"] == "Business Administration"
    assert e["institute"] == ""

    e2 = _education_entry("Bachelor of Science in Computer Science - 3.8 GPA")
    assert e2["degree"] == "Bachelor of Science in Computer Science"


def test_real_institutes_still_extracted():
    e = _education_entry("BSc Computer Science, State University, 2018.")
    assert e["institute"] == "State University" and e["year"] == 2018
    e2 = _education_entry("B.Des, NID Ahmedabad, CGPA 8.9/10 (2026)")
    assert e2["institute"] == "NID Ahmedabad"


def test_mca_subject_is_subject_not_institute():
    e = _education_entry("MCA, Computer Applications")
    assert e["institute"] == ""
    assert e["subject"] == "Computer Applications"
