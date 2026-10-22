import pytest

from tools import ToolError, run_tool


def test_calculator(tmp_path):
    assert run_tool("calculator", {"expression": "17.5/100*2480"}, tmp_path) == "434.0"


def test_calculator_rejects_code(tmp_path):
    with pytest.raises(ToolError):
        run_tool("calculator", {"expression": "__import__('os').system('ls')"}, tmp_path)


def test_write_read_search_list(tmp_path):
    run_tool("write_file", {"path": "a.txt", "content": "agent one\nother\nagent two"}, tmp_path)
    assert run_tool("read_file", {"path": "a.txt"}, tmp_path).startswith("agent one")
    assert len(run_tool("search_files", {"query": "AGENT"}, tmp_path).splitlines()) == 2
    assert run_tool("list_files", {}, tmp_path) == "a.txt"


def test_path_traversal_blocked(tmp_path):
    with pytest.raises(ToolError):
        run_tool("read_file", {"path": "../../etc/passwd"}, tmp_path)
    with pytest.raises(ToolError):
        run_tool("write_file", {"path": "../evil.txt", "content": "x"}, tmp_path)


def test_sessions_are_isolated(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    run_tool("write_file", {"path": "x.txt", "content": "secret"}, a)
    with pytest.raises(ToolError):
        run_tool("read_file", {"path": "x.txt"}, b)


def test_bad_arguments_become_tool_error(tmp_path):
    with pytest.raises(ToolError):
        run_tool("read_file", {"wrong": "arg"}, tmp_path)
