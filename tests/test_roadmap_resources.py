"""Roadmap quality: actionable milestones with explicit evidence boundaries."""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
from slate_core.roadmap import build_roadmap  # noqa: E402
from slate_core.sample_data import JOBS, KNOWN_SKILLS, LEARNING  # noqa: E402

PARSED = {"name": "Asha Verma", "skills": ["python", "git"], "education": [], "experience": []}


def test_every_known_skill_has_a_learning_entry_with_a_resource():
    for skill in KNOWN_SKILLS:
        title, resources, weeks = LEARNING.get(skill, (None, [], 0))
        assert title, f"no LEARNING entry for {skill}"
        assert resources, f"no resources for {skill}"
        assert weeks >= 1


def test_resources_carry_links_or_actions():
    for skill, (_, resources, _) in LEARNING.items():
        for resource in resources:
            assert " - http" in resource or resource.startswith("Practice:"), skill


def test_roadmap_why_cites_listing_evidence():
    milestones = build_roadmap(PARSED, "Data Analyst")
    assert milestones
    match = re.search(r"appears in (\d+) of (\d+)", milestones[0]["why"])
    expected = len([job for job in JOBS if "data analyst" in job["title"].lower()])
    assert match and int(match.group(1)) >= 1 and int(match.group(2)) == expected


def test_roadmap_orders_by_demand_then_alphabetical():
    milestones = build_roadmap(
        {"name": "X", "skills": [], "education": [], "experience": []},
        "Machine Learning Engineer",
    )
    assert [m["skill"] for m in milestones] == ["python", "pytorch", "sql", "statistics"]
    assert all(m["resources"] and m["etaWeeks"] >= 1 for m in milestones)


def test_milestones_are_actionable_and_have_completion_criteria():
    milestones = build_roadmap(PARSED, "Data Analyst")
    assert all(m["practiceTask"] for m in milestones)
    assert all(len(m["completionCriteria"]) >= 2 for m in milestones)
    assert all(m["estimatedHours"] >= 1 for m in milestones)


def test_saved_target_drives_roadmap_without_sample_role_matching():
    target = {
        "title": "Platform Engineer Intern",
        "skills": ["python", "docker", "kubernetes"],
        "rawText": "Must know Python, Docker, Kubernetes and distributed systems.",
        "sourceKind": "user_pasted_not_verified",
    }
    milestones = build_roadmap(PARSED, "ignored role text", target=target)
    assert [m["skill"] for m in milestones] == ["docker", "kubernetes"]
    assert all("saved target" in m["evidenceSource"] for m in milestones)
    assert all("not proof that you lack" in m["why"] for m in milestones)


def test_unknown_requirements_are_not_invented_as_gaps():
    target = {
        "title": "Specialist",
        "skills": ["python"],
        "rawText": "Must know Python and proprietary internal tooling.",
    }
    milestones = build_roadmap(PARSED, "Specialist", target=target)
    assert milestones == []


def test_unknown_role_still_empty():
    assert build_roadmap(PARSED, "Underwater Basket Weaver") == []
