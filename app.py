"""Streamlit UI for the autonomous agent (deploys on Streamlit Community Cloud)."""
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Autonomous AI Agent", page_icon="🤖", layout="wide")

MAX_RUNS_PER_SESSION = 15   # protects your free Groq quota on a public app
COOLDOWN_SECONDS = 3
MODELS = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
EXAMPLES = [
    "Create notes.txt with 3 project ideas, then search it for 'agent' and write summary.txt with the match count.",
    "What is 17.5% of 2480? Save the answer in result.txt and read it back to confirm.",
    "Write a 5-item packing checklist to checklist.md, then list all files in the workspace.",
]


def secret(name, default=None):
    """Streamlit secrets first (Cloud), then environment variables (local)."""
    try:
        return st.secrets[name]
    except Exception:
        return os.getenv(name, default)


# ---------- optional password gate ----------
app_password = secret("APP_PASSWORD")
if app_password and not st.session_state.get("authed"):
    st.title("🤖 Autonomous AI Agent")
    pw = st.text_input("Password", type="password")
    if pw:
        if pw == app_password:
            st.session_state.authed = True
            st.rerun()
        else:
            st.error("Wrong password.")
    st.stop()

# ---------- per-visitor state ----------
if "workspace" not in st.session_state:
    st.session_state.workspace = tempfile.mkdtemp(prefix="agent_ws_")
    st.session_state.history = []
    st.session_state.runs = 0
    st.session_state.last_run = 0.0
workspace = Path(st.session_state.workspace)
api_key = secret("GROQ_API_KEY")

# ---------- sidebar ----------
with st.sidebar:
    st.header("Settings")
    engine = st.radio("Engine", ["Plain loop", "LangGraph"], help="Same tools, two implementations.")
    model = st.selectbox("Model (Groq)", MODELS, help="8B is faster and has higher free-tier limits.")
    max_steps = st.slider("Max steps", 3, 15, 10)
    st.caption(f"Runs left this session: {MAX_RUNS_PER_SESSION - st.session_state.runs}")

    st.header("Workspace files")
    files = sorted(p for p in workspace.rglob("*") if p.is_file())
    if not files:
        st.caption("Empty. Files the agent writes appear here.")
    for i, p in enumerate(files):
        rel = str(p.relative_to(workspace))
        with st.expander(rel):
            text = p.read_text(errors="replace")
            st.code(text[:2000] or "(empty)")
            st.download_button("Download", text, file_name=p.name, key=f"dl_{i}_{rel}")

    if st.button("Reset session"):
        shutil.rmtree(workspace, ignore_errors=True)
        for k in ("workspace", "history", "runs", "last_run"):
            st.session_state.pop(k, None)
        st.rerun()


def render_event(e):
    t = e["type"]
    if t == "thought":
        st.markdown(f"💭 {e['text']}")
    elif t == "tool_call":
        st.markdown(f"🔧 **{e['name']}**")
        st.code(json.dumps(e["args"], indent=2), language="json")
    elif t == "tool_result":
        st.markdown("❌ **error**" if e["is_error"] else "✅ **result**")
        st.code(e["text"][:800], language=None)
    elif t == "error":
        st.warning(e["text"])


# ---------- main ----------
st.title("🤖 Autonomous AI Agent")
st.caption("Plans, calls tools, and finishes multi-step tasks. Powered by Groq (free tier).")

if not api_key:
    st.error("GROQ_API_KEY is missing. Add it in Streamlit Cloud → App settings → Secrets, "
             "or export it locally.")
    st.stop()

for item in st.session_state.history:
    with st.chat_message("user"):
        st.markdown(item["task"])
    with st.chat_message("assistant"):
        with st.expander(f"Agent trace ({len(item['trace'])} events)"):
            for e in item["trace"]:
                render_event(e)
        st.markdown(item["answer"])

if not st.session_state.history:
    st.write("Try an example:")
    cols = st.columns(len(EXAMPLES))
    for col, ex in zip(cols, EXAMPLES):
        if col.button(ex, use_container_width=True):
            st.session_state.pending = ex
            st.rerun()

task = st.chat_input("Describe a multi-step task…") or st.session_state.pop("pending", None)

if task:
    if st.session_state.runs >= MAX_RUNS_PER_SESSION:
        st.warning("Session run limit reached. Use 'Reset session' in the sidebar.")
        st.stop()
    if time.time() - st.session_state.last_run < COOLDOWN_SECONDS:
        st.warning("Please wait a moment between runs.")
        st.stop()

    with st.chat_message("user"):
        st.markdown(task)
    with st.chat_message("assistant"):
        trace = []
        with st.status("Agent is working…", expanded=True) as status:
            def on_event(e):
                trace.append(e)
                render_event(e)

            try:
                if engine == "LangGraph":
                    from graph_agent import run_graph as runner
                else:
                    from agent_free import run_agent as runner
                answer = runner(task, workspace=str(workspace), on_event=on_event,
                                api_key=api_key, model=model, max_steps=max_steps)
                status.update(label="Done", state="complete", expanded=False)
            except Exception as exc:  # show a friendly error instead of a stack trace
                answer = f"Something went wrong: `{type(exc).__name__}: {exc}`"
                status.update(label="Failed", state="error")
        st.markdown(answer)

    st.session_state.runs += 1
    st.session_state.last_run = time.time()
    st.session_state.history.append({"task": task, "trace": trace, "answer": answer})
    st.rerun()
