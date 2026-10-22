"""Steps 3-6: call Claude with tools, run requested tools, loop until done."""
import logging
import os
import sys
import time

import anthropic

from tools import TOOLS, ToolError, run_tool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("agent")

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
MAX_STEPS = 12                 # guardrail: hard cap on loop iterations
MAX_TOTAL_TOKENS = 60_000      # guardrail: token budget per task
ALLOWED_TOOLS = {t["name"] for t in TOOLS}
TOOL_RETRIES = 2

SYSTEM = (
    "You are an autonomous assistant. For any non-trivial task, first write a short plan, "
    "then execute it step by step using the tools. Use the calculator for math. "
    "If a tool fails, read the error and try a different approach. "
    "When the task is complete, give a concise final answer."
)

# The SDK already retries 429/5xx/connection errors with backoff; max_retries tunes it.
client = anthropic.Anthropic(max_retries=4)


def run_with_retry(name: str, args: dict) -> str:
    for attempt in range(TOOL_RETRIES + 1):
        try:
            return run_tool(name, args)
        except ToolError:
            raise                      # Claude should see and handle this one
        except Exception as e:         # unexpected: retry, then surface
            log.warning("tool %s crashed (attempt %d): %s", name, attempt + 1, e)
            if attempt == TOOL_RETRIES:
                raise ToolError(f"Tool crashed: {e}")
            time.sleep(2 ** attempt)


def run_agent(task: str) -> str:
    messages = [{"role": "user", "content": task}]
    tokens_used = 0

    for step in range(1, MAX_STEPS + 1):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=SYSTEM,
            tools=TOOLS,
            messages=messages,
        )
        tokens_used += resp.usage.input_tokens + resp.usage.output_tokens
        log.info("step %d | stop_reason=%s | tokens=%d", step, resp.stop_reason, tokens_used)
        messages.append({"role": "assistant", "content": resp.content})

        # Step 5: no more tool requests -> we're done
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text")

        if tokens_used > MAX_TOTAL_TOKENS:
            return "Stopped: token budget exceeded."

        # Step 4: run every tool Claude asked for and return the results
        results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            log.info("tool_call %s %s", block.name, block.input)
            try:
                if block.name not in ALLOWED_TOOLS:
                    raise ToolError(f"Tool not allowed: {block.name}")
                output, is_error = run_with_retry(block.name, block.input), False
            except ToolError as e:
                output, is_error = str(e), True
            log.info("tool_result error=%s %s", is_error, output[:200].replace("\n", " "))
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
                "is_error": is_error,
            })
        messages.append({"role": "user", "content": results})

    return "Stopped: step limit reached."


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) or (
        "Create notes.txt with three project ideas, then search it for 'agent', "
        "and write summary.txt saying how many lines matched. Also compute 17.5% of 2480."
    )
    print("\n=== FINAL ANSWER ===\n" + run_agent(task))
