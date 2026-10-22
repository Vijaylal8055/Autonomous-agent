"""Steps 1-2: the tools the agent can use, each described as a JSON schema.

Every tool runs inside a *workspace* directory. The Streamlit app gives each visitor
their own temp workspace, so sessions can't see or overwrite each other's files.
"""
import ast
import operator
import os
from pathlib import Path

DEFAULT_WORKSPACE = Path(os.getenv("AGENT_WORKSPACE", "workspace")).resolve()
MAX_OUTPUT_CHARS = 4000      # guardrail: never flood the context window
MAX_FILE_CHARS = 100_000     # guardrail: cap file size written by the agent
MAX_FILES = 50               # guardrail: cap files per workspace


class ToolError(Exception):
    """Raised for expected, recoverable tool failures (the model sees the message)."""


def _ws(workspace) -> Path:
    p = Path(workspace).resolve() if workspace else DEFAULT_WORKSPACE
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------- implementations (all take the workspace first) ----------
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.USub: operator.neg, ast.FloorDiv: operator.floordiv,
}


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ToolError("Exponent too large.")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ToolError("Unsupported expression. Use numbers and + - * / // % ** only.")


def calculator(ws: Path, expression: str) -> str:
    try:
        return str(_eval(ast.parse(expression, mode="eval").body))
    except (SyntaxError, ZeroDivisionError, OverflowError) as e:
        raise ToolError(f"Could not evaluate: {e}")


def _safe_path(ws: Path, rel: str) -> Path:
    p = (ws / rel).resolve()
    if ws not in p.parents and p != ws:
        raise ToolError("Path escapes the workspace; access denied.")
    return p


def list_files(ws: Path) -> str:
    files = [str(p.relative_to(ws)) for p in ws.rglob("*") if p.is_file()]
    return "\n".join(sorted(files)) or "(workspace is empty)"


def read_file(ws: Path, path: str) -> str:
    p = _safe_path(ws, path)
    if not p.is_file():
        raise ToolError(f"No such file: {path}")
    return p.read_text(errors="replace")


def write_file(ws: Path, path: str, content: str) -> str:
    if len(content) > MAX_FILE_CHARS:
        raise ToolError(f"File too large (limit {MAX_FILE_CHARS} chars).")
    p = _safe_path(ws, path)
    if not p.exists() and sum(1 for x in ws.rglob("*") if x.is_file()) >= MAX_FILES:
        raise ToolError(f"Workspace file limit reached ({MAX_FILES}).")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"Wrote {len(content)} chars to {path}"


def search_files(ws: Path, query: str) -> str:
    """Keyword search across workspace text files (swap in a web-search API later)."""
    hits = []
    for p in ws.rglob("*"):
        if p.is_file() and p.suffix in {".txt", ".md", ".csv", ".json", ".py"}:
            for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                if query.lower() in line.lower():
                    hits.append(f"{p.relative_to(ws)}:{i}: {line.strip()}")
    return "\n".join(hits[:30]) or "No matches."


IMPLS = {
    "calculator": calculator,
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "search_files": search_files,
}

# ---------- JSON schemas sent to the model ----------
TOOLS = [
    {
        "name": "calculator",
        "description": "Evaluate an arithmetic expression, e.g. '(12.5 * 4) / 3'. Use for any math instead of guessing.",
        "input_schema": {
            "type": "object",
            "properties": {"expression": {"type": "string", "description": "Arithmetic expression"}},
            "required": ["expression"],
        },
    },
    {
        "name": "list_files",
        "description": "List all files in the workspace.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_file",
        "description": "Read a text file from the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Relative path in the workspace"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a text file in the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path in the workspace"},
                "content": {"type": "string", "description": "Full file contents"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "search_files",
        "description": "Case-insensitive keyword search across workspace text files. Returns file:line matches.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Keyword or phrase"}},
            "required": ["query"],
        },
    },
]


def run_tool(name: str, args: dict, workspace=None) -> str:
    """Execute a tool inside `workspace`; returns truncated text. Raises ToolError on recoverable failures."""
    if name not in IMPLS:
        raise ToolError(f"Unknown tool: {name}")
    try:
        out = IMPLS[name](_ws(workspace), **args)
    except TypeError as e:  # model sent missing/unknown arguments
        raise ToolError(f"Bad arguments for {name}: {e}")
    if len(out) > MAX_OUTPUT_CHARS:
        out = out[:MAX_OUTPUT_CHARS] + "\n...[truncated]"
    return out
