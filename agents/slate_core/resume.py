import io
import re
import unicodedata
from .skills import skill_evidence, resume_skill_evidence, _DEGREE, _SECTION_HEADING
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


def _join_tab_split_lines(text: str) -> str:
    """Rejoin tabular-PDF word fragments into logical lines.

    pdftotext on tabular templates emits one word per physical line:
    'word\\t', newline, ' \\xa0word'. A fragment ends with a tab and the next
    fragment starts with whitespace; lines made only of tabs/spaces/nbsp are
    the real (visual) line breaks. Text without that signature is returned
    unchanged, so ordinary resumes are untouched. Form feeds are page breaks
    and soft hyphens are invisible; both are dropped inside artifact text.
    """
    if "\t\n" not in text and "\xa0" not in text and "\t\r" not in text:
        return text
    # pypdf emits the same fragments separated by '\t\r \xa0' within a line.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\x0c", "\n").replace("\xad", "")
    out, current, blanks, prev_ended_tab = [], None, 0, False
    for raw in text.split("\n"):
        content = raw.strip("\t \xa0")
        if not content:
            if current is not None:
                out.append(current)
                current = None
            blanks += 1
            prev_ended_tab = False
            continue
        # One artifact-blank line is a visual line break; two or more are a
        # real paragraph gap.
        if current is None and out and blanks >= 2:
            out.append("")
        blanks = 0
        if current is not None and prev_ended_tab and raw[:1] in (" ", "\t", "\xa0"):
            current += " " + content
        else:
            if current is not None:
                out.append(current)
            current = content
        prev_ended_tab = raw.endswith("\t")
    if current is not None:
        out.append(current)
    return "\n".join(out)

