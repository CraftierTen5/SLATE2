"""Audit F7 pins (10-sample internet audit, 2026-11-11): skills sections whose
list starts after a blank line, sub-labeled lists, and the .NET/mechanical
vocabulary the samples use. Synthetic fixtures modeled on the public samples;
no personal data."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

from slate_core.resume import parse_resume
from slate_core.skills import skill_evidence, explicit_skill_evidence


def test_blank_line_between_heading_and_inline_list():
    r = parse_resume("Sam\ns@example.com\nSkills\n\nNode.js, JavaScript, ticket triage\n\nEducation\nB.A., State University, 2020")
    skills = set(r["skills"])
    assert {"node.js", "javascript", "ticket triage"} <= skills


def test_blank_line_between_heading_and_bullet_list():
    r = parse_resume("Sam\ns@example.com\nSkills\n\n- C#\n- ASP.NET Core\n- Entity Framework Core\n\nEducation\nB.E., State University, 2026")
    skills = set(r["skills"])
    assert {"c#", "asp.net core", "entity framework"} <= skills


def test_blank_after_items_still_ends_list():
    r = parse_resume("Sam\ns@example.com\nSkills\nPython, SQL\n\nSoftware Engineer, Acme Corp, 2020-2023\n- Built services")
    assert any(e["org"] == "Acme Corp" for e in r["experience"])


def test_sub_label_prefix_is_not_an_item():
    ev = explicit_skill_evidence("Sam\nSkills\n\nTechnical: SolidWorks, GD&T (ASME Y14.5), ANSYS Mechanical (FEA)")
    skills = {e["skill"] for e in ev}
    assert "solidworks" in skills
    assert not any(s.startswith("technical") for s in skills)


def test_dotnet_and_mechanical_vocabulary():
    text = "Built ASP.NET Core APIs in C# with Entity Framework Core and Node.js tooling. Ran ANSYS FEA, applied GD&T and owned DFMEA."
    skills = {e["skill"] for e in skill_evidence(text)}
    assert {"c#", "asp.net core", "entity framework", "node.js", "ansys", "fea", "gd&t", "dfmea"} <= skills


def test_go_as_ordinary_prose_is_not_a_skill():
    assert not any(e["skill"] == "go" for e in skill_evidence("Willing to go the extra mile on the go."))


def test_colon_label_line_ends_section_before_fragments():
    # Tab-split PDF text wraps a sub-labeled line; fragments after the label
    # line must not leak in as skills.
    r = parse_resume("Sam\ns@example.com\nSkills\n\nComputer:\nProficient in Windows\nOS,\nWord,\n\nEducation\nB.A., State University, 2020")
    assert "os" not in r["skills"] and "word" not in r["skills"]


def test_past_tense_bullet_fragment_is_not_a_skill():
    ev = explicit_skill_evidence("Sam\nskills\n\n• Communicated\nregularly with parents")
    assert "communicated" not in {e["skill"] for e in ev}


def test_orphan_closing_paren_stripped_from_item():
    ev = explicit_skill_evidence("Sam\nSkills\nPython (pandas, Matplotlib), SQL")
    assert "matplotlib" in {e["skill"] for e in ev}
