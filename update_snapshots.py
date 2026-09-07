
import json, sqlite3
from datetime import datetime, timezone
import yfinance as yf

DB_PATH = "portfolio.db"
def safe(x):
    try: return float(x) if x is not None else None
    except: return None

with open("portfolio.json","r",encoding="utf-8") as f:
    tickers = json.load(f)["tickers"]

con = sqlite3.connect(DB_PATH)
con.execute("CREATE TABLE IF NOT EXISTS snapshots(captured_at TEXT,ticker TEXT,price REAL,market_cap REAL,trailing_pe REAL,forward_pe REAL,target_mean REAL,target_low REAL,target_high REAL,recommendation_mean REAL,revenue_growth REAL,earnings_growth REAL,profit_margin REAL,PRIMARY KEY(captured_at,ticker))")
now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

for ticker in tickers:
    try:
        t = yf.Ticker(ticker)
        info = t.get_info()
        try: fast = dict(t.fast_info)
        except: fast = {}
        try: tg = t.get_analyst_price_targets() or {}
        except: tg = {}
        row = (now,ticker,safe(fast.get("lastPrice") or info.get("currentPrice")),
               safe(info.get("marketCap") or fast.get("marketCap")),safe(info.get("trailingPE")),
               safe(info.get("forwardPE")),safe(tg.get("mean")),safe(tg.get("low")),safe(tg.get("high")),
               safe(info.get("recommendationMean")),safe(info.get("revenueGrowth")),
               safe(info.get("earningsGrowth")),safe(info.get("profitMargins")))
        con.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
        print("Updated", ticker)
    except Exception as e:
        print("Failed", ticker, e)
con.commit(); con.close()