def parse_resume(text: str) -> dict:
    """Pull name, skills, education and experience from plain resume text."""
    if not isinstance(text, str) or len(text.strip()) < 20:
        raise ParseError("Resume text is empty or too short to parse.")
    if len(text) > MAX_RESUME_CHARS:
        raise ParseError("Resume text is too long (200,000 characters max).")
    text = _join_tab_split_lines(text)
    text = _without_template_tips(text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        raise ParseError("No resume content remains after removing template guidance.")
    name, name_evidence = name_candidate(lines)
    evidence, uncertain = resume_skill_evidence(text)
    skills = [item["skill"] for item in evidence]
    education, experience = [], []
    qlines = list(qualification_lines(text))
    joined_ctx = set()  # qline indices already consumed as another entry's context
    for qi, l in enumerate(qlines):
        for part in re.split(r";", l):
            edu = _education_entry(part) or _school_entry(part)
            if edu:
                # Templates often put dates and the institute on their own lines:
                # degree / 2024 - 2026 / Institute · score. Join them, fail closed.
                if not edu.get("institute"):
                    end_year, ctx, gpa_ctx = None, None, None
                    for off in range(1, 7):
                        if qi + off >= len(qlines):
                            break
                        nl = qlines[qi + off]
                        if not nl.strip() or _is_date_line(nl) or _MONTHDATE_LINE.match(_strip_md(nl)):
                            yrs = re.findall(r"(?:19|20)\d\d", nl)
                            if yrs:
                                end_year = int(yrs[-1])
                            # A standalone 'GPA: 3.5' line is date-classified;
                            # keep its literal label and value for this entry.
                            if gpa_ctx is None:
                                gpa_ctx = _gpa_literal(nl)
                            continue
                        ctx = _institute_context(nl)
                        if ctx:
                            joined_ctx.add(qi + off)
                        break
                    if ctx is None:
                        # Some templates put the institute BEFORE the degree
                        # ('University of X' / 'Expected... 2016' / 'B.A., Y').
                        for off in range(1, 4):
                            bi = qi - off
                            if bi < 0:
                                break
                            bl = qlines[bi]
                            if not bl.strip():
                                continue
                            # A preceding entry or the candidate's own name line
                            # means the scan has left this entry's context.
                            if (bi in joined_ctx or _education_entry(bl) or _school_entry(bl)
                                    or _experience_entry(bl)
                                    or (name and bl.strip().casefold() == str(name).casefold())):
                                break
                            if _is_date_line(bl) or re.search(r"(?:19|20)\d\d", bl) or _gpa_literal(bl):
                                continue
                            ctx = _institute_context(bl)
                            if ctx:
                                joined_ctx.add(bi)
                            break
                    if ctx:
                        edu["institute"] = ctx["institute"]
                        if "gpa" in ctx and "gpa" not in edu:
                            edu["gpa"] = ctx["gpa"]
                    if gpa_ctx and "gpa" not in edu:
                        edu["gpa"] = gpa_ctx
                    if end_year and not edu.get("year"):
                        edu["year"] = end_year
                education.append(edu)
        exp = _experience_entry(l) if l != lines[0] else None
        if exp is None and l != lines[0]:
            prev = qlines[qi - 1] if qi > 0 and qlines[qi - 1] != lines[0] else ""
            prev2 = qlines[qi - 2] if qi > 1 and qlines[qi - 2] != lines[0] else ""
            exp = _title_line_join(l, prev,
                                   qlines[qi + 1] if qi + 1 < len(qlines) else "",
                                   name=name, prev2=prev2)
        if exp and not _EDU_WORDS.search(l):
            experience.append(exp)
    return {"name": name, "nameEvidence": name_evidence, "skills": skills, "education": education, "experience": experience,
            "skillEvidence": evidence, "uncertainSkills": uncertain,
            "sectionReview": section_previews(text),
            "parseWarnings": ["Skill candidates from phrase matches and explicit lists, not verified proficiency or a complete resume assessment. "
                              "Review the detected skills; education and work-history extraction are limited."]}

_EDU_WORDS = re.compile(r"(?<![a-z])(b\.?tech|m\.?tech|bca|mca|b\.?sc|m\.?sc|bachelor|master|mba|pgdm|b\.?com|b\.?ed|b\.?e|b\.?des|m\.?des)(?![a-z])", re.I)
_DATEISH = re.compile(r"^(?:\(?(?:19|20)\d\d(?:\s*[-\u2013to]+\s*(?:(?:19|20)\d\d|present|ongoing))?\)?|cgpa.*|.*cgpa|gpa.*|\d+(?:\.\d+)?\s*(?:/\s*10)?%?)$", re.I)
_TITLES = (r"internship|intern|trainee|developer|analyst|engineer|executive|manager|assistant|associate|designer|consultant|"
           r"officer|teacher|coordinator|specialist|administrator|technician|accountant|recruiter|lead|"
           r"representative|scientist|architect|tutor|coach|volunteer")
_TITLE_RE = re.compile(r"\b(?:[A-Za-z]+\s){0,3}?(?:" + _TITLES + r")\b", re.I)
_TITLE_SUFFIX = r"(?:\s+(?:I{1,3}|IV|V|VI{0,3}))?"
_TITLE_FULL = re.compile(r"(?:[A-Za-z]+\s){0,3}?(?:" + _TITLES + r")" + _TITLE_SUFFIX + r"$", re.I)
_GERUND = (r"(?:build|building|built|manag(?:e|ed|ing)|wrote|writing|led|leading|work(?:ed|ing)?|"
           r"develop(?:ed|ing)?|design(?:ed|ing)?|creat(?:e|ed|ing)|deliver(?:ed|ing)?|"
           r"ship(?:ped|ping)?|launch(?:ed|ing)?|own(?:ed|ing)?|drove|driving|"
           r"support(?:ed|ing)?|maintain(?:ed|ing)?|implement(?:ed|ing)?)")
_ORG_SUFFIX = re.compile(
    r"\b(?:inc|llc|ltd|corp|co|pvt|private|limited|company|university|college|institute|"
    r"technologies|tech|systems|solutions|labs|studio|group|organization|organisation|"
    r"industries|enterprises|consulting|services|machines|implements|softlabs|board)\b\.?", re.I)

def _strip_md(line):
    """Remove markdown heading/emphasis markers for field detection; source text stays as written."""
    s2 = re.sub(r"^#{1,6}\s+", "", line.strip())
    return re.sub(r"[*_`]+", "", s2).strip()
_SUBJECT = re.compile(
    r"^(?:[A-Za-z&]+[\s,]+){0,3}(?:science|arts|applications|studies|engineering|technology|"
    r"mathematics|statistics|commerce|humanities|administration|education|law|medicine)s?$", re.I)


def _gpa_literal(part):
    """GPA/CGPA only when literally stated, label and scale kept exactly as
    written; never computed, converted or invented."""
    fwd = re.search(r"\b(cgpa|gpa)\b\s*[:=-]?\s*(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?)", part, re.I)
    rev = re.search(r"\b(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?)\s*(cgpa|gpa)\b", part, re.I)
    gm = (fwd.group(1), fwd.group(2)) if fwd else ((rev.group(2), rev.group(1)) if rev else None)
    if gm:
        return {"label": gm[0].upper(), "value": re.sub(r"\s+", "", gm[1])}
    return None


def _education_entry(part):
    """Degree, institute and year from one education line; institute only if literally present."""
    part = _strip_md(part).strip().lstrip("-•* ")
    m = _DEGREE.search(part)
    gpa = _gpa_literal(part)
    if not m:
        # Prose education: "studied <subject> at <institute>, graduating <year>".
        # The subject is kept as written; it is what the source literally states.
        if len(part) <= 160:
            sm = re.search(r"\bstudied\s+(.{2,60}?)\s+at\s+((?:[A-Z0-9][\w&.'-]*)(?:\s+(?:[A-Z0-9][\w&.'-]*|of|and))*?)(?=\s*[,.;]|\s+(?:graduating|in|from|during)\b|\s*$)", part, re.I)
            if sm and not re.search(r"\b(?:seeking|looking|aspir|plans? to|wants? to)\b", part, re.I):
                years = re.findall(r"(?:19|20)\d\d", part)
                # Subject of study as written, not an earned-credential claim.
                entry = {"degree": sm.group(1).strip(" ,."), "institute": sm.group(2).strip(" ,."),
                         "year": int(years[-1]) if years else None, "subjectOnly": True}
                if gpa:
                    entry["gpa"] = gpa
                return entry
        return None
    if len(part) > 160:
        return None
    # A degree token must start the line (or follow a bullet), so prose that merely
    # mentions "master" or "B.E." later in a sentence is not promoted to history.
    # Possession/completion lead-ins ("He has a B.Tech", "earned an M.Sc") count.
    if m.start() > 3:
        prefix = part[:m.start()].strip()
        inst_first = None
        if not (re.match(r"^(?:\W*)(?:completed|pursued|graduated|earned|received)\b", prefix, re.I)
                or re.fullmatch(r"(?:\w+\s+)?(?:has|have|holds?)\s+(?:a|an|the)", prefix, re.I)):
            # "State University, B.A. Communications": institute first, degree second.
            cand = prefix.strip().rstrip(",").strip()
            if (_ORG_SUFFIX.search(cand) and 1 <= len(cand.split()) <= 8
                    and not _DATEISH.match(cand) and "@" not in cand):
                inst_first = cand
            else:
                return None
    y = re.search(r"((?:19|20)\d\d)", part)
    year = None
    if y:
        years = re.findall(r"(?:19|20)\d\d", part)
        year = int(years[-1])
    # "Bachelor of Science in Computer Science" must not truncate to "Bachelor":
    # extend bachelor/master with their literal "of ... [in ...]" subject text.
    degree = m.group(1).replace("..", ".")
    if re.fullmatch(r"bachelor|master", degree, re.I):
        ext = re.match(r"\s+of\s+[A-Za-z][\w&.\' ]*?(?:\s+in\s+[A-Za-z][\w&.\' ]*?)?(?=\s*[,;|\u00b7]|\s+[-\u2013\u2014]\s|\s*$)", part[m.end():])
        if ext:
            degree += " " + ext.group(0).strip()
    inst, subject = "", None
    if m.start() > 3:
        pre = part[:m.start()].strip().rstrip(",").strip()
        if _ORG_SUFFIX.search(pre) and 1 <= len(pre.split()) <= 8 and not _DATEISH.match(pre) and "@" not in pre:
            inst = pre
            # "B.A. Communications": the subject follows the degree token.
            suffix = part[m.end():].strip(" ,.;·|")
            if suffix and len(suffix.split()) <= 5 and not _DATEISH.match(suffix) \
                    and not re.search(r"\b(?:cgpa|gpa)\b", suffix, re.I):
                subject = suffix
    segments = [x.strip() for x in re.split(r",|\s[-\u2013]\s|\u00b7", part)[1:]]
    for seg in segments:
        seg = seg.strip(". ")
        if not seg or len(seg) > 80 or _DATEISH.match(seg) \
                or _MONTHDATE_LINE.match(seg) or _DEGREE.fullmatch(seg):
            continue
        # Score text ("3.8 GPA", "CGPA 8.6/10 (till 7th semester)") is never an
        # institute; the labeled value already lives in entry["gpa"].
        if re.search(r"\b(?:cgpa|gpa)\b", seg, re.I):
            continue
        # A short field-of-study segment ("Computer Applications", "Business
        # Administration") is a subject, not an institute; keep it as written.
        if subject is None and _SUBJECT.fullmatch(seg):
            subject = seg
            continue
        if not inst:
            inst = seg
        break
    # Source casing is preserved as written (only the '..' artifact is normalized).
    entry = {"degree": degree, "institute": inst, "year": year}
    if subject:
        entry["subject"] = subject
    if gpa:
        entry["gpa"] = gpa
    return entry


def _org_context(line):
    """An adjacent line that plausibly names an employer, for title-only lines.

    Conservative by design: no dates, no titles, no bullets, no headings, no
    contact data, no ALL-CAPS name headers without an org suffix. Fail closed.
    """
    s2 = _strip_md(line)
    if not s2 or len(s2) > 120 or re.match(r"^[•*\-–]\s", line.strip()):
        return None
    if _DATEISH.match(s2) or _EDU_WORDS.search(s2) or _TITLE_RE.search(s2):
        return None
    if _SECTION_HEADING.fullmatch(s2) or s2.endswith(":"):
        return None
    if "@" in s2 or re.search(r"\d{3,}", s2) or re.match(_GERUND + r"\b", s2, re.I):
        return None
    # 'YMCA, Pomona, CA' is an org plus trailing location, not a name header.
    has_location = bool(re.search(r",\s*[A-Za-z. ]+,\s*[A-Z]{2}\s*$", _strip_md(line)))
    s2 = re.split(r"[|·]", s2)[0].split(",")[0].strip()
    if not (1 <= len(s2.split()) <= 8 and re.search(r"[A-Za-z]", s2)):
        return None
    # An ALL-CAPS line with no org suffix is more likely a name header than an employer.
    if s2.upper() == s2 and not _ORG_SUFFIX.search(s2) and not has_location:
        return None
    # A lone word without an org suffix ("Swim") is not an employer context.
    if len(s2.split()) == 1 and not _ORG_SUFFIX.search(s2) and not has_location:
        return None
    return s2


_MONTHDATE_LINE = re.compile(
    r"^(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
    r"spring|summer|fall|autumn|winter)\b.*(?:19|20)\d\d", re.I)
_MONTH_WORD = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
               r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
               r"spring|summer|fall|autumn|winter)")
