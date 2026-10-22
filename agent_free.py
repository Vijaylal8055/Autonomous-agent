"""Steps 3-6: the agent loop on a free backend (Groq by default, Ollama optional).

run_agent() is used by both the CLI and the Streamlit app. Pass `on_event` to stream
progress (thoughts, tool calls, tool results) to a UI.
"""
import json
import logging
import os
import sys
import time

import openai
from openai import OpenAI

from tools import TOOLS, ToolError, run_tool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("agent")

PROVIDER = os.getenv("PROVIDER", "groq")   # groq | ollama
CONFIGS = {
    "groq": dict(base_url="https://api.groq.com/openai/v1", model="openai/gpt-oss-120b"),
    "ollama": dict(base_url="http://localhost:11434/v1", model="qwen2.5:7b"),
}
CONFIG = CONFIGS[PROVIDER]
DEFAULT_MODEL = os.getenv("MODEL", CONFIG["model"])

# Groq's catalog changes often, so the app also asks the API which models your key can use.
PREFERRED_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b",
                    "llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
_NON_CHAT = ("whisper", "tts", "guard", "embed", "orpheus", "playai", "compound", "safeguard")

MAX_STEPS = 12              # guardrail: hard cap on loop iterations
MAX_TOTAL_TOKENS = 60_000   # guardrail: token budget per task
TOOL_RETRIES = 2
ALLOWED_TOOLS = {t["name"] for t in TOOLS}

SYSTEM = (
    "You are an autonomous assistant. For any non-trivial task, first write a short plan, "
    "then execute it step by step using the tools. Use the calculator for math. "
    "If a tool returns an ERROR, read it and try a different approach. "
    "When the task is complete, give a concise final answer."
)

# Convert our JSON schemas to the OpenAI-compatible tool format
OAI_TOOLS = [
    {"type": "function",
     "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
    for t in TOOLS
]


def make_client(api_key: str | None = None) -> OpenAI:
    """Built lazily so importing this module never requires a key."""
    if PROVIDER == "ollama":
        key = "ollama"
    else:
        key = api_key or os.getenv("GROQ_API_KEY")
        if not key:
            raise RuntimeError("GROQ_API_KEY is not set. Add it to your environment or Streamlit secrets.")
    return OpenAI(base_url=CONFIG["base_url"], api_key=key, max_retries=3)


def list_models(api_key: str | None = None) -> list[str]:
    """Chat models this key can use (preferred ones first); falls back to PREFERRED_MODELS."""
    try:
        client = make_client(api_key).with_options(max_retries=0, timeout=10)
        ids = [m.id for m in client.models.list().data]
    except Exception as e:
        log.warning("could not list models: %s", e)
        return PREFERRED_MODELS
    chat = [i for i in ids if not any(x in i.lower() for x in _NON_CHAT)]
    preferred = [m for m in PREFERRED_MODELS if m in chat]
    return preferred or sorted(chat) or PREFERRED_MODELS


def _assistant_dict(msg) -> dict:
    """Only send back the standard fields (open models add extras like 'reasoning')."""
    d = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        d["tool_calls"] = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
            for tc in msg.tool_calls
        ]
    return d


def run_with_retry(name: str, args: dict, workspace=None) -> str:
    for attempt in range(TOOL_RETRIES + 1):
        try:
            return run_tool(name, args, workspace)
        except ToolError:
            raise                      # the model should see and handle this one
        except Exception as e:         # unexpected crash: retry, then surface
            log.warning("tool %s crashed (attempt %d): %s", name, attempt + 1, e)
            if attempt == TOOL_RETRIES:
                raise ToolError(f"Tool crashed: {e}")
            time.sleep(2 ** attempt)


def run_agent(task, workspace=None, on_event=None, api_key=None, model=None, max_steps=MAX_STEPS) -> str:
    emit = on_event or (lambda e: None)
    client = make_client(api_key)
    model = model or DEFAULT_MODEL
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task}]
    tokens_used = 0

    for step in range(1, max_steps + 1):
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, tools=OAI_TOOLS, temperature=0, max_tokens=4096
            )
        except openai.NotFoundError:
            emit({"type": "error", "text": f"Model '{model}' is not available to your key."})
            return (f"Stopped: model `{model}` was not found. Pick another model in the sidebar "
                    "or set the MODEL environment variable.")
        except openai.RateLimitError:
            emit({"type": "error", "text": "Rate limit hit (free tier). Wait a minute and retry."})
            return "Stopped: the free-tier rate limit was reached. Please try again in a minute."
        except openai.BadRequestError as e:
            # Open models sometimes emit a malformed tool call; nudge and retry.
            log.warning("bad request (likely malformed tool call): %s", e)
            emit({"type": "error", "text": "Model produced a malformed tool call; retrying."})
            messages.append({"role": "user",
                             "content": "Your previous tool call was malformed. Call the tool again with valid JSON arguments."})
            continue

        msg = resp.choices[0].message
        if resp.usage:
            tokens_used += resp.usage.total_tokens
        log.info("step %d | tool_calls=%d | tokens=%d", step, len(msg.tool_calls or []), tokens_used)
        messages.append(_assistant_dict(msg))

        if not msg.tool_calls:                         # loop ends: no more tool requests
            emit({"type": "final", "text": msg.content or ""})
            return msg.content or ""
        if msg.content:
            emit({"type": "thought", "text": msg.content})
        if tokens_used > MAX_TOTAL_TOKENS:
            return "Stopped: token budget exceeded."

        for tc in msg.tool_calls:
            name = tc.function.name
            args = {}
            try:
                args = json.loads(tc.function.arguments or "{}")   # small models can emit bad JSON
                emit({"type": "tool_call", "name": name, "args": args})
                if name not in ALLOWED_TOOLS:
                    raise ToolError(f"Tool not allowed: {name}")
                output, is_error = run_with_retry(name, args, workspace), False
            except json.JSONDecodeError:
                output, is_error = "ERROR: arguments were not valid JSON. Retry with valid JSON.", True
            except ToolError as e:
                output, is_error = f"ERROR: {e}", True
            log.info("tool %s -> %s", name, output[:200].replace("\n", " "))
            emit({"type": "tool_result", "name": name, "text": output, "is_error": is_error})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": output})

    return "Stopped: step limit reached."


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) or (
        "Create notes.txt with three project ideas, then search it for 'agent', "
        "and write summary.txt saying how many lines matched. Also compute 17.5% of 2480."
    )
    print(f"[{PROVIDER} / {DEFAULT_MODEL}]")
    print("\n=== FINAL ANSWER ===\n" + run_agent(task))
