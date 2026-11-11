"""Tailoring with a claim check: every skill the draft claims must come from the parsed resume."""
from .jobs import skill_breakdown, _norm
from .profile import DRAFT_NEEDS, confirmed_contact_lines, profile_answers

def build_draft(parsed: dict, job: dict, profile: dict = None) -> dict:
    # Same matching as the match explanation (jobs.py): case/whitespace ignored,
    # a repeated required skill counts once, the job's own wording is kept.
    matched, missing = skill_breakdown(parsed["skills"], job["skills"])
    name = parsed["name"]
    # Reuse only confirmed profile answers (profile feature). Unknown answers
    # are reported as profileGaps for the UI to ask about, never filled in.
    gaps = list(profile_answers(profile, DRAFT_NEEDS)["missing"])
    # An unparseable name is never guessed and never printed as a placeholder:
    # use a confirmed profile answer when one exists, else omit the line and
    # ask for it through the same confirmation flow.
    if name == "Unknown":
        confirmed_name = profile_answers(profile, ("name",))["answers"].get("name")
        if confirmed_name:
            name = confirmed_name
        else:
            name = None
            gaps = ["name"] + gaps
    contact = confirmed_contact_lines(profile)
    resume = ([f"{name}"] if name else []) + contact + [f"Target role: {job['title']} at {job['company']}", "",
              "Relevant skills: " + (", ".join(matched) if matched else "none listed yet")]
    for e in parsed["experience"]:
        resume.append(f"Experience: {e['title']}, {e['org']}")
    for e in parsed["education"]:
        # Institute is parsed with source casing; render it when literally present.
        # A prose "studied X" subject is labeled as study, never as an earned degree.
        line = (f"Education: Studied {e['degree']}" if e.get("subjectOnly") else f"Education: {e['degree']}")
        line += f", {e['institute']}" if e.get("institute") else ""
        if e.get("gpa"):
            line += f", {e['gpa']['label']} {e['gpa']['value']}"
        resume.append(line + (f" ({e['year']})" if e["year"] else ""))
    # Never assert content the parser did not extract (e.g. projects): the
    # closing stays neutral about what the candidate can discuss.
    note = (f"Hello {job['company']} team, I am applying for the {job['title']} role. "
            + (f"My background includes {', '.join(matched)}. " if matched else "")
            + "I would be glad to discuss the role further.")
    return {"tailoredResume": "\n".join(resume), "coverNote": note, "claims": matched, "gaps": missing,
            "profileGaps": gaps}

def check_claims(parsed: dict, claims: list) -> list:
    """Return claims that are NOT backed by the resume (same normalization as matching)."""
    have = {_norm(s) for s in parsed["skills"]}
    return [c for c in claims if _norm(c) not in have]