_MONTHYEAR = _MONTH_WORD + r"\.?(?:\s+(?:19|20)\d\d)"
_TRAILING_DATES = re.compile(
    r"\s+" + _MONTHYEAR + r"(?:\s*[-\u2013\u2014]\s*(?:" + _MONTHYEAR + r"|present|ongoing))?\s*$", re.I)


def _title_line_join(line, prev, nxt, name="", prev2=""):
    """A line that is exactly a job title gets its org from an adjacent org line
    (markdown and PDF-flattened templates put org and dates on their own lines).
    Some templates order org / dates / title, so when the previous line is only
    a date range, the line before it may be the employer."""
    base = _strip_md(line)
    if not _TITLE_FULL.match(base):
        # Flattened PDF rows keep the dates on the title line ('Software
        # Engineer May 2023 - Present'). Strip a trailing date range; the
        # remainder must be exactly a title, otherwise fail closed.
        stripped = _TRAILING_DATES.sub("", base)
        if stripped != base and _TITLE_FULL.match(stripped):
            base = stripped
        else:
            return None
    org = _org_context(nxt) or _org_context(prev)
    if not org and prev2:
        p = _strip_md(prev)
        if _is_date_line(prev) or _MONTHDATE_LINE.match(p):
            org = _org_context(prev2)
    if org and name and org.casefold() == name.casefold():
        org = None
    if org:
        return {"title": base, "org": org, "months": None}
    return None


