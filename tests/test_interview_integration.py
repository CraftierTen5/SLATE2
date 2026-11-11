"""Synthetic finish/state/provider failure regressions, no live calls.

Adapted for the feature-wise restart: per-user isolation is exercised at the
service level over the agreed duck store protocol (load()/save(state)), one
store per user snapshot, until the auth slice and Akarsh's user store land.
HTTP shape is checked through create_app's single-tenant fixture mode.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agents'))
from slate_core.interview import InterviewStore, GeminiInterviewCoach
from slate_core.llm import MockLLM
from slate_core.service import SlateService, SlateError


def test_finished_legacy_session_cannot_accept_null_question():
    s = InterviewStore()
    s._sessions['old'] = {'role': 'Data Analyst', 'questions': ['Question?'],
                          'answers': ['A saved answer'], 'carried': []}
    with pytest.raises(ValueError, match='interview_ended'):
        s.answer('old', 'Another answer')
    assert len(s._sessions['old']['answers']) == 1


def test_partial_state_marker_not_carried_as_a_weak_skill():
    s = InterviewStore()
    i = s.start('Data Analyst', [])['sessionId']
    s.answer(i, 'short')
    f = s.feedback(i)
    assert 'interview still in progress' in f['weakAreas']
    again = s.start('Data Analyst', s.past_feedback('Data Analyst'))
    assert again['carriedFromEarlier']
    assert 'interview still in progress' not in again['carriedFromEarlier']


@pytest.mark.parametrize('reply', ['not JSON', '{"score":"bad"}', '{}'])
def test_malformed_provider_output_cannot_stop_fallback(reply):
    s = InterviewStore(coach=GeminiInterviewCoach(MockLLM(reply)))
    i = s.start('Data Analyst', [])['sessionId']
    r = s.answer(i, 'I checked the SQL query and compared the results with the source data.')
    assert r['nextQuestion'] and 1 <= r['evaluation']['score'] <= 5
    assert s.end(i)['ended']


def test_provider_failure_switches_to_honest_fallback():
    class Broken:
        def generate(self, prompt):
            raise TimeoutError('synthetic provider timeout')
    s = InterviewStore(coach=GeminiInterviewCoach(Broken()))
    started = s.start('Data Analyst', [])
    assert started['coachMode'] == 'deterministic_fallback'
    r = s.answer(started['sessionId'], 'I checked a SQL query and validated the test results.')
    assert r['nextQuestion']
    assert s.end(started['sessionId'])['coachMode'] == 'deterministic_fallback'


class _MemStore:
    """Duck-typed persistence fixture for the agreed store protocol:
    load() -> dict | None and save(state: dict). One store stands in for one
    user's snapshot, the isolation the per-user store will enforce later."""

    def __init__(self):
        self.state = None

    def load(self):
        return self.state

    def save(self, state):
        # Round-trip through JSON so only serializable session data persists.
        self.state = json.loads(json.dumps(state))


def test_end_report_restart_and_account_isolation():
    a_store, b_store = _MemStore(), _MemStore()
    a = SlateService(store=a_store)
    b = SlateService(store=b_store)
    i = a.start_interview('Human Resources', 'voice')['sessionId']
    a.answer_interview(i, 'I checked employee policy and documented the complaint.')
    with pytest.raises(SlateError) as other_end:
        b.end_interview(i)
    assert other_end.value.code == 'session_not_found'
    f = a.end_interview(i)
    assert f['ended'] and f['answeredCount'] == 1
    # Restart: a fresh service over the same saved state keeps the interview.
    a2 = SlateService(store=a_store)
    assert a2.interview_feedback(i)['answerReviews'][0]['answer'].startswith('I checked')
    with pytest.raises(SlateError) as after_end:
        a2.answer_interview(i, 'extra')
    assert after_end.value.code == 'interview_ended'
    assert a2.end_interview(i)['answeredCount'] == 1
    with pytest.raises(SlateError) as other_feedback:
        b.interview_feedback(i)
    assert other_feedback.value.code == 'session_not_found'


def test_interview_http_routes_and_status_codes():
    # Function-scoped import: a module-level TestClient import is collected by
    # pytest as a test class.
    from fastapi.testclient import TestClient
    from slate_api.app import create_app
    c = TestClient(create_app())
    started = c.post('/v1/interview/mock', json={'targetRole': 'Data Analyst', 'mode': 'text'})
    assert started.status_code == 200
    sid = started.json()['sessionId']
    assert started.json()['coachMode'] == 'deterministic_fallback'
    assert c.post('/v1/interview/mock', json={'targetRole': 'x', 'mode': 'video'}).status_code == 422
    assert c.post(f'/v1/interview/{sid}/answer', json={'text': '   '}).status_code == 422
    assert c.post('/v1/interview/sid_999/answer', json={'text': 'x'}).status_code == 404
    ok = c.post(f'/v1/interview/{sid}/answer',
                json={'text': 'I checked the SQL query and compared the results with the source data.'})
    assert ok.status_code == 200 and ok.json()['nextQuestion']
    assert c.post(f'/v1/interview/{sid}/end').status_code == 200
    assert c.post(f'/v1/interview/{sid}/answer', json={'text': 'extra'}).status_code == 409
    assert c.get(f'/v1/interview/{sid}/feedback').status_code == 200
    assert c.get('/v1/interview/sid_999/feedback').status_code == 404


def test_authenticated_end_report_restart_and_account_isolation(tmp_path):
    """Served construction: bearer token -> verified user -> that user's
    service over the real per-user store. DevAuth + sqlite only; no live
    provider, no Postgres. Interview sessions and coaching memory must stay
    inside the owning account across restarts."""
    from fastapi.testclient import TestClient
    from slate_core.auth import DevAuth
    from slate_core.user_store import SqlUserStore
    from slate_api.app import create_authenticated_app

    url = 'sqlite:///' + str(tmp_path / 'state.db')

    def client():
        return TestClient(create_authenticated_app(DevAuth(), SqlUserStore(url)))

    c = client()
    a = {'Authorization': 'Bearer dev:a@example.com'}
    b = {'Authorization': 'Bearer dev:b@example.com'}
    started = c.post('/v1/interview/mock', headers=a,
                     json={'targetRole': 'Human Resources', 'mode': 'voice'})
    assert started.status_code == 200
    i = started.json()['sessionId']
    assert started.json()['coachMode'] == 'deterministic_fallback'  # no key -> honest fallback
    assert c.post(f'/v1/interview/{i}/answer', headers=a,
                  json={'text': 'I checked employee policy and documented the complaint.'}).status_code == 200
    assert c.post(f'/v1/interview/{i}/end', headers=b).status_code == 404  # not b's session
    f = c.post(f'/v1/interview/{i}/end', headers=a).json()
    assert f['ended'] and f['answeredCount'] == 1
    # Restart: a fresh app over the same sqlite file keeps a's interview.
    c = client()
    review = c.get(f'/v1/interview/{i}/feedback', headers=a).json()
    assert review['answerReviews'][0]['answer'].startswith('I checked')
    assert c.post(f'/v1/interview/{i}/answer', headers=a, json={'text': 'extra'}).status_code == 409
    assert c.post(f'/v1/interview/{i}/end', headers=a).json()['answeredCount'] == 1
    assert c.get(f'/v1/interview/{i}/feedback', headers=b).status_code == 404
    # Coaching memory is per-user: b starts the same role with no carried weak areas.
    started_b = c.post('/v1/interview/mock', headers=b,
                       json={'targetRole': 'Human Resources', 'mode': 'text'})
    assert started_b.status_code == 200
    assert started_b.json()['carriedFromEarlier'] == []
