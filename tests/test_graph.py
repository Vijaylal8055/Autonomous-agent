from graph_agent import build_graph


def test_graph_builds_and_has_expected_nodes(tmp_path):
    g = build_graph(workspace=tmp_path, api_key="test-key")
    nodes = set(g.get_graph().nodes)
    assert {"agent", "tools"} <= nodes