def _experience_entry(line):
    """Title and employer from 'Org, Title, dates', 'Title, Org, dates', 'Title · Org' or 'Title at Org'."""
    line = _strip_md(line)
    if re.match(r"^[•*\-–]\s", line) or len(line) > 220:
        return None
    head = re.split(r"[:：]", line, 1)[0]
    months = re.search(r"\((\d+)\s*months?\)", line)
    mval = int(months.group(1)) if months else None
    head = re.sub(r"\((?:[^()]*)\)", lambda m: " " if re.search(r"(?:19|20)\d\d|month|present", m.group(0), re.I) else m.group(0), head)
    dot_sep = "\u00b7" in head
    parts = [x.strip() for x in re.split(r",|\s[-\u2013\u2014]\s|\u00b7|\|", head)]
    parts = [x for x in parts if x]
    # structured: some part that is essentially just a job title
    for i, part in enumerate(parts):
        base = re.sub(r"\s*\(.*?\)\s*", " ", part).strip()
        if _TITLE_FULL.match(base):
            others = [x for j, x in enumerate(parts) if j != i]
            dateish = [x for x in others if _DATEISH.match(x)]
            rest = [x for x in others if not _DATEISH.match(x)]
            # A "Title · skill, skill, skill" headline is not a job: with a dot
            # separator, several short skill-like segments and no date, fail closed.
            if dot_sep and not dateish and not any(_ORG_SUFFIX.search(x) for x in rest):
                return None
            for cand in (others[i-1:i] if i >= 1 and len(others) >= i else []) + others:
                cand = re.sub(r"\s*\(.*?\)\s*$", "", cand).strip()
                if cand and not _DATEISH.match(cand) and not _TITLE_RE.fullmatch(cand) and not re.match(_GERUND + r"\b", cand, re.I):
                    title = base if _TITLE_FULL.match(base) else _TITLE_RE.search(part).group(0).strip()
                    return {"title": title, "org": cand, "months": mval}
            return None
    # prose: "<title> at <Org>"
    m = re.search(r"\b(" + _TITLES + r")\s+(?:at|with|for)\s+((?:[A-Z0-9][\w&.'-]*)(?:\s+(?:[A-Z0-9][\w&.'-]*|&|of|and))*?)(?=\s+(?:in|from|during|since|working|for|where|and)\b|\s*[,.(;]|\s+(?:19|20)\d\d|$)", line, re.I)
    if m and not re.search(r"\b(?:seeking|looking|aspir)", line, re.I):
        org = m.group(2).strip(" .")
        if org and not _DATEISH.match(org):
            return {"title": m.group(1), "org": org, "months": mval}
    # prose: "worked/interned at <Org> as a <Title>"
    m = re.search(r"\b(?:worked|interned|served)\s+(?:at|with|for)\s+"
                  r"((?:[A-Z0-9][\w&.'-]*)(?:\s+(?:[A-Z0-9][\w&.'-]*|&|of|and))*?)"
                  r"\s+as\s+(?:a|an|the)\s+((?:[A-Za-z]+\s){0,3}?(?:" + _TITLES + r"))\b", line, re.I)
    if m and not re.search(r"\b(?:seeking|looking|aspir)", line, re.I):
        org = m.group(1).strip(" .")
        if org and not _DATEISH.match(org):
            return {"title": m.group(2).strip(), "org": org, "months": mval}
    return None


