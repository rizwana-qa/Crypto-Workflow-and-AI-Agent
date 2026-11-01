
import os
import re
import json
from datetime import datetime, timezone
from pathlib import Path
import requests

# These come from the template. They do the data work, not the AI.
from crypto_workflow import fetch_candles, calc_metrics, apply_rules, WINDOW, HIGH_VOL, BAND

# ---------- Settings ----------

PAIR = "XBTUSD"  # Kraken calls Bitcoin XBT
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "openai/gpt-oss-20b"

# Words that sound like advice. If the AI uses them, we reject the answer.
ADVICE = re.compile(
    r"\b(buy|buying|sell(?!-?off)|selling|invest in|should invest|go long|go short|accumulate)\b",
    re.IGNORECASE,
)


# ---------- 1. Numbers (your code, not the AI) ----------

def get_facts():

    candles = fetch_candles(PAIR)[-WINDOW:]

    if len(candles) < WINDOW:
        raise SystemExit(
            f"Insufficient candle data: expected {WINDOW}, received {len(candles)}"
        )

    facts = calc_metrics(candles)
    facts.update(apply_rules(facts))

    # Additional calculated numbers

    closes = [c["close"] for c in candles]

    returns = [
        (closes[i] / closes[i - 1] - 1) * 100
        for i in range(1, len(closes))
    ]

    best = max(range(len(returns)), key=lambda i: returns[i])
    worst = min(range(len(returns)), key=lambda i: returns[i])

    day = lambda c: datetime.fromtimestamp(
        c["time"], timezone.utc
    ).strftime("%Y-%m-%d")

    volumes = [c["volume"] for c in candles]

    earlier_average = sum(volumes[:-7]) / (len(volumes) - 7)

    volume_change = (
        round((sum(volumes[-7:]) / 7) / earlier_average * 100 - 100, 1)
        if earlier_average != 0 else None
    )

    facts.update({

        "highest_price": round(max(c["high"] for c in candles), 2),

        "lowest_price": round(min(c["low"] for c in candles), 2),

        "best_day": (
            f"{day(candles[best + 1])} "
            f"({round(returns[best], 2)}%)"
        ),

        "worst_day": (
            f"{day(candles[worst + 1])} "
            f"({round(returns[worst], 2)}%)"
        ),

        "volume_last_7_days_vs_earlier_pct": volume_change,

        "rules_used": (
            f"volatility is high above {HIGH_VOL}% daily; "
            f"price is well above or below its average when "
            f"more than {BAND}% away"
        ),

    })

    table = "\n".join(
        f"{day(c)}: close {round(c['close'], 2)}"
        for c in candles
    )

    return facts, table


# ---------- 2. Ask the AI to analyse ----------

