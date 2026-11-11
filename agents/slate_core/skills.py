"""Parser vocabulary, independent of the demo job catalog.

Conservative literal phrases and spelling variants, not a semantic assessment.
Adding a skill here does not create a job, a learning plan or a verified claim.
"""
import re
import unicodedata

SKILL_ALIASES = {
    "python": (), "sql": (), "excel": ("microsoft excel",),
    "statistics": (), "fastapi": (), "postgresql": ("postgres",),
    "git": (), "javascript": (), "react": ("react.js", "reactjs"),
    "typescript": (), "css": (), "pytorch": (), "tableau": (),
    "java": (), "c++": (), "c#": (), "docker": (), "aws": ("amazon web services",),
    "node.js": ("nodejs",),
    "asp.net core": (), "entity framework": ("entity framework core", "ef core"),
    "ansys": (), "gd&t": (), "fea": ("finite element analysis",), "dfmea": (),
    "figma": (), "machine learning": (), "power bi": ("powerbi",),
    "autocad": (), "solidworks": (), "matlab": (), "tally": ("tally erp", "tallyprime"),
    "communication": ("communications", "communication skills"),
    "customer service": ("customer support", "served customers"),
    "cash handling": ("handled cash", "cash register"),
    "numeracy": ("numeracy skills",),
    "teamwork": ("team work", "work as part of a team", "working as part of a team"),
    "organisation": ("organization", "organisational skills", "organizational skills"),
    "problem solving": ("solve problems", "solving problems"),
    "responsibility": ("take responsibility",),
    "coaching": ("assistant coach",),
    "leadership": (),
}


def normalized(text):
    text = unicodedata.normalize("NFKC", text or "").casefold()
    text = re.sub(r"[\u2010-\u2015]", "-", text)
    # PDFs can line-wrap a multi-word skill or use a nonbreaking space/hyphen.
    return re.sub(r"\s+", " ", text)


def skill_evidence(text):
    """Return canonical skills and one literal matched phrase per skill.

    Never equate broad subjects with tools (maths != statistics, business != SQL).
    Evidence is a phrase match, not proof of proficiency or positive assertion.
    """
    low = normalized(text)
    found = []
    for skill, aliases in sorted(SKILL_ALIASES.items()):
        for phrase in (skill,) + aliases:
            pattern = r"(?<![\w+#])" + re.escape(phrase).replace(r"\ ", r"[\s-]+") + r"(?![\w+#])"
            match = re.search(pattern, low)
            if match:
                found.append({"skill": skill, "matchedText": match.group(0), "source": "known_phrase"})
                break
    return found


# These are explicit section labels, not a promise of language understanding.
_SKILL_HEADING = re.compile(
    r"^(?:key skills|technical skills|core skills|professional skills|skills|"
    r"competencies|compétences|habilidades|fähigkeiten|技能|कौशल)\s*[:：]?\s*(.*)$", re.I)
_SECTION_HEADING = re.compile(
    r"^(?:education|experience|work experience|employment|projects|qualifications|"
    r"certifications|interests(?:/hobbies)?|referees|references|availability|"
    r"career objective|summary|professional summary|academic qualifications|academic details|internship|internships|work history|professional experience|professional background|volunteer experience|volunteer work|leadership roles|formation|expérience|educación|"
    r"positions? of responsibility|achievements?|awards?|honou?rs(?: ?/ ?awards)?|languages?|"
    r"(?:professional )?memberships?|hobbies|extracurricular(?: activities)?|declaration|"
    r"experiencia|ausbildung|berufserfahrung|教育|工作经历|शिक्षा|अनुभव)\s*[:：]?\s*$", re.I)


def _mdless(line):
    """Strip markdown heading/emphasis markers for heading detection only;
    callers keep the original line for content."""
    s2 = re.sub(r"^#{1,6}\s+", "", line.strip())
    return re.sub(r"[*_`]+", "", s2).strip()


def _skill_heading_match(line):
    """A skills heading, or None for prose fragments like 'skills.'/'skills,'.

    PDF text can wrap a sentence so its last word ('skills.') sits alone on a
    line. Punctuation-only trailing content is a fragment, never a heading;
    real inline content ('Skills: Python, Java') always contains a word.
    """
    m = _SKILL_HEADING.fullmatch(line)
    if m and m.group(1) and not re.search(r"[\w]", m.group(1)):
        return None
    return m


