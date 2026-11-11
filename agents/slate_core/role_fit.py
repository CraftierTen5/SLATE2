"""Role-fit guardrail: no blind cross-family tailoring, career switches allowed.

When the target role's family clearly differs from what the resume visibly
shows, a draft may still be created - people change careers - but only after
the user explicitly acknowledges the gap, and the draft record keeps that
acknowledgment. This addresses "do not blindly tailor an SDE resume toward
management/consulting": the switch is not prevented, it is never silent.

Boundaries, stated honestly:
- Family detection is a small literal keyword vocabulary over titles and
  known skill phrases, never a semantic judgment, fit score or
  employability claim. Only titles/skills are scanned, not prose, so a
  negation or incidental mention in a sentence cannot trigger a family.
- Every review returns an explicit evidence state. "unknown" is labeled
  insufficient evidence - it must never read as proof of fit or mismatch.
- The acknowledgment gate is the only new blocker, and it blocks ONLY the
  draft-creation routes until acknowledged. The claim gate (claims.py) stays
  the only check that can reject draft content; facts remain bound to the
  original source exactly as before.

Vocabulary order decides ties: more specific families come first, so
"store manager" classifies as retail_customer_service, not management.
"""

_VOCAB = {
    "engineering_technology": (
        "software", "developer", "sde", "backend", "front-end", "frontend",
        "full stack", "full-stack", "devops", "data analyst", "data scientist",
        "machine learning", "ml engineer", "data engineer", "engineer",
        "programmer", "python", "java", "javascript", "typescript", "react",
        "sql", "docker", "kubernetes", "aws", "fastapi", "pytorch", "c++",
    ),
    "retail_customer_service": (
        "cashier", "cash handling", "retail", "customer service",
        "customer support", "sales associate", "store manager", "hospitality",
        "served customers",
    ),
    "management_consulting": (
        "management consultant", "consulting", "consultant", "strategy",
        "operations manager", "product manager", "program manager",
        "project manager", "business development", "general management",
        "management trainee", "manager", "mba",
    ),
}

MISMATCH = "family_mismatch_needs_acknowledgment"
SAME = "same_keyword_family_not_a_fit_assessment"
INSUFFICIENT = "insufficient_evidence_no_assessment"


def role_family(text) -> str:
    """Classify title/skill text into a known role family, or "unknown".

    "unknown" is the honest answer whenever nothing literal matches; callers
    must treat it as no-evidence, never as a negative finding.
    """
    low = " " + " ".join(str(text or "").lower().split()) + " "
    for family, phrases in _VOCAB.items():
        if any(p in low for p in phrases):
            return family
    return "unknown"


def resume_family(parsed: dict) -> str:
    """The family the resume VISIBLY shows: parsed skills + experience titles.

    Free-text sections are deliberately not scanned: a sentence like "no
    management experience" or "reported to the engineering manager" must not
    classify the resume.
    """
    parts = list((parsed or {}).get("skills", []))
    parts += [e.get("title", "") for e in (parsed or {}).get("experience", [])
              if isinstance(e, dict)]
    return role_family(" ".join(str(p) for p in parts))


def target_family(title, skills=None) -> str:
    """The family the target role names, from its title and required skills."""
    return role_family(" ".join([str(title or "")] + [str(s) for s in (skills or [])]))


def role_fit_review(parsed: dict, title, skills=None) -> dict:
    """The evidence state for a resume/target pair. Always explicit.

    kind=MISMATCH: both families recognized and different - draft routes must
      refuse until the user acknowledges, then keep the label visible.
    kind=SAME: one shared keyword family. Not a fit assessment; the label says
      so, because a keyword overlap must not read as "this person fits".
    kind=INSUFFICIENT: at least one side unrecognized. No distance check was
      possible; that is stated, so silence can never imply fit.
    """
    have, want = resume_family(parsed), target_family(title, skills)
    base = {"reviewKind": "keyword_review_not_a_fit_assessment"}
    if have != "unknown" and want != "unknown" and have != want:
        shown, asked = have.replace("_", " "), want.replace("_", " ")
        return {**base, "kind": MISMATCH, "resumeFamily": have, "targetFamily": want,
                "note": ("This resume visibly shows " + shown + " while the target is "
                         + asked + ". No draft was created yet. If this role change "
                         "is intended, acknowledge it explicitly; the draft will keep "
                         "the original facts unchanged and add nothing about fit.")}
    if have != "unknown" and have == want:
        return {**base, "kind": SAME, "resumeFamily": have, "targetFamily": want,
                "note": ("Resume and target share the keyword family "
                         + have.replace("_", " ") + ". This is a literal keyword "
                         "grouping, not a fit assessment or a match quality score.")}
    return {**base, "kind": INSUFFICIENT, "resumeFamily": have, "targetFamily": want,
            "note": ("Role family could not be determined for "
                     + ("the resume" if have == "unknown" else "the target")
                     + (" or both" if have == want == "unknown" else "")
                     + " from a small keyword vocabulary, so no distance check was "
                     "possible. This is insufficient evidence - not evidence of fit "
                     "or of mismatch.")}
