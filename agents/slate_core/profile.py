"""Confirmed profile answers: collected once, reused, never guessed.

Applications keep asking for the same personal answers (name, email, phone,
location, links). Slate stores them as ONE profile per user. A value becomes
an answer only when the user explicitly confirms it. Anything the user has
not answered stays unknown: no feature may fill it from a guess, parsed
resume text, or a job description.

- suggest_from_text() finds literal candidates in an uploaded resume. They
  are review candidates only, never answers on their own.
- normalize_answers() accepts only the bounded field vocabulary and rejects
  malformed values, so no feature can quietly store new kinds of personal
  facts or skip validation.
- profile_answers() is the reuse contract: a feature asks for the fields it
  needs and receives confirmed values plus the list still unknown, which the
  UI surfaces as gaps to ask about - never blanks to invent.

Confirmed answers are user statements, stored per user in the same state
document as resumes and drafts. They are not independently verified.
"""
import re

# Bounded vocabulary with per-field length caps. A field not listed here
# cannot be stored at all.
FIELDS = {"name": 120, "email": 254, "phone": 40, "location": 120,
          "linkedin": 300, "github": 300, "portfolio": 300}
_LINK_FIELDS = ("linkedin", "github", "portfolio")

# Answers an application draft header typically needs. Gaps are reported for
# these; the other fields are reused when present without being demanded.
DRAFT_NEEDS = ("email", "phone")

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.I)
_PHONE_TAIL = re.compile(r"(\+?\d[\d\s()./-]{5,}\d)")
_EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DOMAIN_SHAPE = re.compile(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/\S*)?$")
_PHONE_SHAPE = re.compile(r"[+()\d][+()\d\s./-]*")


def _suggest_phone(line):
    # Emails and URLs on the same line are not part of a phone number.
    line = _URL.sub(" ", _EMAIL.sub(" ", line))
    m = _PHONE_TAIL.search(line)
    if not m:
        return None
    text = m.group(1).strip()
    digits = re.sub(r"\D", "", text)
    # A bare year or year range (2027, 2023-2027) is not a phone number.
    if len(digits) < 7 or (not text.startswith("+") and len(digits) < 9):
        return None
    return text


def suggest_from_text(source_text, parsed=None):
    """Candidate profile answers found literally in the uploaded resume text.

    Returns {field: value} only for fields with a literal candidate. Every
    suggestion is a review candidate, not an answer; a field the resume does
    not show has no suggestion, never a guessed value.
    """
    found = {}
    for line in (source_text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if "email" not in found:
            m = _EMAIL.search(line)
            if m:
                found["email"] = m.group(0)
        if "phone" not in found:
            phone = _suggest_phone(line)
            if phone:
                found["phone"] = phone
        for url in _URL.findall(line):
            low = url.lower()
            field = ("linkedin" if "linkedin.com" in low
                     else "github" if "github.com" in low
                     else "portfolio")
            found.setdefault(field, url.rstrip(".,;)"))
    name = (parsed or {}).get("name")
    if name and name != "Unknown":
        found.setdefault("name", name)
    return {f: found[f] for f in FIELDS if f in found}


def normalize_answers(answers):
    """Validate and trim user-confirmed answers. Fail closed on bad input.

    Only known fields are accepted; empty values count as unanswered and stay
    unknown. Raises ValueError with a human-readable reason otherwise.
    """
    if not isinstance(answers, dict):
        raise ValueError("answers must be an object of field names to values.")
    unknown = sorted(set(answers) - set(FIELDS))
    if unknown:
        raise ValueError("unsupported profile field(s): " + ", ".join(unknown))
    clean = {}
    for field, raw in answers.items():
        if not isinstance(raw, str):
            raise ValueError(field + " must be text.")
        value = re.sub(r"\s+", " ", raw).strip()
        if not value:
            continue
        if len(value) > FIELDS[field]:
            raise ValueError("%s is too long (max %d characters)." % (field, FIELDS[field]))
        if field == "email":
            if not _EMAIL_SHAPE.match(value):
                raise ValueError("email must look like an email address.")
        elif field in _LINK_FIELDS:
            if not (_URL.match(value) or _DOMAIN_SHAPE.match(value)):
                raise ValueError(field + " must be a URL or a domain.")
            if not _URL.match(value):
                value = "https://" + value
        elif field == "phone":
            if not _PHONE_SHAPE.fullmatch(value) or len(re.sub(r"\D", "", value)) < 5:
                raise ValueError("phone must be a phone number.")
        clean[field] = value
    return clean


def profile_answers(profile, needed):
    """The reuse contract: confirmed values for `needed`, and what stays unknown.

    Callers must use only the returned answers and surface `missing` as fields
    to ask the user about. Missing fields are never filled from any source.
    """
    stored = (profile or {}).get("answers", {})
    return {"answers": {f: stored[f] for f in needed if f in stored},
            "missing": [f for f in needed if f not in stored]}


def profile_view(profile):
    """API shape: confirmed answers plus the fields still unknown."""
    if not profile:
        return {"status": "not_started", "answers": {},
                "unknownFields": list(FIELDS),
                "source": "no_profile_saved"}
    answers = profile.get("answers", {})
    return {"status": profile.get("status", "user_confirmed"),
            "answers": dict(answers),
            "unknownFields": [f for f in FIELDS if f not in answers],
            "source": profile.get("source", "user_confirmed_answers_not_independently_verified")}


def confirmed_contact_lines(profile):
    """Draft header lines built ONLY from confirmed profile answers.

    Returns [] when nothing relevant is confirmed, so drafts created without
    a profile stay byte-identical to before this feature existed.
    """
    stored = (profile or {}).get("answers", {})
    contact = " | ".join(stored[f] for f in ("email", "phone", "location") if f in stored)
    links = " | ".join(stored[f] for f in _LINK_FIELDS if f in stored)
    lines = []
    if contact:
        lines.append("Contact: " + contact)
    if links:
        lines.append("Links: " + links)
    return lines