def explicit_skill_evidence(text):
    """Keep concise, explicitly listed skill phrases even outside the vocabulary.

    No inference from prose/job titles. A long bullet is not turned into a skill.
    Supported input: a recognized skills heading followed by short list items,
    or an inline list after that heading. Unknown section formats stay unsupported.
    Values remain candidate skill mentions for human review, not verified facts.
    """
    out, seen, active, started, blanks = [], set(), False, False, 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            # Markdown puts a single blank line between a heading and its list;
            # tolerate one, but a second blank (or any blank once items have
            # started) ends the section.
            blanks += 1
            if started or blanks > 1:
                active = False
            continue
        blanks = 0
        line = _mdless(line)
        heading = _skill_heading_match(line)
        if heading:
            active = True
            started = False
            content = heading.group(1)
        elif _SECTION_HEADING.fullmatch(line):
            active = False
            continue
        elif active:
            # Wrapped narrative continuation lines are not standalone list items.
            if not re.match(r"^[•*\-–]\s+", line) and not re.search(r"[,;|•]", line):
                # A colon-terminated line is a sub-label or unknown heading
                # ('Computer:'), not prose: the section ends here.
                if _SECTION_HEADING.fullmatch(line) or line.endswith((":", "：")): active = False
                continue
            content = re.sub(r"^[•*\-–]\s*", "", line)
            # An unknown heading ends the section rather than consuming its text.
            if content.endswith((":", "：")):
                active = False
                continue
            # A short label prefix ('Technical: SolidWorks, ...') is not an item.
            label = re.match(r"^([A-Za-z][\w ]{0,28})[:：]\s+(.+[,;|•].+)$", content)
            if label:
                content = label.group(2)
            started = True
        else:
            continue
        for part in re.split(r"[,;|•]", content):
            phrase = part.strip().strip(".")
            # A comma inside parentheses splits an item; drop the orphaned paren.
            if phrase.endswith(")") and "(" not in phrase:
                phrase = phrase[:-1].strip()
            if not phrase or len(phrase) > 70 or len(phrase.split()) > 5:
                continue
            # Reject sentence-like claims, dates/contact values, and labels.
            if any(c in phrase for c in "@:/<>\\") or re.search(r"\b(?:I|my|when|through|demonstrated|seeking|proven)\b", phrase, re.I):
                continue
            if not any(c.isalpha() for c in phrase):
                continue
            matches = skill_evidence(phrase)
            # Known short aliases canonicalize only when they cover the whole item.
            exact = next((e for e in matches if e["matchedText"] == normalized(phrase)), None)
            if matches and not exact:
                continue  # avoid duplicating prose/qualifiers as a second skill
            # A lone past-tense word is a wrapped bullet opener ('Communicated
            # regularly with...' split by PDF artifacts), not a skill.
            if exact is None and len(phrase.split()) == 1 and re.search(r"ed$", phrase, re.I):
                continue
            skill = exact["skill"] if exact else normalized(phrase)
            if skill not in seen:
                out.append({"skill": skill, "matchedText": phrase, "source": "explicit_skill_list"})
                seen.add(skill)
            if len(out) >= 64:
                return out
    return out


_UNCERTAIN = re.compile(
    r"\b(?:no|not|never|without|lack|lacking|unfamiliar|want(?:s)? to learn|"
    r"wish(?:es)? to learn|plan(?:s|ning)? to learn|learning|learn|seeking|"
    r"aspir(?:e|es|ing)|interested in|hop(?:e|es|ing) to|instruction)\b", re.I)
# Degree tokens; shared with resume.py, which imports it from here.
_DEGREE = re.compile(
    r"(?<![a-z])(b\.?\s?tech|m\.?\s?tech|b\.?e\.?|m\.?e\.?|b\.?s\.?|m\.?s\.?|bca|mca|b\.?sc\.?|m\.?sc\.?|b\.?com\.?|m\.?com\.?|"
    r"b\.?a\.?|m\.?a\.?|b\.?ed\.?|m\.?ed\.?|b\.?des\.?|m\.?des\.?|bba|mba|pgdm|b\.?arch|ph\.?d|diploma|bachelor|master)(?![a-z])", re.I)
_STUDY_LINE = re.compile(
    r"\b(?:studied|studying|study of|read for|majored in|speciali[sz]ed in|pursued|pursuing)\b", re.I)
_INSTRUCTION_HEADING = re.compile(
    r"^(?:required skills|desired skills|skills to learn|learning goals|"
    r"example skills|job requirements|instructions|tips)\s*[:：]?\s*(.*)$", re.I)


def _review_text(text):
    """Tag known instructional sections; preserve line boundaries for context."""
    instruction, lines = False, []
    for line in text.splitlines():
        clean = line.strip()
        mdless = _mdless(clean)
        if _INSTRUCTION_HEADING.fullmatch(mdless):
            instruction = True
        elif _skill_heading_match(mdless) or _SECTION_HEADING.fullmatch(mdless):
            instruction = False
        lines.append(("instruction: " if instruction else "") + clean)
    low = unicodedata.normalize("NFKC", "\n".join(lines)).casefold()
    low = re.sub(r"[\u2010-\u2015]", "-", low)
    return re.sub(r"[^\S\n]+", " ", low)


# "Machine Learning" is a field name, not an aspiration to learn something.
_LEARNING_NOUN = re.compile(
    r"\b(?:machine|deep|reinforcement|transfer|supervised|unsupervised|federated|statistical|e|blended|"
    r"organi[sz]ational)[\s-]+learning\b|\blearning\s+(?:management|analytics|design|and development|experience designer)\b", re.I)


