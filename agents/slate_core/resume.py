import io
import re
import unicodedata
from .skills import skill_evidence, resume_skill_evidence
from .resume_review import section_previews

MAX_PDF_BYTES = 5_000_000
MAX_RESUME_CHARS = 200_000
MAX_PDF_PAGES = 20

_QUALIFICATION_UNCERTAIN = re.compile(
    r"\b(?:no|not|never|without|lack|lacking|unfamiliar|seeking|aspir(?:e|es|ing)|"
    r"want(?:s)? to|wish(?:es)? to|plan(?:s|ning)? to|hop(?:e|es|ing) to|"
    r"interested in|learning|learn|instruction|example|pursuing|prospective)\b", re.I)

class ParseError(ValueError):
    pass

def parse_resume(text: str) -> dict:
    """Pull name, skills, education and experience from plain resume text."""
    if not isinstance(text, str) or len(text.strip()) < 20:
        raise ParseError("Resume text is empty or too short to parse.")
    if len(text) > MAX_RESUME_CHARS:
        raise ParseError("Resume text is too long (200,000 characters max).")
    text = _without_template_tips(text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        raise ParseError("No resume content remains after removing template guidance.")
    name, name_evidence = name_candidate(lines)
    evidence, uncertain = resume_skill_evidence(text)
    skills = [item["skill"] for item in evidence]
    education, experience = [], []
    for l in qualification_lines(text):
        for part in re.split(r";", l):
            edu = _education_entry(part)
            if edu:
                education.append(edu)
        exp = _experience_entry(l) if l != lines[0] else None
        if exp and not _EDU_WORDS.search(l):
            experience.append(exp)
    return {"name": name, "nameEvidence": name_evidence, "skills": skills, "education": education, "experience": experience,
            "skillEvidence": evidence, "uncertainSkills": uncertain,
            "sectionReview": section_previews(text),
            "parseWarnings": ["Skill candidates from phrase matches and explicit lists, not verified proficiency or a complete resume assessment. "
                              "Review the detected skills; education and work-history extraction are limited."]}

_DEGREE = re.compile(
    r"(?<![a-z])(b\.?\s?tech|m\.?\s?tech|b\.?e\.?|m\.?e\.?|bca|mca|b\.?sc\.?|m\.?sc\.?|b\.?com\.?|m\.?com\.?|"
    r"b\.?a\.?|m\.?a\.?|b\.?ed\.?|m\.?ed\.?|b\.?des\.?|m\.?des\.?|bba|mba|pgdm|b\.?arch|ph\.?d|diploma|bachelor|master)(?![a-z])", re.I)
_EDU_WORDS = re.compile(r"(?<![a-z])(b\.?tech|m\.?tech|bca|mca|b\.?sc|m\.?sc|bachelor|master|mba|pgdm|b\.?com|b\.?ed|b\.?e|b\.?des|m\.?des)(?![a-z])", re.I)
_DATEISH = re.compile(r"^(?:\(?(?:19|20)\d\d(?:\s*[-\u2013to]+\s*(?:(?:19|20)\d\d|present|ongoing))?\)?|cgpa.*|.*cgpa|gpa.*|\d+(?:\.\d+)?\s*(?:/\s*10)?%?)$", re.I)
_TITLES = (r"internship|intern|trainee|developer|analyst|engineer|executive|manager|assistant|associate|designer|consultant|"
           r"officer|teacher|coordinator|specialist|administrator|technician|accountant|recruiter|lead|"
           r"representative|scientist|architect|tutor|coach")
_TITLE_RE = re.compile(r"\b(?:[A-Za-z]+\s){0,3}?(?:" + _TITLES + r")\b", re.I)


def _education_entry(part):
    """Degree, institute and year from one education line; institute only if literally present."""
    part = part.strip().lstrip("-•* ")
    m = _DEGREE.search(part)
    if not m or len(part) > 160:
        return None
    # A degree token must start the line (or follow a bullet), so prose that merely
    # mentions "master" or "B.E." later in a sentence is not promoted to history.
    if m.start() > 3 and not re.match(r"^(?:\W*)(?:completed|pursued|graduated)", part, re.I):
        return None
    y = re.search(r"((?:19|20)\d\d)", part)
    year = None
    if y:
        years = re.findall(r"(?:19|20)\d\d", part)
        year = int(years[-1])
    inst = ""
    segments = [x.strip() for x in re.split(r",|\s[-\u2013]\s", part)[1:]]
    for seg in segments:
        seg = seg.strip(". ")
        if seg and not _DATEISH.match(seg) and not _DEGREE.fullmatch(seg) and len(seg) <= 80:
            inst = seg
            break
    # Source casing is preserved as written (only the '..' artifact is normalized).
    return {"degree": m.group(1).replace("..", "."), "institute": inst, "year": year}


def _experience_entry(line):
    """Title and employer from 'Org, Title, dates', 'Title, Org, dates' or 'Title at Org'."""
    line = line.strip()
    if re.match(r"^[•*\-–]\s", line) or len(line) > 220:
        return None
    head = re.split(r"[:：]", line, 1)[0]
    months = re.search(r"\((\d+)\s*months?\)", line)
    mval = int(months.group(1)) if months else None
    head = re.sub(r"\((?:[^()]*)\)", lambda m: " " if re.search(r"(?:19|20)\d\d|month|present", m.group(0), re.I) else m.group(0), head)
    parts = [x.strip() for x in re.split(r",|\s[-\u2013]\s", head)]
    parts = [x for x in parts if x]
    # structured: some part that is essentially just a job title
    for i, part in enumerate(parts):
        t = _TITLE_RE.fullmatch(re.sub(r"\s*\(.*?\)\s*", " ", part).strip())
        if t:
            others = [x for j, x in enumerate(parts) if j != i]
            for cand in (others[i-1:i] if i >= 1 and len(others) >= i else []) + others:
                cand = re.sub(r"\s*\(.*?\)\s*$", "", cand).strip()
                if cand and not _DATEISH.match(cand) and not _TITLE_RE.fullmatch(cand) and not re.match(r"^(?:built|managed|wrote|led|worked)\b", cand, re.I):
                    return {"title": _TITLE_RE.search(part).group(0).strip(), "org": cand, "months": mval}
            return None
    # prose: "<title> at <Org>"
    m = re.search(r"\b(" + _TITLES + r")\s+(?:at|with|for)\s+((?:[A-Z0-9][\w&.'-]*)(?:\s+(?:[A-Z0-9][\w&.'-]*|&|of|and))*?)(?=\s+(?:in|from|during|since|working|for|where|and)\b|\s*[,.(;]|\s+(?:19|20)\d\d|$)", line, re.I)
    if m and not re.search(r"\b(?:seeking|looking|aspir)", line, re.I):
        org = m.group(2).strip(" .")
        if org and not _DATEISH.match(org):
            return {"title": m.group(1), "org": org, "months": mval}
    return None


def _name_part(line):
    """Keep the name from 'Name - Job Title' / 'Name | City' headers and drop trailing symbols."""
    first = re.split(r"\s[-\u2013\u2014|]\s|\s\|\s|\s{2,}", line, 1)[0].strip()
    if first and first != line and 1 <= len(first.split()) <= 5 and all(
            unicodedata.category(c)[0] in {"L", "M"} or c in " '-’." for c in first):
        return first
    stripped = re.sub(r"[\s\W_]+$", "", line) if re.search(r"[^\w\s'’.-]\s*$", line) else line
    return stripped if stripped and any(c.isalpha() for c in stripped) else line


def name_candidate(lines):
    """A bounded header heuristic, never identity verification.

    Skip only explicit document titles/contact lines before the first content
    line. Never scan past a section or job title hunting for a plausible name.
    """
    titles = {"resume", "résumé", "curriculum vitae", "cv", "bio-data", "biodata"}
    sections = {"skills", "key skills", "technical skills", "education", "experience",
                "work experience", "summary", "profile", "career objective", "objective",
                "compétences", "habilidades", "fähigkeiten", "कौशल", "技能",
                "qualifications", "academic qualifications", "academic details", "education and qualifications", "internship", "internships", "work history", "professional background", "academic background", "formation", "educación", "ausbildung", "शिक्षा", "教育",
                "employment", "employment history", "professional experience", "expérience", "experiencia", "berufserfahrung", "अनुभव", "工作经历"}
    for line in lines[:8]:
        label = line.casefold().rstrip(':：')
        if label in titles:
            continue
        if "@" in line or re.match(r"^(?:e-?mail|phone|mobile|tel|contact|https?://|www\.)\b", line, re.I) or re.fullmatch(r"[+()\d\s.-]{7,}", line):
            continue
        if label in sections:
            break
        if re.match(r"^(?:name|full name)\s*[:：]", line, re.I):
            line = re.sub(r"^(?:name|full name)\s*[:：]\s*", "", line, flags=re.I)
        line = _name_part(line)
        # Names can be one word or contain apostrophes/hyphens. Reject digits,
        # contact syntax and unsupported punctuation, not non-Latin letters.
        if (1 <= len(line.split()) <= 5 and len(line) <= 100
                and all(unicodedata.category(c)[0] in {"L", "M"} or c in " '-’." for c in line)
                and any(c.isalpha() for c in line)):
            return line, {"status": "header_candidate_not_verified", "sourceText": line}
        break
    # No standalone name line: accept only an explicit "<Capitalised Name> is/am ..." opening.
    m = re.match(r"^([A-Z][a-z'’-]+(?:\s[A-Z][a-z'’-]+){1,3})\s+(?:is|am|has)\b", lines[0]) if lines else None
    if m:
        return m.group(1), {"status": "header_candidate_not_verified", "sourceText": m.group(1)}
    return "Unknown", {"status": "not_recognized", "sourceText": None}


def _qualification_uncertain(line):
    """'Example' marks sample/instruction text, but a line that starts with a degree may
    name an institute 'Example University' / 'IIT Example'. Only that shape is exempt;
    every other uncertainty word still applies, and non-degree lines keep 'example'."""
    probe = line.lstrip("-•* ")
    m = _DEGREE.match(probe)
    if m and re.match(r"^(?:\W*|\s+)", probe[m.end():]):
        line = re.sub(r"\bexample\b", " ", line, flags=re.I)
    return bool(_QUALIFICATION_UNCERTAIN.search(line))


def qualification_lines(text):
    """Conservative literal lines eligible for degree/work extraction, not proof."""
    excluded_section = False
    text = _without_template_tips(text)
    for l in text.splitlines():
        l = l.strip()
        label = l.casefold().rstrip(':：')
        if label.startswith("user-provided skill statements"):
            excluded_section = True
            continue
        # Explicit non-history sections can contain degree words and job titles
        # without describing the candidate's qualifications or employment.
        section_label = re.split(r"[:：]", label, maxsplit=1)[0].strip()
        if section_label in {"career objective", "objective", "career goals", "learning goals", "job requirements", "required qualifications", "example", "example experience", "instructions", "tips",
                             "skills", "key skills", "technical skills", "competencies", "core competencies", "compétences", "habilidades", "fähigkeiten", "कौशल", "技能",
                             "projects", "personal projects", "academic projects", "references", "referees", "interests", "hobbies", "interests/hobbies"}:
            excluded_section = True
            continue
        if label in {"education", "qualifications", "academic qualifications", "academic details", "education and qualifications", "internship", "internships", "work history", "professional background", "academic background", "experience", "work experience", "employment", "employment history", "professional experience", "formation", "educación", "ausbildung", "शिक्षा", "教育", "expérience", "experiencia", "berufserfahrung", "अनुभव", "工作经历"}:
            excluded_section = False
            continue
        # A literal degree/job-title mention is not necessarily a qualification.
        # Conservative exclusion keeps ambiguous text available for source review
        # rather than promoting a denial, aspiration or example into history.
        if excluded_section or _qualification_uncertain(l):
            continue
        yield l


def find_skills(text: str) -> list:
    """Canonical skill mentions, including supported spelling/phrase aliases.

    Shared with claim checking. Do NOT strip template guidance here: a draft
    cannot hide a new skill from the claim gate by wrapping it in '(Tip: ...)'.
    """
    return [item["skill"] for item in skill_evidence(text)]


def _without_template_tips(text):
    """Ignore explicitly marked parenthesized resume-template instructions only.

    Handle line wraps and nested parentheses without swallowing later sections
    when an unclosed note occurs. Do not remove arbitrary parenthetical facts.
    """
    pattern = re.compile(r"\(\s*tip\s*:", re.I)
    pos, chunks = 0, []
    while True:
        match = pattern.search(text, pos)
        if not match:
            break
        depth, end = 1, match.end()
        while end < len(text) and depth:
            if text[end] == "(": depth += 1
            elif text[end] == ")": depth -= 1
            end += 1
        if depth:  # keep the unmatched remainder; never rescan it quadratically
            break
        chunks.append(text[pos:match.start()]); chunks.append("\n")
        pos = end
    chunks.append(text[pos:])
    return "".join(chunks)


def _after(line: str, sep: str) -> str:
    return line.split(sep, 1)[1].strip().rstrip(".") if sep in line else ""


def extract_pdf_text(data: bytes) -> str:
    """Pull selectable text out of PDF bytes. Scanned images and broken files raise ParseError."""
    if not data or len(data) > MAX_PDF_BYTES:
        raise ParseError("PDF is empty or larger than 5 MB.")
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ParseError("PDF support (pypdf) is not installed on this server.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ParseError("That PDF is password-protected; export it without a password and retry.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ParseError("PDF has too many pages (20 max). Export only your resume pages and retry.")
        chunks, total = [], 0
        for page in reader.pages:
            chunk = page.extract_text() or ""
            total += len(chunk) + 1
            if total > MAX_RESUME_CHARS:
                raise ParseError("PDF text is too long (200,000 characters max).")
            chunks.append(chunk)
        text = "\n".join(chunks)
    except ParseError:
        raise
    except Exception:
        raise ParseError("Could not read that file as a PDF.")
    if len(text.strip()) < 20:
        raise ParseError("No selectable text found in that PDF (a scanned image will not work).")
    return text
