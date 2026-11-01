# Crypto data workflow + AI agent

**Question:** Which coin was the most volatile over the last 30 days, and is each coin above or below its 30-day average?

This project is for education only and is not financial advice.

## What this repo has

- `crypto_workflow.py`: the data workflow. It gets daily candles from the Kraken public API, calculates metrics, applies two rules, and writes a report to `reports/`. It does not call any AI model.
- `agent.py`: an AI agent built on top of the workflow. It uses the workflow functions as tools and answers questions in plain English.

## What I learned about the data

(Fill in from your own look at https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440)

## How to run

1. Install Python 3 and open this folder in VS Code.
2. Install the package: `pip install -r requirements.txt`
3. Run the workflow: `python3 crypto_workflow.py` (Windows: `python crypto_workflow.py`). A report appears in `reports/`.
4. To use the agent, get a free Groq key and set it for this terminal only:
   - Mac: `export GROQ_API_KEY="your key"`
   - Windows PowerShell: `$env:GROQ_API_KEY="your key"`
5. Ask a question: `python3 agent.py "Which coin was most volatile, and is Bitcoin above its average?"`

Never put your key in a file or push it to GitHub.

## How it works

The workflow fetches 720 daily candles per coin and drops the last one, because it is not finished. It takes the last 30 finished days and calculates the average close, the % distance from that average, daily volatility (standard deviation of daily % returns), and maximum drawdown. Two rules turn the numbers into labels. Then it writes a Markdown report.

The agent adds an AI model on top. The model never calculates anything. It chooses a tool (`get_metrics` or `read_latest_report`), our code runs it, and the model explains the result.

## Rules and thresholds

- **High volatility:** daily volatility above 3.5%. (Explain why you picked this number.)
- **Well above or below average:** more than 5% away from the 30-day average. (Explain why.)

## Agent guardrails

- Only the coins in `PAIRS` can be requested.
- Maximum of 6 steps per question.
- The prompt forbids buy and sell language, and the code also checks every answer and replaces advice with a refusal.
- Every tool call is printed so you can see what the agent did.

## Hand check

(Pick one number, recalculate it in Google Sheets, and write what you found.)

## Sample output

(Paste a sample report here after you run the workflow.)