_SCHOOL_RE = re.compile(
    r"^((?:HSC|SSC|CBSE|ICSE)(?:\s*\(\s*Class\s*[XIVxiv0-9]{1,3}\s*\))?|"
    r"Class\s*(?:XII|XI|X|IX|12|11|10|9)(?:\s*\([A-Za-z]+\))?)(?=\s*[,·|)]|$)", re.I)
_PERCENT = re.compile(r"^(\d+(?:\.\d+)?\s*%)$")
_GENERIC_SCHOOL = re.compile(r"^(?:secondary|higher secondary|senior secondary|high)\s+school$", re.I)


def _school_entry(part):
    """School-level rows (HSC/SSC/Class X/XII): board as institute, percentage kept
    verbatim as a labeled score. Source casing preserved; no scale is ever invented."""
    m = _SCHOOL_RE.match(part.strip())
    if not m:
        return None
    rest = part[m.end():]
    segments = [x.strip() for x in re.split(r",|\s[-\u2013\u2014]\s|\u00b7|\|", rest)]
    segments = [x.strip(". ") for x in segments if x.strip(". ")]
    inst, subject, score = "", None, None
    y = re.search(r"((?:19|20)\d\d)", part)
    for seg in segments:
        pm = _PERCENT.match(seg)
        if pm:
            score = {"label": "Percentage", "value": pm.group(1).strip()}
            continue
        if _DATEISH.match(seg):
            continue
        if _GENERIC_SCHOOL.match(seg):
            subject = subject or seg
            continue
        if re.search(r"\b(?:board|university|school|vidyalaya|college)\b", seg, re.I) and not inst:
            inst = seg
            continue
        if subject is None and (_SUBJECT.fullmatch(seg) or re.search(r"\b(?:science|commerce|arts|humanities)\b", seg, re.I)):
            subject = seg
            continue
        if not inst:
            inst = seg
    entry = {"degree": m.group(1).strip(), "institute": inst,
             "year": int(y.group(1)) if y else None}
    if subject:
        entry["subject"] = subject
    if score:
        entry["gpa"] = score
    return entry


