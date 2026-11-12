"""Deterministic, evidence-labelled career learning plans.

The roadmap is a practice planner, not a hiring prediction or employability score.
"""
from .sample_data import JOBS, LEARNING


def _milestone(skill, count, total, source_label):
    title, resources, weeks = LEARNING.get(skill, (f"Learn {skill}", [], 2))
    return {
        "title": title,
        "skill": skill,
        "phase": "Build foundations" if weeks <= 2 else "Develop applied skill",
        "why": (f"{skill} is not listed among the resume's recognized skills and "
                f"appears in {count} of {total} {source_label}. This is a keyword gap, "
                "not proof that you lack the skill."),
        "resources": resources,
        "etaWeeks": weeks,
        "estimatedHours": max(3, weeks * 4),
        "practiceTask": (f"Complete a small, role-relevant exercise using {skill}; "
                         "document the problem, your approach, and the result."),
        "completionCriteria": [
            f"Finish one hands-on exercise using {skill}.",
            "Save a working artifact, notes, or a reproducible result.",
            "Explain one design choice and one limitation without relying on a tutorial."
        ],
        "status": "not_started",
        "evidenceSource": source_label,
    }


def build_roadmap(parsed: dict, target_role: str, target: dict | None = None) -> list:
    """Build a plan from a saved target snapshot or matching sample listings.

    Saved targets contribute only known-vocabulary mentions. Unknown requirements
    remain unassessed in the source text and are never called gaps.
    """
    role = (target_role or "").strip()
    have = {str(s).strip().lower() for s in (parsed or {}).get("skills", [])}
    if target is not None:
        required = sorted({str(s).strip().lower() for s in target.get("skills", []) if s})
        if not required:
            return []
        missing = [s for s in required if s not in have]
        return [_milestone(s, 1, len(required), "known skill mentions in your saved target")
                for s in missing]

    if not role:
        return []
    jobs = [j for j in JOBS if role.lower() in j["title"].lower()]
    if not jobs:
        return []
    count = {}
    for job in jobs:
        for skill in job["skills"]:
            if skill not in have:
                count[skill] = count.get(skill, 0) + 1
    ordered = sorted(count, key=lambda skill: (-count[skill], skill))
    return [_milestone(skill, count[skill], len(jobs), f"{role} sample listings")
            for skill in ordered]
