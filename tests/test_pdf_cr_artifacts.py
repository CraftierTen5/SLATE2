"""Audit F12 pins (10-sample internet audit, 2026-11-11): pypdf (the
production upload path) emits the same tabular word fragments as pdftotext
but separated by '\\t\\r \\xa0' - a CR where pdftotext puts an LF - so the
tab-split repair never fired and names, degrees and experience shattered on
real PDF uploads. Separately, a degree line carrying a trailing date range
('... - 3.8 GPA Sep 2019 - May 2023') split on ' - ' and adopted the month
-year fragment as the institute. Synthetic fixtures modeled on the public
samples; no personal data."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

from slate_core.resume import parse_resume, _join_tab_split_lines

# pypdf's rendering of the same tabular layout as the F9 TABBED fixture:
# fragments end with '\t\r' and the next fragment starts with ' \xa0'.
CR_TABBED = ("Lee Example\t\r \xa0\nlee@example.com\t\r \xa0\n"
             "EDUCATION\t\r \xa0\nBachelor\t\r \xa0of\t\r \xa0Arts,\t\r \xa0Business\t\r \xa0Administration\t\r \xa0\n"
             "GPA:\t\r \xa03.5\t\r \xa0\n\t\r \xa0\n"
             "SKILLS\t\r \xa0\nComputer:\t\r \xa0Microsoft\t\r \xa0Word,\t\r \xa0Excel\t")


def test_cr_tab_split_words_rejoin_like_lf_ones():
    j = _join_tab_split_lines(CR_TABBED)
    assert "Bachelor of Arts, Business Administration" in j.splitlines()
    assert "Computer: Microsoft Word, Excel" in j.splitlines()


def test_cr_fixture_parses_like_lf_fixture():
    r = parse_resume(CR_TABBED)
    assert r["name"] == "Lee Example"
    edu = r["education"][0]
    assert edu["degree"] == "Bachelor of Arts" and edu["subject"] == "Business Administration"
    # Label and value verbatim; no scale is ever invented.
    assert edu["gpa"] == {"label": "GPA", "value": "3.5"}
    assert {"microsoft word", "excel"} <= set(r["skills"])


def test_crlf_mixed_text_is_normalized_before_joining():
    j = _join_tab_split_lines("Sam\t\r\n \xa0s@example.com\r\nSkills\r\nPython, SQL")
    assert j.splitlines()[0] == "Sam s@example.com"


def test_degree_line_trailing_date_range_is_not_an_institute():
    r = parse_resume(
        "John Doe\nhello@example.com\n"
        "EDUCATION\nXYZ University\n"
        "Bachelor of Science in Computer Science - 3.8 GPA Sep 2019 - May 2023\n"
        "- Won 1st place in 2022 Education Hackathon\n"
        "SKILLS\nPython, SQL"
    )
    edu = r["education"][0]
    assert edu["degree"] == "Bachelor of Science in Computer Science"
    assert edu["institute"] == "XYZ University"
    assert edu["year"] == 2023
    assert edu["gpa"] == {"label": "GPA", "value": "3.8"}


def test_month_year_fragment_is_not_an_institute():
    r = parse_resume(
        "Jo Example\nj@example.com\n"
        "EDUCATION\nBachelor of Science in Computer Science, May 2023\n"
        "SKILLS\nPython, SQL"
    )
    edu = r["education"][0]
    assert edu["degree"] == "Bachelor of Science in Computer Science"
    # No institute is stated anywhere, so the field stays empty: fail closed.
    assert edu["institute"] == ""
    assert edu["year"] == 2023