def _is_uncertain(context):
    return bool(_UNCERTAIN.search(_LEARNING_NOUN.sub(" ", context)))


def _context(low, match):
    start = max((low.rfind(c, 0, match.start()) for c in "\n.!?;"), default=-1) + 1
    ends = [low.find(c, match.end()) for c in "\n.!?;"]
    end = min((i for i in ends if i >= 0), default=len(low))
    return low[start:end]


def _line_of(low, match):
    """The whole line containing a match; sentence splitting cuts 'B.Des' at its dot."""
    start = low.rfind("\n", 0, match.start()) + 1
    end = low.find("\n", match.end())
    return low[start: end if end >= 0 else len(low)]


def plain_list_review_candidates(text):
    """Expose an initial unbulleted skills block for review, never count it.

    PDF extraction can drop bullets, but short lines can also be wrapped prose
    or an unrecognized section. At least two concise initial lines are needed;
    continuation lines after a bullet/inline list are deliberately excluded.
    """
    pending, out = [], []
    def flush():
        if len(pending) >= 2:
            for phrase in pending:
                if not skill_evidence(phrase):
                    out.append({"skill": normalized(phrase), "matchedText": phrase,
                                "source": "ambiguous_plain_skills_block",
                                "reason": "Unbulleted skills-section text may be a list or wrapped prose; not counted without review."})
        pending.clear()
    active, blanks = False, 0
    for raw in text.splitlines():
        line = _mdless(raw.strip())
        heading = _skill_heading_match(line)
        if heading:
            flush(); active = not bool(heading.group(1)); continue
        if not active:
            continue
        if not line:
            # A single blank after the heading is markdown spacing; a second
            # consecutive blank, or a blank once items are pending, ends it.
            blanks += 1
            if pending or blanks > 1:
                flush(); active = False
            continue
        blanks = 0
        if _SECTION_HEADING.fullmatch(line) or line.endswith((":", "：")):
            flush(); active = False; continue
        if (re.match(r"^[•*\-–]\s+", line) or re.search(r"[,;|•]", line)
                or len(line) > 70 or len(line.split()) > 5
                or any(c in line for c in "@:/<>\\.?!")
                or re.search(r"\b(?:I|my|when|through|demonstrated|seeking|proven|and|the|with|from|since|of)\b", line, re.I)):
            flush(); active = False; continue
        if any(c.isalpha() for c in line):
            pending.append(line)
        if len(pending) >= 64:
            flush(); active = False
    flush()
    return out[:64]


def resume_skill_evidence(text):
    """Separate plain mentions from negative/aspirational/instructional contexts.

    Conservative context flags are not a semantic guarantee. A positive mention
    elsewhere can support a candidate even if a separate mention is uncertain.
    Draft claim checking deliberately uses unfiltered skill_evidence instead.
    """
    low, accepted, flagged = _review_text(text), {}, {}
    for skill, aliases in sorted(SKILL_ALIASES.items()):
        for phrase in (skill,) + aliases:
            pattern = r"(?<![\w+#])" + re.escape(phrase).replace(r"\ ", r"[\s-]+") + r"(?![\w+#])"
            for match in re.finditer(pattern, low):
                e = {"skill": skill, "matchedText": match.group(0), "source": "known_phrase"}
                context = _context(low, match)
                line = _line_of(low, match).strip()
                if _is_uncertain(context):
                    flagged.setdefault(skill, dict(e, reason="Negative, aspirational or instructional context; not counted without review."))
                elif _SECTION_HEADING.fullmatch(_mdless(line)):
                    # "Positions of Responsibility" is a section heading; its words
                    # are not evidence of a responsibility skill.
                    flagged.setdefault(skill, dict(e, reason="Appears in a section heading; a heading word is not a skill mention; not counted without review."))
                elif _DEGREE.search(line) or _STUDY_LINE.search(line):
                    # A degree or study line names subjects of study; e.g. "B.Des
                    # Communication Design" or "She studied Communication Design at
                    # NID" is not evidence of a communication skill. Flag for review
                    # instead of accepting. A mention elsewhere can still be accepted.
                    flagged.setdefault(skill, dict(e, reason="Appears on a degree, education or study line; may name a subject of study, not a skill; not counted without review."))
                else:
                    accepted.setdefault(skill, e)
    for e in explicit_skill_evidence(text):
        if e["skill"] in accepted:
            continue
        phrase = re.escape(normalized(e["matchedText"])).replace(r"\ ", r"\s+")
        matches = list(re.finditer(phrase, low))
        if matches and any(not _is_uncertain(_context(low, m)) for m in matches):
            accepted[e["skill"]] = e
        else:
            flagged.setdefault(e["skill"], dict(e, reason="Negative, aspirational or instructional context; not counted without review."))
    for e in plain_list_review_candidates(text):
        flagged.setdefault(e["skill"], e)
    return sorted(accepted.values(), key=lambda e: e["skill"]), [flagged[k] for k in sorted(flagged) if k not in accepted]
