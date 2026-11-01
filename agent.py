import os
import re
import sys
import json
from pathlib import Path

import requests

from crypto_workflow import PAIRS, fetch_candles, calc_metrics, apply_rules

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "openai/gpt-oss-20b"

SYSTEM = (
    "You answer questions about crypto market data. "
    "Always use the tools for numbers and never guess them. "
    "Describe what the numbers show. Never tell anyone to buy, sell, hold or invest. "
    "Keep answers to a few sentences."
)

ADVICE = re.compile(r"\b(buy|sell|hold|invest in|should invest|go long|go short)\b", re.IGNORECASE)


# ---------- Tools (your Assignment 1 code, wrapped) ----------
_cache = {}


def get_metrics(pair):
    if pair not in _cache:
        m = calc_metrics(fetch_candles(pair))
        m.update(apply_rules(m))
        _cache[pair] = {"pair": pair, **m}
    return _cache[pair]


def read_latest_report():
    files = sorted(Path("reports").glob("report_*.md"))
    if not files:
        return {"error": "no report found. Run crypto_workflow.py first."}
    return {"file": files[-1].name, "text": files[-1].read_text(encoding="utf-8")[:3000]}


TOOLS = [
    {"type": "function", "function": {
        "name": "get_metrics",
        "description": "Get 30-day metrics for one coin: latest close, average close, % vs average, "
                       "volatility, max drawdown, and rule labels",
        "parameters": {"type": "object",
                       "properties": {"pair": {"type": "string", "enum": PAIRS}},
                       "required": ["pair"]}}},
    {"type": "function", "function": {
        "name": "read_latest_report",
        "description": "Read the most recent report written by the workflow",
        "parameters": {"type": "object", "properties": {}}}},
]


# ---------- Talk to the model ----------
def ask_groq(messages, **extra):
    r = requests.post(
        GROQ_URL,
        headers={"Authorization": "Bearer " + os.environ["GROQ_API_KEY"]},
        json={"model": MODEL, "messages": messages, **extra},
        timeout=60,
    )
    if r.status_code != 200:
        raise SystemExit("Groq error: " + r.text)
    return r.json()["choices"][0]["message"]


# ---------- The agent loop ----------
def run_tool(name, args):
    if name == "get_metrics" and args.get("pair") in PAIRS:
        return get_metrics(args["pair"])
    if name == "read_latest_report":
        return read_latest_report()
    return {"error": "tool or input not allowed"}


def run_agent(question, max_steps=6):
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
    for step in range(1, max_steps + 1):
        msg = ask_groq(messages, tools=TOOLS, temperature=0.2)
        calls = msg.get("tool_calls")
        if not calls:
            return check_answer(msg["content"])
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for call in calls:
            name = call["function"]["name"]
            args = json.loads(call["function"]["arguments"] or "{}")
            print("STEP", step, "->", name, args)
            result = run_tool(name, args)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})
    return "Stopped: too many steps"


def check_answer(text):
    # Code guardrail: the prompt can fail, so we also check the answer
    if ADVICE.search(text):
        return ("I can only describe what the data shows, not give buy or sell advice. "
                "Ask me about volatility, trends or averages instead.")
    return text + "\n\nThis is for education only and is not financial advice."


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python3 agent.py "your question"')
    print(run_agent(" ".join(sys.argv[1:])))
