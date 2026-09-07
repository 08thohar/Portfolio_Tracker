# AI Portfolio Intelligence Tracker

Configured tickers:
TSLA, MSFT, LLY, PLTR, GOOG, TM, HOOD, RTX, AMZN, IBKR, OPEN, NVDA, BABA, SMCI, META, ORCL

Tracks:
- prices and 1Y relative performance
- quarterly income statement, cash flow and balance sheet
- earnings dates/history
- analyst consensus and price targets
- upgrades/downgrades
- EPS revisions
- recent company news
- SQLite snapshots through time
- AI-generated source-constrained company briefs
- change detection versus previous snapshots

## Run
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Enable AI
PowerShell:
```powershell
$env:OPENAI_API_KEY="your-key"
```

Optional model override:
```powershell
$env:OPENAI_MODEL="gpt-5.6-luna"
```

## Store automatic daily snapshots
```bash
python update_snapshots.py
```

Use Windows Task Scheduler, cron, or the included GitHub Actions workflow to run this automatically.

## CV wording
**AI Portfolio Intelligence Platform | Python, LLMs, APIs, SQLite, Streamlit**

- Developed an automated portfolio-monitoring platform aggregating market data, quarterly financials, earnings, analyst expectations, rating changes and company news across a 16-stock equity portfolio.
- Integrated an LLM research layer to produce source-constrained company briefs and identify material changes in fundamentals, analyst signals and news.
- Built persistent SQLite snapshotting and automated refresh workflows to compare valuation, growth and consensus indicators over time.

## Note
This MVP uses yfinance for research/personal-use data access. For production/commercial use, replace or supplement it with licensed market-data APIs.