def ask_groq(prompt):

    r = requests.post(

        GROQ_URL,

        headers={
            "Authorization": "Bearer " + os.environ["GROQ_API_KEY"]
        },

        json={
            "model": MODEL,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": "Reply with JSON only. No extra text."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        },

        timeout=60,

    )

    if r.status_code != 200:
        raise SystemExit("Groq error: " + r.text)

    return r.json()["choices"][0]["message"]["content"].strip()


# ---------- 3. AI Analysis ----------

def get_analysis(facts, table):

    prompt = (

        f"You are a careful market data analyst. Here are numbers for Bitcoin ({PAIR}), "
        f"the last {WINDOW} finished daily candles.\n\n"

        f"Numbers calculated by code:\n{json.dumps(facts, indent=2)}\n\n"

        f"Daily closes:\n{table}\n\n"

        "Decide which kinds of analysis are useful here, for example trend, volatility, "
        "drawdown, volume and momentum.\n\n"

        "In addition, select exactly 5 further useful and distinct AI analysis "
        "perspectives of your choice. These must be different from the standard "
        "analysis types and must be relevant to the supplied data. "
        "Do not duplicate analysis types. Only include analyses that can genuinely "
        "be performed using the available numbers.\n\n"

        "Return JSON with exactly these keys:\n"

        "- analysis_types: a list of objects, each with 'type' and "
        "'what_i_looked_at'. Include useful standard analyses and exactly "
        "5 additional distinct analyses.\n"

        "- observations: a list of 8 to 10 strings, each tied to specific "
        "numbers supplied above.\n"

        "- summary: 5 to 7 sentences.\n"

        "- limitations: one sentence explaining what this analysis cannot tell us.\n\n"

        "Rules:\n"

        "1. Use only the numbers given.\n"
        "2. Do not invent data, figures, trends or conclusions.\n"
        "3. Every observation must be supported by specific supplied numbers.\n"
        "4. Do not claim an analysis was performed unless the supplied data supports it.\n"
        "5. Do not repeat the same observation using different wording.\n"
        "6. Never tell anyone to buy, sell or invest.\n"
        "7. Return valid JSON only, without Markdown formatting.\n"

    )

    for attempt in range(2):

        text = ask_groq(prompt)

        text = (
            text.removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )

        try:

            a = json.loads(text)

            analysis_types = a.get("analysis_types")
            observations = a.get("observations")
            summary = a.get("summary")
            limitations = a.get("limitations")

            # Validate analysis types

            valid_types = (
                isinstance(analysis_types, list)
                and len(analysis_types) >= 6
                and all(
                    isinstance(t, dict)
                    and isinstance(t.get("type"), str)
                    and bool(t["type"].strip())
                    and isinstance(t.get("what_i_looked_at"), (str, list))
                    and bool(t["what_i_looked_at"])
                    for t in analysis_types
                )
            )

            # Validate distinct analysis names

            unique_types = (
                len({
                    t["type"].strip().casefold()
                    for t in analysis_types
                }) == len(analysis_types)
                if valid_types else False
            )

            # Validate observations

            valid_observations = (
                isinstance(observations, list)
                and 8 <= len(observations) <= 10
                and all(
                    isinstance(o, str) and bool(o.strip())
                    for o in observations
                )
            )

            # Validate summary sentence count

            sentence_count = (
                len(re.findall(r"[.!?](?:\s|$)", summary))
                if isinstance(summary, str) else 0
            )

            valid_summary = (
                isinstance(summary, str)
                and 5 <= sentence_count <= 7
            )

            # Validate limitations

            valid_limitations = (
                isinstance(limitations, str)
                and bool(limitations.strip())
                and len(re.findall(r"[.!?](?:\s|$)", limitations)) == 1
            )

            # Validate exact JSON keys

            valid_keys = (
                isinstance(a, dict)
                and set(a.keys()) == {
                    "analysis_types",
                    "observations",
                    "summary",
                    "limitations"
                }
            )

            ok = (
                valid_keys
                and valid_types
                and unique_types
                and valid_observations
                and valid_summary
                and valid_limitations
            )

        except (json.JSONDecodeError, AttributeError, TypeError):

            ok = False

        # Reject financial advice language

        if ok and ADVICE.search(json.dumps(a)):

            print("The AI used advice words, trying again")
            ok = False

        if ok:

            return a

        print("The answer was not valid, trying again")

    raise SystemExit("The AI did not return a valid analysis")


# ---------- 4. Write the report ----------

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

    lines += [
        "",
        "## Types of analysis the AI used",
        ""
    ]

    for t in analysis["analysis_types"]:

        lines.append(
            f"- **{t['type']}**: {t['what_i_looked_at']}"
        )

    lines += [
        "",
        "## Observations",
        ""
    ]

    lines += [
        f"- {o}"
        for o in analysis["observations"]
    ]

    lines += [
        "",
        "## Summary",
        "",
        analysis["summary"],
        "",
        "## Limitations",
        "",
        analysis["limitations"],
        "",
        "This report is written by an AI from past data. "
        "It is for education only and is not financial advice."
    ]

    return "\n".join(lines)


# ---------- 5. Save the report ----------

def save_report(text):

    Path("reports").mkdir(exist_ok=True)

    name = (
        "ai_report_"
        + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        + ".md"
    )

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

    print("\nOBSERVATIONS:")

    for observation in analysis["observations"]:

        print("-", observation)

    print("\nSUMMARY:", analysis["summary"])

    print("\nLIMITATIONS:", analysis["limitations"])

    print(
        "\nReport written to",
        save_report(build_report(facts, analysis))
    )