def _is_date_line(line):
    """A line that is only a date range; an institute line ending in a score is not one."""
    s2 = _strip_md(line)
    return bool(_DATEISH.match(s2)) and not re.search(r"[,·|]", s2)


def _institute_context(line):
    """An adjacent line naming an institute, for degree lines whose institute sits on
    the next line. Conservative like _org_context: fail closed on anything else."""
    s2 = _strip_md(line)
    if not s2 or len(s2) > 140 or re.match(r"^[•*\-–]\s", line.strip()):
        return None
    if _DEGREE.search(s2) or _SCHOOL_RE.match(s2) or _TITLE_RE.search(s2):
        return None
    if "@" in s2 or _SECTION_HEADING.fullmatch(s2) or s2.endswith(":"):
        return None
    segs = [x.strip() for x in re.split(r"\u00b7|\|", s2) if x.strip()]
    inst = re.sub(r",?\s*(?:\d+(?:\.\d+)?\s*(?:/\s*\d+)?\s*(?:cgpa|gpa)|(?:cgpa|gpa)\s*[:=-]?\s*\d+(?:\.\d+)?(?:\s*/\s*\d+)?)$", "", segs[0], flags=re.I).strip(" .,")
    if _DATEISH.match(inst):
        return None
    fwd = re.search(r"\b(cgpa|gpa)\b\s*[:=-]?\s*(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?)", s2, re.I)
    rev = re.search(r"\b(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?)\s*(cgpa|gpa)\b", s2, re.I)
    gm = (fwd.group(1), fwd.group(2)) if fwd else ((rev.group(2), rev.group(1)) if rev else None)
    if not (2 <= len(inst.split()) <= 10 and re.search(r"[A-Za-z]", inst)):
        return None
    if inst.upper() == inst and not _ORG_SUFFIX.search(inst):
        return None
    out = {"institute": inst}
    if gm:
        out["gpa"] = {"label": gm[0].upper(), "value": re.sub(r"\s+", "", gm[1])}
    else:
        pm = re.search(r"\b(\d+(?:\.\d+)?\s*%)", s2)
        if pm:
            out["gpa"] = {"label": "Percentage", "value": pm.group(1)}
    return out


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
        line = _strip_md(line)
        label = line.casefold().rstrip(':：').strip()
        if label in titles:
            continue
        if "@" in line or re.match(r"^(?:e-?mail|phone|mobile|tel|contact|https?://|www\.)\b", line, re.I) or re.fullmatch(r"[+()\d\s.-]{7,}", line):
            continue
        if re.fullmatch(r"\d{1,3}", line):
            continue  # page-number furniture from PDF extraction, never a name
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
    # "no backlogs" is academic standing, not a denial of the qualification.
    probe = re.sub(r",?\s*no backlogs\b", "", probe, flags=re.I)
    line = re.sub(r",?\s*no backlogs\b", "", line, flags=re.I)
    # "Example State University" is a proper org name, not sample-text marking;
    # same exemption shape as the degree-first "Example University" case.
    if _ORG_SUFFIX.search(probe):
        probe = re.sub(r"\bexample\b", " ", probe, flags=re.I)
        line = re.sub(r"\bexample\b", " ", line, flags=re.I)
    m = _DEGREE.match(probe)
    if m and re.match(r"^(?:\W*|\s+)", probe[m.end():]):
        line = re.sub(r"\bexample\b", " ", line, flags=re.I)
    return bool(_QUALIFICATION_UNCERTAIN.search(line))


