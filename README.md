# Autonomous AI Agent — Groq + LangGraph + Streamlit

An assistant that plans, calls tools, and finishes multi-step tasks. Two interchangeable engines
(a plain tool-use loop and LangGraph) behind a Streamlit UI, running on Groq's free tier.

```
app.py            Streamlit UI (live agent trace, workspace files, limits)
agent_free.py     Plain tool-use loop (steps 3-6)
graph_agent.py    LangGraph version of the same agent
tools.py          Tool JSON schemas + sandboxed implementations (steps 1-2)
agent.py          Optional: plain loop on the Claude API
tests/            Offline tests (fake model, no key needed)
.github/workflows CI (compile + pytest) and a 6-hourly restart/keep-awake job
scripts/          keepalive.py: headless-browser wake-up check used by the restart workflow
.streamlit/       config + secrets template
```

## 1. Run locally
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit it and set GROQ_API_KEY (free key: https://console.groq.com -> API Keys)

pytest -q                    # all offline, should pass
streamlit run app.py         # opens http://localhost:8501
```
CLI alternatives: `GROQ_API_KEY=... python agent_free.py "your task"` or `python graph_agent.py "your task"`.

## 2. Push to GitHub
```bash
git init && git add . && git commit -m "Autonomous agent"
git branch -M main
git remote add origin https://github.com/<you>/autonomous-agent.git
git push -u origin main
```
`.gitignore` already excludes `.streamlit/secrets.toml` — **never commit your key**.

## 3. Deploy on Streamlit Community Cloud
1. Go to https://share.streamlit.io and sign in with GitHub.
2. **Create app** → choose your repo, branch `main`, main file path `app.py`.
3. **Advanced settings** → pick Python 3.12 and paste your secrets:
   ```toml
   GROQ_API_KEY = "gsk_..."
   APP_PASSWORD = "choose-something"   # optional but recommended for a public URL
   ```
4. **Deploy**. First build takes a few minutes while it installs `requirements.txt`.
5. Updates: every `git push` to `main` redeploys automatically. Edit secrets any time under App settings → Secrets.

(Streamlit may tweak menu labels over time; the flow stays the same.)

## 4. Operating notes
- **Free-tier limits:** Groq rate-limits requests. The app retries with backoff and shows a friendly
  message on a 429. Use `llama-3.1-8b-instant` for higher limits.
- **Public URL = shared quota:** set `APP_PASSWORD`, and keep the per-session run cap
  (`MAX_RUNS_PER_SESSION` in `app.py`).
- **Files are ephemeral:** each visitor gets a temp workspace; it's wiped when the app restarts or sleeps.
  The sidebar has Download buttons.
- **Sleeping apps:** free apps hibernate after inactivity; the first visit afterwards wakes them up.
- **Model names change:** if Groq retires a model, edit `MODELS` in `app.py` and the default in `agent_free.py`.

## 5. Scheduled restart + keep-awake (every 6 hours)
`.github/workflows/restart-app.yml` runs every 6 hours (and on demand from the Actions tab):
1. **Restart:** pushes an empty commit to `main`. Streamlit Community Cloud redeploys when the branch changes.
2. **Wake check:** after 2 minutes, `scripts/keepalive.py` opens your app in a headless browser, clicks
   the "get this app back up" button if the app was hibernating, and confirms it renders.

One-time setup:
- GitHub repo → **Settings → Secrets and variables → Actions → Variables → New variable**:
  name `APP_URL`, value your app URL (e.g. `https://your-app.streamlit.app`).
- Repo → **Settings → Actions → General → Workflow permissions** → allow read and write
  (the workflow also declares `contents: write`).

Notes:
- To keep the app awake **without** restarting it, set `RESTART_APP: "false"` at the top of the workflow.
- A restart wipes every visitor's temporary workspace, and adds ~4 empty commits per day to your history.
- GitHub cron runs can start a few minutes late. Streamlit hibernates apps after a period without
  visitors (roughly 12 hours), so a 6-hour schedule keeps it warm.
- If the empty-commit restart doesn't redeploy for you, use **Manage app → Reboot app** instead, or set
  `RESTART_APP: "false"` and rely on the wake check alone.
- If Streamlit changes its page layout, update the selectors/button text in `scripts/keepalive.py`.

## Guardrails (step 6)
Step cap, token budget, tool allowlist, per-session workspace sandbox with path-traversal blocking,
file size/count limits, output truncation, tool retries, bad-JSON and malformed-tool-call recovery,
rate-limit handling, per-session run cap and cooldown, optional password, logging.

## Ideas to extend
Real web-search tool, human approval before `write_file`, LangGraph checkpointer (`MemorySaver`),
a planner node that stores the plan in graph state.
