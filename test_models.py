from types import SimpleNamespace as NS

import agent_free


class FakeClient:
    def __init__(self, ids):
        self.models = NS(list=lambda: NS(data=[NS(id=i) for i in ids]))

    def with_options(self, **kw):
        return self


def test_list_models_filters_and_orders(monkeypatch):
    ids = ["whisper-large-v3", "llama-3.1-8b-instant", "openai/gpt-oss-20b", "groq/compound"]
    monkeypatch.setattr(agent_free, "make_client", lambda key=None: FakeClient(ids))
    assert agent_free.list_models("k") == ["openai/gpt-oss-20b", "llama-3.1-8b-instant"]


def test_list_models_falls_back_on_error(monkeypatch):
    def boom(key=None):
        raise RuntimeError("no network")
    monkeypatch.setattr(agent_free, "make_client", boom)
    assert agent_free.list_models("k") == agent_free.PREFERRED_MODELS
