"""HTTP status regression checks for the target feature's contract errors."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))
from fastapi.testclient import TestClient
from slate_api.app import create_app, STATUS


def test_missing_target_uses_not_found_status():
    response = TestClient(create_app()).get('/v1/targets/not-a-target')
    assert response.status_code == 404
    assert response.json()['error']['code'] == 'target_not_found'


def test_target_validation_status_codes_are_registered():
    assert STATUS['invalid_target'] == 422
    assert STATUS['invalid_source_preservation'] == 422
