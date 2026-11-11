"""Ancillary backend setup must not expose database credentials."""
import importlib.util
from pathlib import Path
from fastapi.testclient import TestClient


def test_backend_health_only_exposes_configured_flag(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql://example:never-return-this@localhost/db')
    spec = importlib.util.spec_from_file_location('slate_setup_health', Path(__file__).resolve().parents[1] / 'backend' / 'main.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    response = TestClient(module.app).get('/')
    assert response.status_code == 200
    assert response.json() == {'message': 'Backend is running', 'database_configured': True}
    assert 'never-return-this' not in response.text
