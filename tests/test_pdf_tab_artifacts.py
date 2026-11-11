"""Audit F9 pins (10-sample internet audit, 2026-11-11): tabular-PDF
extraction emits one word per line ('word\\t' / ' \\xa0word'), shattering
sentences; a bare page-number line can sit where the name belongs; a
standalone GPA line was swallowed as a date line. Synthetic fixtures modeled
on the public samples; no personal data."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

from slate_core.resume import parse_resume, _join_tab_split_lines

TABBED = ("2\t\n \xa0\nLee Example\t\n \xa0\nlee@example.com\t\n \xa0\n"
          "EDUCATION\t\n \xa0\nBachelor\t\n \xa0of\t\n \xa0Arts,\t\n \xa0Business\t\n \xa0Administration\t\n \xa0\n"
          "GPA:\t\n \xa03.5\t\n \xa0\n\t\n \xa0\n"
          "SKILLS\t\n \xa0\nComputer:\t\n \xa0Microsoft\t\n \xa0Word,\t\n \xa0Excel\t")


def test_tab_split_words_rejoin_into_logical_lines():
    j = _join_tab_split_lines(TABBED)
    assert "Bachelor of Arts, Business Administration" in j.splitlines()
    assert "Computer: Microsoft Word, Excel" in j.splitlines()


def test_single_artifact_blank_is_a_line_break_two_are_a_paragraph_gap():
    j = _join_tab_split_lines(TABBED)
    assert "\nGPA: 3.5\n\nSKILLS\n" in j


def test_name_degree_gpa_and_skills_from_tabbed_text():
    r = parse_resume(TABBED)
    assert r["name"] == "Lee Example"
    edu = r["education"][0]
    assert edu["degree"] == "Bachelor of Arts" and edu["subject"] == "Business Administration"
    # Label and value verbatim; no scale is ever invented.
    assert edu["gpa"] == {"label": "GPA", "value": "3.5"}
    assert {"microsoft word", "excel"} <= set(r["skills"])


def test_text_without_artifact_signature_is_untouched():
    plain = "Sam\ns@example.com\nEducation\nB.E., State University, 2026"
    assert _join_tab_split_lines(plain) == plain
    r = parse_resume(plain)
    assert r["education"][0]["degree"] == "B.E."


def test_bare_page_number_line_is_never_a_name():
    r = parse_resume("2\nLee Example\nlee@example.com\nSkills\nPython, SQL")
    assert r["name"] == "Lee Example"
