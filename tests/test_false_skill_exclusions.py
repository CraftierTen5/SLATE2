"""Audit F1 pins (10-sample internet audit, 2026-11-11): section-heading words
and PDF-wrapped 'skills.' prose fragments must never become earned skills.
Synthetic fixtures modeled on the public samples; no personal data."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agents'))
from slate_core.resume import parse_resume


def test_positions_of_responsibility_heading_is_not_a_skill():
    text = (
        "Ananya Kulkarni\n"
        "Skills\n"
        "Technical: Java, Python, Git\n"
        "Education\n"
        "B.E., Computer Engineering\n"
        "Positions of Responsibility\n"
        "- Technical head, college coding club: ran weekly sessions for juniors\n"
    )
    parsed = parse_resume(text)
    assert "responsibility" not in parsed["skills"]
    assert all(e["skill"] != "responsibility" for e in parsed["skillEvidence"])
    flagged = parsed.get("uncertainSkills", [])
    assert any(e["skill"] == "responsibility" and "heading" in e["reason"] for e in flagged)


def test_take_responsibility_skill_list_line_still_counts():
    # The retail fixture earned 'responsibility' from a skills-list sentence,
    # which is a genuine candidate claim and must keep working.
    text = (
        "Alex Example\n"
        "Key Skills\n"
        "Able to take responsibility and solve problems.\n"
    )
    parsed = parse_resume(text)
    assert "responsibility" in parsed["skills"]


def test_wrapped_prose_skills_fragment_does_not_open_a_skills_section():
    # PDF extraction wrapped "...communication skills." so 'skills.' sat alone
    # on a line; the following involvement bullet must not become skill items.
    text = (
        "Leo Leopard\n"
        "Objective\n"
        "To obtain a position which utilizes my strong communication\n"
        "skills.\n"
        "\n"
        "On Campus Involvement\n"
        "Member\n"
        "- Led groups of 9 students in discussion on success skills, business ethics, and personal\n"
        "finances\n"
    )
    parsed = parse_resume(text)
    assert "ethics" not in parsed["skills"]
    assert "business ethics" not in parsed["skills"]
    assert all("ethic" not in e["skill"] for e in parsed["skillEvidence"])
    # The genuine mention of communication in the objective still counts.
    assert "communication" in parsed["skills"]


def test_skills_comma_fragment_does_not_open_a_skills_section():
    text = (
        "Leo Leopard\n"
        "Objective\n"
        "Using my teamwork and organizational\n"
        "skills,\n"
        "I contribute to group projects.\n"
        "- Built models with MATLAB, and presented findings\n"
    )
    parsed = parse_resume(text)
    assert "and presented findings" not in parsed["skills"]
    assert all("presented findings" not in e["skill"] for e in parsed["skillEvidence"])
    assert "matlab" in parsed["skills"]


def test_languages_and_achievements_headings_end_skills_mode():
    text = (
        "Sneha Kulkarni\n"
        "Skills\n"
        "Technical: SQL, Python\n"
        "Achievements\n"
        "- Top 40 of 600 teams, Smart India Hackathon\n"
        "Languages\n"
        "- English\n- Hindi\n"
    )
    parsed = parse_resume(text)
    assert set(parsed["skills"]) >= {"sql", "python"}
    assert all("hackathon" not in e["skill"] for e in parsed["skillEvidence"])
    assert "english" not in parsed["skills"] and "hindi" not in parsed["skills"]


def test_study_line_without_degree_token_does_not_earn_the_subject_as_a_skill():
    # Audit D1 original repro: "She studied Communication Design at NID
    # Ahmedabad" has no degree token, yet 'communication' was accepted as an
    # earned skill. Studying a subject is never an earned credential.
    text = (
        "Riya Sharma\n"
        "She studied Communication Design at NID Ahmedabad, graduating in 2026.\n"
        "Skills: Figma, user research\n"
    )
    parsed = parse_resume(text)
    assert "communication" not in parsed["skills"]
    assert all(e["skill"] != "communication" for e in parsed["skillEvidence"])
    assert any(e["skill"] == "communication" and "study" in e["reason"] for e in parsed["uncertainSkills"])
    # The study line still parses as a labeled subject of study, not a degree.
    assert parsed["education"][0]["subjectOnly"] is True
    assert parsed["education"][0]["degree"] == "Communication Design"
    # Genuine skill-list mentions elsewhere are unaffected.
    assert "figma" in parsed["skills"]


def test_genuine_mention_off_the_study_line_still_counts():
    text = (
        "Riya Sharma\n"
        "She studied Communication Design at NID Ahmedabad in 2026.\n"
        "Work Experience\n"
        "Led client communication for a design studio.\n"
    )
    parsed = parse_resume(text)
    assert "communication" in parsed["skills"]
