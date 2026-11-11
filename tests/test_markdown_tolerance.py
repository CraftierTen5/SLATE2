"""Audit F6 pins (10-sample internet audit, 2026-11-11): markdown heading and
emphasis markers must not hide sections, degrees, names or skill lists.
Synthetic fixtures modeled on the public samples; no personal data."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

from slate_core.resume import parse_resume, _education_entry
from slate_core.skills import explicit_skill_evidence


def test_hash_name_header_is_a_name():
    r = parse_resume("# Alex Johnson\nalex@example.com\nSkills\nPython, SQL")
    assert r["name"] == "Alex Johnson"


def test_markdown_degree_line_parses():
    e = _education_entry("### Master of Science in Computer Science")
    assert e["degree"] == "Master of Science in Computer Science"


def test_bold_section_headings_open_and_close_sections():
    r = parse_resume(
        "Sam\ns@example.com\n**Education:**\nB.S., State University, 2020\n"
        "**Experience:**\nSoftware Engineer, Acme Corp, 2020-2023\n- Built services"
    )
    assert r["education"][0]["degree"] == "B.S."
    assert any(e["org"] == "Acme Corp" for e in r["experience"])


def test_markdown_skills_heading_opens_list():
    ev = explicit_skill_evidence("Jo\nj@x.com\n**Skills:**\nPython, Go, Kubernetes")
    assert {e["skill"] for e in ev} >= {"python", "go", "kubernetes"}


def test_institute_first_degree_line():
    e = _education_entry("Example State University, B.A. Communications")
    assert e == {"degree": "B.A.", "institute": "Example State University",
                 "year": None, "subject": "Communications"}


def test_example_instruction_lines_still_excluded():
    r = parse_resume(
        "Sam\ns@example.com\nExample experience:\nSoftware Engineer, Nowhere, 2020\n"
        "Experience\nSoftware Engineer, Acme Corp, 2021-2023\n- Built services"
    )
    assert all(e["org"] != "Nowhere" for e in r["experience"])
