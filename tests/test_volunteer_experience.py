"""Audit F11 pins (10-sample internet audit, 2026-11-11): volunteer sections
and the reversed org / dates / title layout. Synthetic fixtures modeled on
the public samples; no personal data."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

from slate_core.resume import parse_resume

SAMPLE = ("Sam Example\ns@example.com\nVolunteer Experience\n"
          "Riverdale Food Bank, Springfield, IL\nJune 2012 – Present\nVolunteer\n"
          "- Plan two yearly outreach events\n\n"
          "YMCA, Springfield, IL\nSummer 2013, 2014\nVolunteer Swim Coach\n"
          "- Instructed classes of up to 15 children\n")


def test_reversed_org_dates_title_layout():
    r = parse_resume(SAMPLE)
    assert {"title": "Volunteer", "org": "Riverdale Food Bank", "months": None} in r["experience"]
    assert {"title": "Volunteer Swim Coach", "org": "YMCA", "months": None} in r["experience"]


def test_all_caps_lone_word_without_location_is_still_not_an_org():
    r = parse_resume(
        "Sam Example\ns@example.com\nExperience\nJANE\nSwim Coach\n- Taught laps\n")
    assert all(e["org"] != "JANE" for e in r["experience"])


def test_month_and_season_date_lines_are_not_orgs():
    r = parse_resume(SAMPLE)
    assert all("2012" not in e["org"] and "2013" not in e["org"] for e in r["experience"])
