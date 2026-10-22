"""Smoke test: the Streamlit app renders without exceptions."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_app_shows_missing_key_message(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert any("GROQ_API_KEY" in e.value for e in at.error)


def test_app_renders_with_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value.endswith("Autonomous AI Agent")
