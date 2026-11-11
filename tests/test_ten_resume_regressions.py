"""Regressions from the ten-sample local evaluation (synthetic resumes)."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agents'))
from slate_core.resume import parse_resume


def _skills(text):
    return set(parse_resume(text)['skills'])


def test_machine_learning_does_not_poison_the_skills_list():
    p = parse_resume('Riya Sharma\nSkills\nPython, Java, SQL, React, Docker, Git, Machine Learning\n')
    assert {'python', 'java', 'sql', 'docker', 'git', 'machine learning'} <= set(p['skills'])
    assert p['uncertainSkills'] == []


@pytest.mark.parametrize('field', ['Deep Learning', 'Reinforcement Learning', 'E-learning', 'Learning Management'])
def test_other_learning_nouns_do_not_flag_neighbours(field):
    assert {'python', 'sql'} <= _skills(f'Asha Rao\nSkills\nPython, SQL, {field}\n')


@pytest.mark.parametrize('line', [
    'Learning Python', 'Not experienced in Java', 'Want to learn Docker', 'Currently learning Python and machine learning basics'])
def test_real_negative_or_aspirational_still_protected(line):
    p = parse_resume(f'Sam Roy\nSkills\n{line}\n')
    assert 'python' not in p['skills'] and 'java' not in p['skills'] and 'docker' not in p['skills']


def test_header_with_title_keeps_only_name_and_ignores_header_as_job():
    p = parse_resume('Karan Mehta - Data Analyst\nkaran@example.com\nEducation\nB.Sc Statistics, 2022\nPGDM Analytics, 2024\nExperience\nData Analyst, FinCo, 2024-present\n')
    assert p['name'] == 'Karan Mehta'
    assert [e['degree'] for e in p['education']] == ['B.Sc', 'PGDM']
    assert p['education'][0]['institute'] == '' and p['education'][0]['year'] == 2022
    assert p['experience'] == [{'title': 'Data Analyst', 'org': 'FinCo', 'months': None}]


def test_symbol_after_name_and_prose_name():
    assert parse_resume('Aarav Gupta  \u2605\naarav@example.com\nSkills\nFigma, Research\n')['name'] == 'Aarav Gupta'
    assert parse_resume('Priya Nair is a final-year student with AutoCAD, SolidWorks and MATLAB skills.\n')['name'] == 'Priya Nair'
    assert parse_resume('Contact: x@example.com\nSkills\nPython, SQL, Git\n')['name'] == 'Unknown'


@pytest.mark.parametrize('heading,line,org', [
    ('Internship', 'HR Intern, Zenith Corp - screened 150 resumes', 'Zenith Corp'),
    ('Work Experience', 'Content Executive, BrightMedia, 2023-2025', 'BrightMedia'),
    ('Professional Experience', 'Acme Labs, Software Engineer, 2020-2022: built things using AWS and PostgreSQL', 'Acme Labs'),
    ('Work History', 'Software Intern, Acme Labs (Jun 2025 - Aug 2025)', 'Acme Labs'),
])
def test_employer_is_the_employer_not_a_skill_in_the_sentence(heading, line, org):
    p = parse_resume(f'Jo Doe\n{heading}\n{line}\n')
    assert [e['org'] for e in p['experience']] == [org]


def test_many_roles_each_get_their_own_employer():
    lines = '\n'.join(f'Company {i}, Engineer, 20{i:02d}: used AWS and PostgreSQL' for i in range(10, 20))
    p = parse_resume('Dev Patel\nExperience\n' + lines + '\n')
    assert [e['org'] for e in p['experience']] == [f'Company {i}' for i in range(10, 20)]


def test_bullets_and_goals_are_not_promoted_to_roles_or_degrees():
    p = parse_resume('Jo Doe\nExperience\n- Built Power BI dashboards as analyst for 5 teams\nCareer Objective\nSeeking engineer at BigCo\nMaster data management in my free time\n')
    assert p['experience'] == [] and p['education'] == []


def test_academic_qualifications_heading_and_degree_variants():
    p = parse_resume('Mohit Jain\nAcademic Qualifications\nMBA (HR), Example University, 2025, 7.9 CGPA\nB.Com, 2023\nM.A. Education, 2016; B.Ed, 2015\n')
    assert [(e['degree'], e['institute'], e['year']) for e in p['education']] == [
        ('MBA', 'Example University', 2025), ('B.Com', '', 2023), ('M.A.', '', 2016), ('B.Ed', '', 2015)]


def test_added_vocabulary_is_literal_only():
    assert {'tally', 'autocad'} <= _skills('Sameer Khan\nSkills\nGood at Excel and Tally. Used AutoCAD.\n')


def test_section_preview_recognises_common_alternate_headings():
    p = parse_resume('Mohit Jain\nCareer Objective\nSeeking an HR role\nAcademic Qualifications\nMBA (HR), Example University, 2025\nInternship\nHR Intern, Zenith Corp\nKey Skills\nRecruitment, Payroll\n')
    rev = p['sectionReview']
    assert rev['education']['status'] == 'source_section_needs_review'
    assert rev['education']['sourceLines'] == ['MBA (HR), Example University, 2025']
    assert rev['experience']['sourceLines'] == ['HR Intern, Zenith Corp']


def test_example_instruction_line_is_not_promoted_but_example_institute_is():
    p = parse_resume('Sam Roy\nEducation\nExample, Engineer at FakeCo (12 months)\n')
    assert p['experience'] == [] and p['education'] == []
    p = parse_resume('Sam Roy\nEducation\nB.Tech, Example, 2025\nExperience\nExample: Analyst at FakeCo (3 months)\n')
    assert p['education'] == [{'degree': 'B.Tech', 'institute': 'Example', 'year': 2025}]
    assert p['experience'] == []
    p = parse_resume('Sam Roy\nEducation\nB.Tech Computer Science, IIT Example, 2023-2027\nMBA, Example University, 2025\n')
    assert [e['institute'] for e in p['education']] == ['IIT Example', 'Example University']
    assert parse_resume('Sam Roy\nEducation\nB.Tech, Example, 2025; Seeking engineer at FakeCo\n')['experience'] == []


def test_source_casing_is_preserved_in_degrees_and_titles():
    p = parse_resume('Riya Sharma\nSkills\nPython\nExperience\nML Intern, DataWorks, 2025\nHR Intern, Zenith Corp, 2024\nEducation\nB.Tech CSE, 2026\nB.Sc Statistics, 2022\n')
    assert [e['title'] for e in p['experience']] == ['ML Intern', 'HR Intern']
    assert [e['degree'] for e in p['education']] == ['B.Tech', 'B.Sc']
    p = parse_resume('Jo Doe\nEducation\nB.TECH CSE, 2026\n')
    assert p['education'][0]['degree'] == 'B.TECH'  # uppercase source stays uppercase
