import sys
import time
import statistics
from datetime import datetime, timezone
from pathlib import Path

import requests

# ---------- Settings ----------
API = "https://api.kraken.com/0/public/OHLC"
PAIRS = ["XBTUSD", "ETHUSD", "SOLUSD"]   # Kraken calls Bitcoin XBT
INTERVAL = 1440                           # candle size in minutes (1440 = 1 day)
WINDOW = 30                               # how many days we look at
HIGH_VOL = 3.5                            # daily volatility above this (%) is called "high"
BAND = 5.0                                # price more than this % from its average is "well" above/below

QUESTION = "Which coin was the most volatile over the last 30 days, and is each coin above or below its 30-day average?"


# ---------- 1. Get the data ----------
def fetch_candles(pair, interval=INTERVAL):
    response = requests.get(API, params={"pair": pair, "interval": interval}, timeout=30)
    data = response.json()
    if data["error"]:
        raise SystemExit(f"Kraken error for {pair}: {data['error']}")
    key = next(k for k in data["result"] if k != "last")   # Kraken may rename the pair
    rows = data["result"][key][:-1]                         # drop the last candle: it is not finished yet
    # A candle is [time, open, high, low, close, vwap, volume, count], and the numbers are text
    return [
        {"time": int(c[0]), "open": float(c[1]), "high": float(c[2]),
         "low": float(c[3]), "close": float(c[4]), "volume": float(c[6])}
        for c in rows
    ]


# ---------- 2. Metrics ----------
def calc_metrics(candles, window=WINDOW):
    last = candles[-window:]
    closes = [c["close"] for c in last]
    returns = [(closes[i] / closes[i - 1] - 1) * 100 for i in range(1, len(closes))]

    average = sum(closes) / len(closes)
    latest = closes[-1]

    peak = closes[0]
    max_drawdown = 0.0
    for price in closes:
        peak = max(peak, price)
        max_drawdown = min(max_drawdown, (price / peak - 1) * 100)

    return {
        "latest_close": round(latest, 2),
        "average_close": round(average, 2),
        "vs_average_pct": round((latest / average - 1) * 100, 2),
        "change_pct": round((latest / closes[0] - 1) * 100, 2),
        "volatility_pct": round(statistics.stdev(returns), 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "data_to": datetime.fromtimestamp(last[-1]["time"], timezone.utc).strftime("%Y-%m-%d"),
    }


# ---------- 3. Rules ----------
def apply_rules(m):
    volatility = "high" if m["volatility_pct"] > HIGH_VOL else "normal"
    if m["vs_average_pct"] > BAND:
        position = "well above its average"
    elif m["vs_average_pct"] < -BAND:
        position = "well below its average"
    else:
        position = "close to its average"
    return {"volatility_label": volatility, "position_label": position}


# ---------- 4. Report ----------
def build_report(results):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ranked = sorted(results, key=lambda r: r["volatility_pct"], reverse=True)
    lines = [
        "# Crypto volatility report",
        "",
        f"**Question:** {QUESTION}",
        f"**Data up to:** {ranked[0]['data_to']} (last finished daily candle)",
        f"**Report created:** {now}",
        "",
        "| Pair | Latest close | 30-day average | Vs average | Volatility (daily) | Max drawdown |",
        "|---|---|---|---|---|---|",
    ]
    for r in ranked:
        lines.append(
            f"| {r['pair']} | {r['latest_close']} | {r['average_close']} | {r['vs_average_pct']}% | "
            f"{r['volatility_pct']}% | {r['max_drawdown_pct']}% |"
        )
    lines += ["", "## What the numbers show", ""]
    lines.append(f"- {ranked[0]['pair']} had the highest volatility ({ranked[0]['volatility_pct']}% daily).")
    for r in ranked:
        lines.append(f"- {r['pair']}: volatility is {r['volatility_label']}, and the price is {r['position_label']}.")
    lines += [
        "",
        f"Rules used: volatility is called high above {HIGH_VOL}% daily. "
        f"A price is called well above or below its average when it is more than {BAND}% away.",
        "",
        "These are observations about past data. This project is for education only and is not financial advice.",
    ]
    return "\n".join(lines)


def write_report(text):
    Path("reports").mkdir(exist_ok=True)
    name = "report_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + ".md"
    path = Path("reports") / name
    path.write_text(text, encoding="utf-8")
    return path


# ---------- Run ----------
def main():
    results = []
    for pair in PAIRS:
        candles = fetch_candles(pair)
        m = calc_metrics(candles)
        m.update(apply_rules(m))
        m["pair"] = pair
        results.append(m)
        print(pair, m)
        time.sleep(1)   # be polite to the API
    path = write_report(build_report(results))
    print("Report written to", path)


if __name__ == "__main__":
    main()