def qualification_lines(text):
    """Conservative literal lines eligible for degree/work extraction, not proof."""
    excluded_section = False
    # Sections whose items name things (projects, references) stay excluded past
    # blank lines: "Team lead, Clinic Billing System" is a project role, not a job.
    ENTITY_LIST_SECTIONS = {"projects", "personal projects", "academic projects",
                            "references", "referees", "interests", "hobbies", "interests/hobbies"}
    text = _without_template_tips(text)
    for l in text.splitlines():
        l = l.strip()
        if not l:
            # A blank line ends an excluded prose/list section ("Skills:" then a
            # blank then an experience line must not hide that line); blanks are
            # never yielded.
            if excluded_section not in ENTITY_LIST_SECTIONS:
                excluded_section = False
            continue
        label = _strip_md(l).casefold().rstrip(':：').strip()
        if label.startswith("user-provided skill statements"):
            excluded_section = "user-provided skill statements"
            continue
        # Explicit non-history sections can contain degree words and job titles
        # without describing the candidate's qualifications or employment.
        section_label = re.split(r"[:：]", label, maxsplit=1)[0].strip()
        if section_label in {"career objective", "objective", "career goals", "learning goals", "job requirements", "required qualifications", "example", "example experience", "instructions", "tips",
                             "skills", "key skills", "technical skills", "competencies", "core competencies", "compétences", "habilidades", "fähigkeiten", "कौशल", "技能",
                             "projects", "personal projects", "academic projects", "references", "referees", "interests", "hobbies", "interests/hobbies"}:
            excluded_section = section_label
            continue
        if label in {"education", "qualifications", "academic qualifications", "academic details", "education and qualifications", "internship", "internships", "work history", "professional background", "academic background", "experience", "work experience", "employment", "employment history", "professional experience", "volunteer experience", "volunteer work", "formation", "educación", "ausbildung", "शिक्षा", "教育", "expérience", "experiencia", "berufserfahrung", "अनुभव", "工作经历"}:
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
    # pypdf emits lone '\r' line endings inside tabular layouts. The extracted
    # text is stored as the resume source, and the review editor's textarea
    # normalizes line endings on read - so CR bytes here would make the saved
    # version permanently 'dirty' and block approve/export. Store LF only.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Tabular templates extract as one word per line ('word\t' / ' \xa0word').
    # Reconstruct the logical lines for storage as well: same words, readable
    # source in the draft editor and exports. parse_resume applies the same
    # join itself, so parse results are unchanged (user-approved, 2026-11-11).
    text = _join_tab_split_lines(text)
    if len(text.strip()) < 20:
        raise ParseError("No selectable text found in that PDF (a scanned image will not work).")
    return text
