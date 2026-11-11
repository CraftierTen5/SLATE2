"""Audit F4 pins (10-sample internet audit, 2026-11-11): school-level rows,
GPA without a scale, institute on the next line, and 'no backlogs' as academic
standing. Genuine denials stay excluded. Synthetic fixtures; no personal data."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

from slate_core.resume import parse_resume, _education_entry, _school_entry


def test_no_backlogs_does_not_hide_degree_line():
    r = parse_resume(
        "Meera K\nm@example.com\nEducation\n"
        "B.E., Computer Engineering · Savitribai Phule Pune University "
        "(affiliated college) · CGPA 8.1/10 (till 7th semester), no backlogs"
    )
    assert r["education"] == [{
        "degree": "B.E.",
        "institute": "Savitribai Phule Pune University (affiliated college)",
        "year": None, "subject": "Computer Engineering",
        "gpa": {"label": "CGPA", "value": "8.1/10"}}]


def test_genuine_denials_still_excluded():
    for text in (
        "B.Tech not completed",
        "No degree yet, currently pursuing",
        "Pursuing M.Tech, no certification completed",
    ):
        r = parse_resume(f"Kay\nk@example.com\nSummary\n{text}\nSKILLS\nPython")
        assert r["education"] == [], text


def test_gpa_without_scale_label_verbatim():
    e = _education_entry("Bachelor of Science in Computer Science - 3.8 GPA")
    assert e["gpa"] == {"label": "GPA", "value": "3.8"}


def test_hsc_ssc_rows_with_board_and_verbatim_percentage():
    e = _school_entry("HSC (Class XII), Science · Maharashtra State Board · 84.6%")
    assert e == {"degree": "HSC (Class XII)", "institute": "Maharashtra State Board",
                 "year": None, "subject": "Science",
                 "gpa": {"label": "Percentage", "value": "84.6%"}}
    e2 = _school_entry("SSC (Class X) · Maharashtra State Board · 91.2%")
    assert e2["degree"] == "SSC (Class X)"
    assert e2["gpa"] == {"label": "Percentage", "value": "91.2%"}


def test_class_xii_board_style():
    e = _school_entry("Class XII (MPBSE), Science with Mathematics")
    assert e["degree"] == "Class XII (MPBSE)"
    assert e["subject"] == "Science with Mathematics"


def test_institute_on_next_line_joins():
    r = parse_resume(
        "Aman\na@example.com\nEducation\n"
        "MCA, Computer Applications\n"
        "Malwa Institute of Computer Applications, Indore, Madhya Pradesh · 8.6 CGPA"
    )
    assert r["education"] == [{
        "degree": "MCA", "institute": "Malwa Institute of Computer Applications, Indore, Madhya Pradesh",
        "year": None, "subject": "Computer Applications", "gpa": {"label": "CGPA", "value": "8.6"}}]


def test_institute_join_fail_closed_on_non_institute_next_line():
    r = parse_resume(
        "Aman\na@example.com\nEducation\nMCA, Computer Applications\n"
        "EXPERIENCE\nSoftware Intern · Some Co\n2023\n- Built things"
    )
    edu = r["education"][0]
    assert edu["institute"] == ""


def test_dates_between_degree_and_institute():
    r = parse_resume(
        "Aman\na@example.com\nEducation\n"
        "MCA, Computer Applications\n2024 – 2026\n"
        "Malwa Institute of Computer Applications, Indore, Madhya Pradesh · 8.6 CGPA\n"
        "Class XII (MPBSE), Science with Mathematics\n2020 – 2021\n"
        "Shri Gurukul Higher Secondary School, Indore, Madhya Pradesh · 81%"
    )
    assert r["education"][0]["institute"] == "Malwa Institute of Computer Applications, Indore, Madhya Pradesh"
    assert r["education"][0]["year"] == 2026
    assert r["education"][0]["gpa"] == {"label": "CGPA", "value": "8.6"}
    assert r["education"][1]["institute"] == "Shri Gurukul Higher Secondary School, Indore, Madhya Pradesh"
    assert r["education"][1]["gpa"] == {"label": "Percentage", "value": "81%"}
