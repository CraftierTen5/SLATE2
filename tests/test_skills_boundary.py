"""Audit F5 pins (10-sample internet audit, 2026-11-11): a blank line or a new
section heading ends skills-list continuation; content after it is scanned
normally. Synthetic fixtures modeled on the public samples; no personal data."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

from slate_core.resume import parse_resume


def test_experience_after_skills_section_and_blank_line():
    r = parse_resume(
        "Riya Sharma\nriya@example.com\nSummary\nFinal-year student.\n"
        "Skills:\nPython, SQL, Excel\n\n"
        "Software Engineering Intern, Tarangan Fintech Solutions, 2024\n"
        "Education\nB.E., State University, 2026"
    )
    assert {"title": "Software Engineering Intern",
            "org": "Tarangan Fintech Solutions", "months": None} in r["experience"]
    assert r["education"][0]["degree"] == "B.E."


def test_continuation_without_blank_stays_in_skills_section():
    r = parse_resume(
        "Riya Sharma\nriya@example.com\nSkills:\nPython, SQL\n"
        "Software Engineer, Acme, 2020\nEducation\nB.E., State University, 2026"
    )
    assert r["experience"] == []


def test_blank_line_ends_objective_section():
    r = parse_resume(
        "Sam\ns@example.com\nCareer Objective\nSeeking a challenging role.\n\n"
        "Software Engineer, Acme Corp, 2020-2023\n- Built services"
    )
    assert any(e["org"] == "Acme Corp" for e in r["experience"])


def test_section_heading_still_ends_list():
    r = parse_resume(
        "Sam\ns@example.com\nSkills:\nPython, SQL\nExperience\n"
        "Software Engineer, Acme Corp, 2020-2023\n- Built services"
    )
    assert any(e["org"] == "Acme Corp" for e in r["experience"])


def test_projects_section_does_not_leak_team_lead_as_employment():
    r = parse_resume(
        "Aman\na@example.com\nSkills:\nPython, SQL\n\nProjects\n\n"
        "Team lead, Clinic Appointment and Billing System\n"
        "- Built the billing module\n\nEducation\nB.E., State University, 2026"
    )
    assert all("Clinic" not in e["org"] for e in r["experience"])
