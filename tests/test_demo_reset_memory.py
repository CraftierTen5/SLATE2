"""Demo reset is explicit and does not delete interview memory."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))
import pytest
from fastapi.testclient import TestClient
from slate_core import SlateService, SlateError
from slate_api.app import create_app


def test_reset_is_explicit_and_preserves_interviews():
    service = SlateService()
    resume = service.upload_resume('Asha Verma\nSkills: Python, Git')['resumeId']
    session = service.start_interview('Data Analyst')['sessionId']
    with pytest.raises(SlateError):
        service.reset_demo('')
    assert service.get_resume(resume)
    assert service.reset_demo('reset') == {'reset': True}
    assert service.list_resumes()['totalCount'] == 0
    assert session in service.interviews._sessions


def test_reset_endpoint_is_opt_in(monkeypatch):
    monkeypatch.delenv('SLATE_DEMO_RESET', raising=False)
    client = TestClient(create_app())
    response = client.post('/v1/demo/reset', json={'confirm': 'reset'})
    assert response.status_code == 403
