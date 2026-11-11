"""Deterministic claim validation for draft text. Fail closed.

What it does check (rule based, not semantic):
- skills: any known skill named in the draft must be on the parsed resume
- numbers: "N years/months" of experience must not exceed the resume's total experience;
  percentages and GPA/CGPA values must appear in the original resume text
- degrees: a degree named in the draft (B.Tech, M.Tech, MBA, PhD, ...) must appear in the resume text
What it does NOT check: paraphrased or implied claims, employers or projects named in free text,
job titles, tone. A draft that passes is "no rule-detectable unsupported claim", not "verified true".
"""
import re
from .resume import find_skills, qualification_lines

DEGREES = ["b.tech", "btech", "m.tech", "mtech", "mba", "ph.d", "phd", "bca", "mca", "b.sc", "m.sc", "bachelor", "master"]

def _norm(s: str) -> str:
    return re.sub(r"[\s]+", " ", s.lower())

def total_months(parsed: dict) -> int:
    return sum(e.get("months") or 0 for e in parsed.get("experience", []))

def validate(parsed: dict, resume_text: str, *texts: str, allowed_mentions=()) -> list:
    """Return a list of human-readable violations; empty list means no rule-detectable problem.

    allowed_mentions: exact strings the generator legitimately quotes - the
    target's own title and company. Only verifiable REFERENCE contexts are
    exempt: the stored exact title/company on a "Target role:" line, the phrase "applying for the
    <title> role", and the greeting "Hello <company> team". Anything else on
    those lines stays checked. The same words in
    any other context stay subject to every check, so a first-person
    assertion containing the exact title ("Previously worked as a Machine
    Learning Engineer") is still caught.
    """
    problems = []
    body = "\n".join(t for t in texts if t)
    mentions = [m.strip() for m in allowed_mentions if isinstance(m, str) and m.strip()]
    if mentions:
        def _strip_refs(line):
            # A 'Target role:' line is a reference, but only the stored exact
            # title/company are exempt - anything else appended to the line
            # remains fully checked.
            if line.lstrip().lower().startswith("target role:"):
                for m in mentions:
                    line = re.sub(r"(?<!\w)" + re.escape(m) + r"(?!\w)", " ", line, flags=re.I)
            return line
        body = "\n".join(_strip_refs(line) for line in body.split("\n"))
        for m in mentions:
            body = re.sub(r"(?<!\w)applying for the " + re.escape(m) + r" role(?!\w)", " ", body, flags=re.I)
            body = re.sub(r"(?<!\w)hello " + re.escape(m) + r" team(?!\w)", " ", body, flags=re.I)
    low, src = _norm(body), _norm(resume_text)
    for s in find_skills(body):
        if s not in parsed["skills"]:
            problems.append(f"skill '{s}' is not on the resume")
    have_months = total_months(parsed)
    for n, unit in re.findall(r"(\d+(?:\.\d+)?)\s*\+?\s*(years?|yrs?|months?)", low):
        months = float(n) * (12 if unit.startswith(("y",)) else 1)
        if months > have_months:
            problems.append(f"experience claim '{n} {unit}' exceeds the resume's {have_months} months")
    for num in re.findall(r"(\d+(?:\.\d+)?)\s*%", low):
        if not re.search(r"(?<![\d.])" + re.escape(num) + r"\s*%", src):
            problems.append(f"percentage '{num}%' is not in the resume")
    for num in re.findall(r"c?gpa[^0-9]{0,12}(\d+(?:\.\d+)?)", low):
        if not re.search(r"(?<![\d.])" + re.escape(num) + r"(?![\d])", src):
            problems.append(f"GPA value '{num}' is not in the resume")
    degree_src = _norm("\n".join(qualification_lines(resume_text)))
    for d in DEGREES:
        if re.search(r"(?<![a-z.])" + re.escape(d) + r"(?![a-z])", low) and not re.search(r"(?<![a-z.])" + re.escape(d) + r"(?![a-z])", degree_src):
            problems.append(f"degree '{d}' is not on the resume")
    return problems
