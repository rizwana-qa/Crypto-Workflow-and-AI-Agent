import os
import re
import json
from datetime import datetime, timezone
from pathlib import Path
 
import requests
 
# These come from the template. They do the data work, not the AI.
from crypto_workflow import fetch_candles, calc_metrics, apply_rules, WINDOW, HIGH_VOL, BAND
 
# ---------- Settings ----------
PAIR = "XBTUSD"          # Kraken calls Bitcoin XBT
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "openai/gpt-oss-20b"
 
# Words that sound like advice. If the AI uses them, we reject the answer.
ADVICE = re.compile(
    r"\b(buy|buying|sell(?!-?off)|selling|invest in|should invest|go long|go short|accumulate)\b",
    re.IGNORECASE,
)
 
 
# ---------- 1. Numbers (your code, not the AI) ----------
def get_facts():
    candles = fetch_candles(PAIR)[-WINDOW:]       # the last 30 finished days
    facts = calc_metrics(candles)                 # from the template
    facts.update(apply_rules(facts))              # the template's rule labels
 
    # A few extra numbers so the AI has more to choose from
    closes = [c["close"] for c in candles]
    returns = [(closes[i] / closes[i - 1] - 1) * 100 for i in range(1, len(closes))]
    best = max(range(len(returns)), key=lambda i: returns[i])
    worst = min(range(len(returns)), key=lambda i: returns[i])
    day = lambda c: datetime.fromtimestamp(c["time"], timezone.utc).strftime("%Y-%m-%d")
    volumes = [c["volume"] for c in candles]
    facts.update({
        "highest_price": round(max(c["high"] for c in candles), 2),
        "lowest_price": round(min(c["low"] for c in candles), 2),
        "best_day": f"{day(candles[best + 1])} ({round(returns[best], 2)}%)",
        "worst_day": f"{day(candles[worst + 1])} ({round(returns[worst], 2)}%)",
        "volume_last_7_days_vs_earlier_pct": round(
            (sum(volumes[-7:]) / 7) / (sum(volumes[:-7]) / (len(volumes) - 7)) * 100 - 100, 1),
        "rules_used": f"volatility is high above {HIGH_VOL}% daily; "
                      f"price is well above or below its average when more than {BAND}% away",
    })
    table = "\n".join(f"{day(c)}: close {round(c['close'], 2)}" for c in candles)
    return facts, table
 
 
# ---------- 2. Ask the AI to analyse ----------
def ask_groq(prompt):
    r = requests.post(
        GROQ_URL,
        headers={"Authorization": "Bearer " + os.environ["GROQ_API_KEY"]},
        json={"model": MODEL, "temperature": 0.2,
              "messages": [{"role": "system", "content": "Reply with JSON only. No extra text."},
                           {"role": "user", "content": prompt}]},
        timeout=60,
    )
    if r.status_code != 200:
        raise SystemExit("Groq error: " + r.text)
    return r.json()["choices"][0]["message"]["content"].strip()
 
 
def get_analysis(facts, table):
    prompt = (
        f"You are a careful market data analyst. Here are numbers for Bitcoin ({PAIR}), "
        f"the last {WINDOW} finished daily candles.\n\n"
        f"Numbers calculated by code:\n{json.dumps(facts, indent=2)}\n\n"
        f"Daily closes:\n{table}\n\n"
        "Decide which kinds of analysis are useful here (for example trend, volatility, drawdown, "
        "volume, momentum) and use only those. Return JSON with exactly these keys:\n"
        "- analysis_types: a list of objects, each with \"type\" and \"what_i_looked_at\" "
        "(list only the analyses you really used)\n"
        "- observations: a list of 3 to 5 strings, each tied to specific numbers above\n"
        "- summary: 2 or 3 sentences\n"
        "- limitations: one sentence on what this analysis cannot tell us\n"
        "Rules: use only the numbers given, do not invent anything, describe what the data shows, "
        "and never tell anyone to buy, sell or invest."
    )
    for attempt in range(2):
        text = ask_groq(prompt)
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            a = json.loads(text)
            ok = (isinstance(a.get("analysis_types"), list) and a["analysis_types"]
                  and all("type" in t and "what_i_looked_at" in t for t in a["analysis_types"])
                  and isinstance(a.get("observations"), list) and a["observations"]
                  and isinstance(a.get("summary"), str) and isinstance(a.get("limitations"), str))
        except (json.JSONDecodeError, AttributeError, TypeError):
            ok = False
        if ok and ADVICE.search(json.dumps(a)):
            print("The AI used advice words, trying again")
            ok = False
        if ok:
            return a
        print("The answer was not valid, trying again")
    raise SystemExit("The AI did not return a valid analysis")
 
 
# ---------- 3. Write the report ----------
def build_report(facts, analysis):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Bitcoin 30-day AI analysis",
        "",
        f"**Data:** Kraken, {PAIR}, daily candles up to {facts['data_to']}",
        f"**Report created:** {now}",
        f"**AI model:** {MODEL}",
        "",
        "## Numbers (calculated by code)",
        "",
        "| Measure | Value |",
        "|---|---|",
    ]
    for k, v in facts.items():
        lines.append(f"| {k.replace('_', ' ')} | {v} |")
    lines += ["", "## Types of analysis the AI used", ""]
    for t in analysis["analysis_types"]:
        lines.append(f"- **{t['type']}**: {t['what_i_looked_at']}")
    lines += ["", "## Observations", ""]
    lines += [f"- {o}" for o in analysis["observations"]]
    lines += ["", "## Summary", "", analysis["summary"],
              "", "## Limitations", "", analysis["limitations"], "",
              "This report is written by an AI from past data. It is for education only and is not financial advice."]
    return "\n".join(lines)
 
 
def save_report(text):
    Path("reports").mkdir(exist_ok=True)
    name = "ai_report_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + ".md"
    path = Path("reports") / name
    path.write_text(text, encoding="utf-8")
    # On GitHub, this also shows the report on the page of the run
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(text)
    return path
 
 
# ---------- Run ----------
if __name__ == "__main__":
    facts, table = get_facts()
    print(facts)
    analysis = get_analysis(facts, table)
    print("\nTYPES OF ANALYSIS THE AI USED:")
    for t in analysis["analysis_types"]:
        print("-", t["type"] + ":", t["what_i_looked_at"])
    print("\nSUMMARY:", analysis["summary"])
    print("\nReport written to", save_report(build_report(facts, analysis)))
