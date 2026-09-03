"""Free, LLM-less resume parser. Used when there is no ANTHROPIC_API_KEY or the
API rejects the call (no credits). Strictly extractive: regexes + the vertical
skill taxonomy. Anything it can't find is None/empty - it never guesses.
Lower quality than the Claude parser; profiles record parser_model so the UI
can say so."""
import re

from app.profile.parser import Education, ParsedProfile
from app.vertical.loader import load_vertical

HEURISTIC_MODEL = "heuristic-1.0"

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w-]+/?", re.I)
GITHUB_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w-]+/?", re.I)
URL_RE = re.compile(r"https?://[^\s|,]+", re.I)
YEAR_RE = re.compile(r"\b(20\d{2}|19\d{2})\b")
MONTH_YEAR_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(20\d{2})\b", re.I
)
LOCATION_RE = re.compile(r"\b([A-Z][a-zA-Z.]+(?: [A-Z][a-zA-Z.]+)*),\s*([A-Z]{2})\b")

DEGREE_RE = re.compile(
    r"\b(Ph\.?D\.?|Doctor of Philosophy|M\.?S\.?|M\.?Sc\.?|Master(?:'s| of)?(?: Science| Engineering| Arts)?|"
    r"MEng|M\.?Tech\.?|MBA|B\.?S\.?|B\.?Sc\.?|Bachelor(?:'s| of)?(?: Science| Engineering| Arts| Technology)?|"
    r"B\.?Tech\.?|BEng|B\.?E\.?)\b",
    re.I,
)
SCHOOL_RE = re.compile(r"\b([A-Z][\w&.'-]*(?:\s+(?:of|the|and|[A-Z][\w&.'-]*))*\s+(?:University|College|Institute|School)(?:\s+of\s+[A-Z][\w&.'-]*(?:\s+[A-Z][\w&.'-]*)*)?|"
                       r"University\s+of\s+[A-Z][\w&.'-]*(?:\s+[A-Z][\w&.'-]*)*)")
TITLE_WORDS = re.compile(
    r"\b(Engineer|Scientist|Developer|Intern|Analyst|Researcher|Research Assistant|Manager|Architect|"
    r"Consultant|Specialist|Fellow|Associate|Teaching Assistant)\b",
    re.I,
)
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _clean(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip(" \t•·|-–—")


def _grad_date(line: str) -> str | None:
    m = MONTH_YEAR_RE.search(line)
    if m:
        return f"{m.group(2)}-{MONTHS[m.group(1)[:3].lower()]:02d}"
    years = YEAR_RE.findall(line)
    return years[-1] if years else None


def _parse_education(lines: list[str]) -> list[Education]:
    out: list[Education] = []
    for i, line in enumerate(lines):
        dm = DEGREE_RE.search(line)
        if not dm:
            continue
        window = " ".join(lines[i:i + 2])  # school/date may sit on the next line
        degree = dm.group(0)
        field = None
        fm = re.search(r"(?:in|of)\s+([A-Z][\w &/-]{2,60}?)(?:,|\.|\s+(?:at|from|-|–|\|)|$)", line[dm.end():])
        if fm:
            field = fm.group(1).strip()
        sm = SCHOOL_RE.search(window)
        school = sm.group(0).strip() if sm else None
        grad = _grad_date(window)
        if field and len(field.split()) > 5:
            field = None  # prose after "in ...", not a field of study
        if not school and not grad:
            continue  # a bare degree mention (e.g. inside a summary sentence), not an entry
        entry = Education(degree=degree, field=field, school=school, graduation_date=grad)
        if any(e.degree.lower() == entry.degree.lower() and e.school == entry.school for e in out):
            continue
        out.append(entry)
    return out


def _parse_titles(lines: list[str]) -> list[str]:
    titles: list[str] = []
    for line in lines:
        if DEGREE_RE.search(line) or "@" in line or line.startswith(("-", "•")):
            continue
        title = re.split(r"\s+[-–—|@,]\s+|\s+at\s+|\s*\(", line, maxsplit=1)[0].strip()
        if TITLE_WORDS.search(title) and 1 <= len(title.split()) <= 6 and title not in titles:
            titles.append(title)
    return titles[:10]


def _parse_skills(text: str) -> list[str]:
    """Return skill strings as they appear in the text, matched via the taxonomy."""
    found: list[str] = []
    text = URL_RE.sub(" ", EMAIL_RE.sub(" ", text))
    text = re.sub(r"\b(?:www\.)?(?:linkedin|github)\.com/\S+", " ", text, flags=re.I)
    lower = text.lower()
    for skill in load_vertical().skills:
        for name in (skill.canonical, *skill.aliases):
            pat = r"(?<![\w+#])" + re.escape(name.lower()) + r"(?![\w+#])"
            m = re.search(pat, lower)
            if m:
                original = text[m.start():m.end()]
                if original not in found:
                    found.append(original)
                break
    return found


SECTION_HEADERS = {
    "summary", "professional summary", "objective", "profile", "about", "about me", "education",
    "experience", "work experience", "professional experience", "skills", "technical skills",
    "projects", "publications", "certifications", "awards", "contact", "achievements", "interests",
}


def _unspace(line: str) -> str:
    """'S U M M A R Y' -> 'SUMMARY' (PDF text extraction artifact)."""
    words = line.split()
    if len(words) >= 3 and sum(len(w) == 1 for w in words) >= len(words) * 0.6:
        return "".join(words)
    return line


def _is_section_header(line: str) -> bool:
    return _unspace(line).strip(": ").lower() in SECTION_HEADERS


def _parse_name(lines: list[str]) -> str | None:
    for line in lines[:6]:
        if "@" in line or any(ch.isdigit() for ch in line) or URL_RE.search(line):
            continue
        if _is_section_header(line):
            continue
        words = line.split()
        if 2 <= len(words) <= 4 and all(w[:1].isupper() for w in words if w.isalpha()):
            return line
    return None


def _parse_locations(text: str) -> list[str]:
    seen: list[str] = []
    for city, state in LOCATION_RE.findall(text):
        loc = f"{city}, {state}"
        if loc not in seen:
            seen.append(loc)
    return seen[:5]


def heuristic_parse(text: str) -> ParsedProfile:
    lines = [_clean(l) for l in text.splitlines()]
    lines = [l for l in lines if l]
    email = EMAIL_RE.search(text)
    phone = PHONE_RE.search(text)
    linkedin = LINKEDIN_RE.search(text)
    github = GITHUB_RE.search(text)
    return ParsedProfile(
        name=_parse_name(lines),
        email=email.group(0) if email else None,
        phone=phone.group(0).strip() if phone else None,
        linkedin_url=linkedin.group(0) if linkedin else None,
        github_url=github.group(0) if github else None,
        education=_parse_education(lines),
        skills=_parse_skills(text),
        titles_held=_parse_titles(lines),
        locations=_parse_locations(text),
        # Not derivable without judgement -> left null rather than guessed:
        years_of_experience=None,
        work_authorization=None,
        needs_sponsorship=None,
        inferred_target_titles=[],
        seniority_band=None,
        remote_preference=None,
        summary=None,
    )
