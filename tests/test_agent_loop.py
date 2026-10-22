"""Offline end-to-end test of the agent loop using a scripted fake model (no network, no key)."""
import json
from types import SimpleNamespace as NS

import agent_free


def _msg(content=None, tool_calls=None):
    m = NS(content=content, tool_calls=tool_calls)
    m.model_dump = lambda exclude_none=True: {
        "role": "assistant", "content": content,
        **({"tool_calls": [{"id": t.id, "type": "function",
                            "function": {"name": t.function.name, "arguments": t.function.arguments}}
                           for t in tool_calls]} if tool_calls else {})}
    return m


def _call(id_, name, args):
    return NS(id=id_, function=NS(name=name, arguments=json.dumps(args)))


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        return NS(choices=[NS(message=self.script.pop(0))], usage=NS(total_tokens=10))


def test_full_loop_runs_tools_and_finishes(tmp_path, monkeypatch):
    script = [
        _msg("Plan: write then read.", [_call("1", "write_file", {"path": "r.txt", "content": "42"})]),
        _msg(None, [_call("2", "read_file", {"path": "r.txt"})]),
        _msg("All done: the file contains 42."),
    ]
    monkeypatch.setattr(agent_free, "make_client", lambda key=None: FakeClient(script))
    events = []
    answer = agent_free.run_agent("task", workspace=tmp_path, on_event=events.append)
    assert answer == "All done: the file contains 42."
    assert (tmp_path / "r.txt").read_text() == "42"
    assert [e["type"] for e in events] == [
        "thought", "tool_call", "tool_result", "tool_call", "tool_result", "final"]


def test_unknown_tool_and_bad_json_are_recovered(tmp_path, monkeypatch):
    bad_json = NS(id="1", function=NS(name="calculator", arguments="{not json"))
    script = [
        _msg(None, [bad_json]),
        _msg(None, [_call("2", "delete_everything", {})]),
        _msg("Recovered."),
    ]
    monkeypatch.setattr(agent_free, "make_client", lambda key=None: FakeClient(script))
    events = []
    assert agent_free.run_agent("task", workspace=tmp_path, on_event=events.append) == "Recovered."
    errors = [e for e in events if e["type"] == "tool_result"]
    assert all(e["is_error"] for e in errors) and len(errors) == 2


def test_step_limit(tmp_path, monkeypatch):
    script = [_msg(None, [_call(str(i), "list_files", {})]) for i in range(5)]
    monkeypatch.setattr(agent_free, "make_client", lambda key=None: FakeClient(script))
    out = agent_free.run_agent("task", workspace=tmp_path, max_steps=3)
    assert out == "Stopped: step limit reached."
