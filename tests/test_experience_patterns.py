"""Audit F3 pins (10-sample internet audit, 2026-11-11): experience extraction
must handle the dominant real-world formats - 'Title · Org', markdown heading
prefixes, org/dates on adjacent lines - and stay fail-closed on headlines.
Synthetic fixtures modeled on the public samples; no personal data."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

from slate_core.resume import parse_resume, _experience_entry


def test_dot_separator_title_org():
    e = _experience_entry("Software Engineering Intern · Tarangan Fintech Solutions")
    assert e == {"title": "Software Engineering Intern", "org": "Tarangan Fintech Solutions", "months": None}


def test_title_level_suffix_preserved():
    e = _experience_entry("Mechanical Design Engineer II · Brightwater Fluid Systems")
    assert e["title"] == "Mechanical Design Engineer II"
    assert e["org"] == "Brightwater Fluid Systems"


def test_markdown_heading_prefix():
    e = _experience_entry("### Support Operations Specialist, ExampleSoft")
    assert e["org"] == "ExampleSoft"


def test_emdash_trailing_clause_does_not_break_or_leak():
    e1 = _experience_entry("Acme Corp, Senior Backend Engineer — building onboarding flows")
    e2 = _experience_entry("Senior Backend Engineer — Acme Corp, building onboarding flows")
    assert e1["org"] == "Acme Corp" and e2["org"] == "Acme Corp"


def test_org_on_next_line_markdown():
    r = parse_resume(
        "ALEX JOHNSON\nalex@example.com\nWork Experience:\n"
        "### Senior Software Engineer\n**TechCorp Inc.** | San Francisco, CA\n"
        "*Jan 2020 - Present*\n- Led development of services"
    )
    assert r["experience"] == [
        {"title": "Senior Software Engineer", "org": "TechCorp Inc.", "months": None}]


def test_org_on_previous_line_pdf_flattened():
    r = parse_resume(
        "John Doe\nSoftware engineer obsessed with building products\nhello@example.com\n"
        "EXPERIENCE\nABC Company\nSoftware Engineer\nMay 2023 - Present\n- Lead a team of five\n"
        "DEF Organization\nSoftware Engineer Intern\nSummer 2022\n- Re-architected the editor"
    )
    assert r["experience"] == [
        {"title": "Software Engineer", "org": "ABC Company", "months": None},
        {"title": "Software Engineer Intern", "org": "DEF Organization", "months": None}]


def test_skill_headline_is_not_a_job():
    r = parse_resume(
        "Fresher Dev\nf@example.com\nSUMMARY\n"
        "Software Engineer (Fresher) · Java, DSA, Spring Boot\n"
        "EXPERIENCE\nSoftware Intern · Some Co\n2023\n- Built things"
    )
    assert all(e["org"] != "Java" for e in r["experience"])
    assert {"title": "Software Intern", "org": "Some Co", "months": None} in r["experience"]


def test_name_header_is_not_an_org():
    r = parse_resume("ALEX JOHNSON\n## Software Engineer\nalex@example.com\nSKILLS\nPython, SQL")
    assert r["experience"] == []


def test_first_line_name_is_not_an_org():
    # The title-only headline under a name header must not join the name as org.
    r = parse_resume(
        "Jane Doe\nSenior Backend Engineer\njane.doe@example.com\nEXPERIENCE\n"
        "Senior Backend Engineer, Acme Corp, 2021-present\n- Built services on Node.js"
    )
    assert r["experience"] == [
        {"title": "Senior Backend Engineer", "org": "Acme Corp", "months": None}]


def test_lone_word_context_is_not_an_org():
    # Tab-split "Volunteer / Swim / Coach": 'Swim' is not an employer.
    r = parse_resume(
        "Sam Reid\ns@example.com\nVOLUNTEERING\nSummer 2013\nVolunteer\nSwim\nCoach\n"
        "- Instructed classes of up to 15 children"
    )
    assert all(e["org"] != "Swim" for e in r["experience"])


def test_dot_focus_area_headline_is_not_a_job():
    # 'Role · focus area' headline: single dot segment without an org suffix fails closed.
    assert _experience_entry("Mechanical Design Engineer · Product Development & DFM") is None
