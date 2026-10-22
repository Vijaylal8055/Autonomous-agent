"""The same agent as a LangGraph state machine: agent -> tools -> agent -> ... -> END.

build_graph() makes a graph bound to one workspace; run_graph() streams events for a UI.
"""
import os
import sys

from langchain_core.tools import tool
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from tools import ToolError, run_tool

PROVIDER = os.getenv("PROVIDER", "groq")   # groq (free key) | ollama (no key) | anthropic
DEFAULT_MODEL = os.getenv("MODEL", "llama-3.3-70b-versatile")
SYSTEM = (
    "You are an autonomous assistant. Plan briefly, use tools step by step, "
    "recover from tool errors, and finish with a concise answer."
)


def _make_llm(api_key=None, model=None):
    if PROVIDER == "ollama":
        from langchain_ollama import ChatOllama          # local, no key
        return ChatOllama(model=model or os.getenv("MODEL", "qwen2.5:7b"), temperature=0)
    if PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic    # needs ANTHROPIC_API_KEY
        return ChatAnthropic(model=model or os.getenv("MODEL", "claude-sonnet-5-5"), max_tokens=2000)
    from langchain_groq import ChatGroq                  # needs free GROQ_API_KEY
    key = api_key or os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not set. Add it to your environment or Streamlit secrets.")
    return ChatGroq(model=model or DEFAULT_MODEL, temperature=0, api_key=key)


def build_graph(workspace=None, api_key=None, model=None):
    def _safe(name: str, **kwargs) -> str:
        try:
            return run_tool(name, kwargs, workspace)
        except ToolError as e:
            return f"ERROR: {e}"

    @tool
    def calculator(expression: str) -> str:
        """Evaluate an arithmetic expression, e.g. '(12.5 * 4) / 3'."""
        return _safe("calculator", expression=expression)

    @tool
    def list_files() -> str:
        """List all files in the workspace."""
        return _safe("list_files")

    @tool
    def read_file(path: str) -> str:
        """Read a text file from the workspace."""
        return _safe("read_file", path=path)

    @tool
    def write_file(path: str, content: str) -> str:
        """Create or overwrite a text file in the workspace."""
        return _safe("write_file", path=path, content=content)

    @tool
    def search_files(query: str) -> str:
        """Case-insensitive keyword search across workspace text files."""
        return _safe("search_files", query=query)

    tools = [calculator, list_files, read_file, write_file, search_files]
    llm = _make_llm(api_key, model).bind_tools(tools)

    def agent_node(state: MessagesState):
        msgs = [{"role": "system", "content": SYSTEM}] + state["messages"]
        return {"messages": [llm.invoke(msgs)]}

    builder = StateGraph(MessagesState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
    builder.add_edge("tools", "agent")
    return builder.compile()


def _text(content) -> str:
    if isinstance(content, list):
        return "".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    return content or ""


def run_graph(task, workspace=None, on_event=None, api_key=None, model=None, max_steps=12) -> str:
    emit = on_event or (lambda e: None)
    graph = build_graph(workspace, api_key, model)
    final = ""
    try:
        # each agent+tools round trip is ~2 graph steps; recursion_limit is the loop guardrail
        for update in graph.stream(
            {"messages": [("user", task)]},
            config={"recursion_limit": max_steps * 2 + 1},
            stream_mode="updates",
        ):
            for node, payload in update.items():
                for m in payload["messages"]:
                    if node == "agent":
                        calls = getattr(m, "tool_calls", None) or []
                        text = _text(m.content)
                        if calls:
                            if text:
                                emit({"type": "thought", "text": text})
                            for c in calls:
                                emit({"type": "tool_call", "name": c["name"], "args": c["args"]})
                        else:
                            final = text
                            emit({"type": "final", "text": text})
                    elif node == "tools":
                        out = _text(m.content)
                        emit({"type": "tool_result", "name": m.name, "text": out,
                              "is_error": out.startswith("ERROR")})
    except GraphRecursionError:
        return "Stopped: step limit reached."
    return final


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) or "Write hello.txt containing the result of 12*34, then read it back."
    print(run_graph(task))
