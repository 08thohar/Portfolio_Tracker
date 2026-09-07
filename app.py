
import os, json, sqlite3
from datetime import datetime, timezone
import pandas as pd
import streamlit as st
import yfinance as yf
from openai import OpenAI

DB_PATH = "portfolio.db"
PORTFOLIO_PATH = "portfolio.json"

st.set_page_config(page_title="AI Portfolio Intelligence", layout="wide")
st.title("AI Portfolio Intelligence")
st.caption("Market data, earnings, financials, analyst views, news and AI-assisted change detection.")

def load_tickers():
    with open(PORTFOLIO_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["tickers"]

def db():
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "CREATE TABLE IF NOT EXISTS snapshots("
        "captured_at TEXT,ticker TEXT,price REAL,market_cap REAL,trailing_pe REAL,forward_pe REAL,"
        "target_mean REAL,target_low REAL,target_high REAL,recommendation_mean REAL,revenue_growth REAL,"
        "earnings_growth REAL,profit_margin REAL,PRIMARY KEY(captured_at,ticker))"
    )
    return con

def safe_num(x):
    try:
        return float(x) if x is not None else None
    except Exception:
        return None

@st.cache_data(ttl=900)
def fetch_company(ticker):
    t = yf.Ticker(ticker)
    try: info = t.get_info()
    except Exception: info = {}
    try: fast = dict(t.fast_info)
    except Exception: fast = {}
    try: targets = t.get_analyst_price_targets() or {}
    except Exception: targets = {}
    try: recs = t.get_recommendations_summary()
    except Exception: recs = pd.DataFrame()
    try: earnings = t.get_earnings_dates(limit=8)
    except Exception: earnings = pd.DataFrame()
    try: q_income = t.get_income_stmt(freq="quarterly", pretty=True)
    except Exception: q_income = pd.DataFrame()
    try: q_cash = t.get_cashflow(freq="quarterly", pretty=True)
    except Exception: q_cash = pd.DataFrame()
    try: q_balance = t.get_balance_sheet(freq="quarterly", pretty=True)
    except Exception: q_balance = pd.DataFrame()
    try: news = t.get_news(count=12, tab="news")
    except Exception: news = []
    try: upgrades = t.get_upgrades_downgrades()
    except Exception: upgrades = pd.DataFrame()
    try: eps_rev = t.get_eps_revisions()
    except Exception: eps_rev = pd.DataFrame()

    return {
        "ticker": ticker,
        "name": info.get("shortName") or info.get("longName") or ticker,
        "sector": info.get("sector", "N/A"),
        "industry": info.get("industry", "N/A"),
        "price": safe_num(fast.get("lastPrice") or info.get("currentPrice")),
        "currency": info.get("currency", "USD"),
        "market_cap": safe_num(info.get("marketCap") or fast.get("marketCap")),
        "trailing_pe": safe_num(info.get("trailingPE")),
        "forward_pe": safe_num(info.get("forwardPE")),
        "revenue_growth": safe_num(info.get("revenueGrowth")),
        "earnings_growth": safe_num(info.get("earningsGrowth")),
        "profit_margin": safe_num(info.get("profitMargins")),
        "recommendation_mean": safe_num(info.get("recommendationMean")),
        "recommendation_key": info.get("recommendationKey"),
        "targets": targets,
        "recs": recs,
        "earnings": earnings,
        "income": q_income,
        "cashflow": q_cash,
        "balance": q_balance,
        "news": news,
        "upgrades": upgrades,
        "eps_revisions": eps_rev,
    }

@st.cache_data(ttl=900)
def fetch_prices(tickers, period="1y"):
    try:
        d = yf.download(list(tickers), period=period, auto_adjust=True, progress=False, group_by="column")
        if isinstance(d.columns, pd.MultiIndex):
            close = d["Close"]
        else:
            close = d[["Close"]].rename(columns={"Close": tickers[0]})
        return close.dropna(how="all")
    except Exception:
        return pd.DataFrame()

def fmt_money(x):
    if x is None: return "N/A"
    if abs(x) >= 1e12: return f"${x/1e12:.2f}T"
    if abs(x) >= 1e9: return f"${x/1e9:.2f}B"
    if abs(x) >= 1e6: return f"${x/1e6:.2f}M"
    return f"${x:,.0f}"

def fmt_pct(x):
    return "N/A" if x is None else f"{x*100:.1f}%"

def headline_fields(item):
    c = item.get("content", item) if isinstance(item, dict) else {}
    title = c.get("title") or (item.get("title", "") if isinstance(item, dict) else "")
    summary = c.get("summary") or c.get("description") or ""
    pub = c.get("pubDate") or c.get("providerPublishTime")
    url = ""
    if isinstance(c.get("canonicalUrl"), dict):
        url = c["canonicalUrl"].get("url","")
    if not url and isinstance(c.get("clickThroughUrl"), dict):
        url = c["clickThroughUrl"].get("url","")
    return title, summary, pub, url

def latest_snapshot(ticker):
    con = db()
    row = con.execute(
        "SELECT captured_at,price,market_cap,trailing_pe,forward_pe,target_mean,"
        "recommendation_mean,revenue_growth,earnings_growth,profit_margin "
        "FROM snapshots WHERE ticker=? ORDER BY captured_at DESC LIMIT 1", (ticker,)
    ).fetchone()
    con.close()
    if not row: return None
    keys = ["captured_at","price","market_cap","trailing_pe","forward_pe","target_mean",
            "recommendation_mean","revenue_growth","earnings_growth","profit_margin"]
    return dict(zip(keys,row))

def save_snapshot(company):
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    tg = company["targets"] if isinstance(company["targets"], dict) else {}
    con = db()
    con.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        now, company["ticker"], company["price"], company["market_cap"], company["trailing_pe"],
        company["forward_pe"], safe_num(tg.get("mean")), safe_num(tg.get("low")),
        safe_num(tg.get("high")), company["recommendation_mean"], company["revenue_growth"],
        company["earnings_growth"], company["profit_margin"]
    ))
    con.commit(); con.close()

def ai_brief(company, previous):
    if not os.getenv("OPENAI_API_KEY"):
        return None
    headlines = []
    for n in company["news"][:8]:
        title, summary, pub, url = headline_fields(n)
        if title:
            headlines.append({"title": title, "summary": summary[:400], "published": str(pub), "url": url})
    earnings_txt = ""
    if isinstance(company["earnings"], pd.DataFrame) and not company["earnings"].empty:
        earnings_txt = company["earnings"].head(5).reset_index().to_string(index=False)
    upgrades_txt = ""
    if isinstance(company["upgrades"], pd.DataFrame) and not company["upgrades"].empty:
        upgrades_txt = company["upgrades"].head(8).reset_index().to_string(index=False)

    payload = {
        "ticker": company["ticker"], "name": company["name"], "price": company["price"],
        "forward_pe": company["forward_pe"], "revenue_growth": company["revenue_growth"],
        "earnings_growth": company["earnings_growth"], "profit_margin": company["profit_margin"],
        "analyst_targets": company["targets"], "recommendation_mean": company["recommendation_mean"],
        "recommendation_key": company["recommendation_key"], "previous_snapshot": previous,
        "recent_earnings": earnings_txt, "recent_rating_changes": upgrades_txt, "headlines": headlines,
    }
    prompt = f"""
You are an equity-research monitoring assistant. Analyse ONLY the supplied data.

DATA:
{json.dumps(payload, default=str)}

Produce concise markdown with exactly these headings:
### What changed
### Earnings & fundamentals
### Analyst view
### News that matters
### Watch next
### AI signal

For AI signal choose one of: Positive / Mixed-positive / Mixed / Mixed-negative / Negative / Insufficient data.

Rules:
- Never invent facts or dates.
- Distinguish reported facts from inference.
- Do not give personalised investment advice.
- If evidence conflicts, say so.
- For news, use only supplied headline/summary text.
"""
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    r = client.responses.create(model=os.getenv("OPENAI_MODEL","gpt-5.6-luna"), input=prompt)
    return r.output_text

tickers = load_tickers()
prices = fetch_prices(tuple(tickers), "1y")

with st.sidebar:
    st.header("Portfolio")
    selected = st.selectbox("Company", tickers)
    if st.button("Refresh online data"):
        fetch_company.clear(); fetch_prices.clear(); st.rerun()
    st.caption("Online data cache: 15 minutes.")
    st.caption("Set OPENAI_API_KEY to enable AI briefs.")

st.subheader("Portfolio overview")
if not prices.empty:
    norm = prices / prices.ffill().iloc[0] * 100
    st.line_chart(norm)
    perf = []
    for t in tickers:
        if t in prices.columns and prices[t].dropna().shape[0] > 1:
            s = prices[t].dropna()
            perf.append([t, s.iloc[-1], (s.iloc[-1]/s.iloc[0]-1)*100])
    if perf:
        st.dataframe(pd.DataFrame(perf, columns=["Ticker","Last price","1Y return %"]).sort_values("1Y return %", ascending=False),
                     hide_index=True, use_container_width=True)

company = fetch_company(selected)
previous = latest_snapshot(selected)

st.markdown("---")
st.header(f"{selected} — {company['name']}")
c1,c2,c3,c4,c5 = st.columns(5)
c1.metric("Price", f"{company['currency']} {company['price']:.2f}" if company["price"] else "N/A")
c2.metric("Market cap", fmt_money(company["market_cap"]))
c3.metric("Forward P/E", f"{company['forward_pe']:.1f}" if company["forward_pe"] else "N/A")
c4.metric("Revenue growth", fmt_pct(company["revenue_growth"]))
c5.metric("Profit margin", fmt_pct(company["profit_margin"]))

tg = company["targets"] if isinstance(company["targets"], dict) else {}
a1,a2,a3,a4 = st.columns(4)
a1.metric("Analyst target mean", tg.get("mean","N/A"))
a2.metric("Target low", tg.get("low","N/A"))
a3.metric("Target high", tg.get("high","N/A"))
a4.metric("Consensus", company["recommendation_key"] or "N/A")

tabs = st.tabs(["AI Brief","Earnings","Quarterly Financials","Analysts","News","History"])

with tabs[0]:
    if previous: st.caption(f"Previous stored snapshot: {previous['captured_at']}")
    else: st.caption("No previous snapshot yet.")
    if st.button("Generate AI company brief"):
        try:
            brief = ai_brief(company, previous)
            if brief: st.markdown(brief)
            else: st.info("Set OPENAI_API_KEY first.")
        except Exception as e:
            st.error(f"AI brief failed: {e}")
    if st.button("Save current snapshot"):
        save_snapshot(company)
        st.success("Snapshot saved.")

with tabs[1]:
    if isinstance(company["earnings"], pd.DataFrame) and not company["earnings"].empty:
        st.dataframe(company["earnings"].reset_index(), hide_index=True, use_container_width=True)
    else: st.info("No earnings data returned.")

with tabs[2]:
    for label, df in [("Income statement", company["income"]),("Cash flow", company["cashflow"]),("Balance sheet", company["balance"])]:
        st.subheader(label)
        if isinstance(df, pd.DataFrame) and not df.empty: st.dataframe(df, use_container_width=True)
        else: st.caption("No data returned.")

with tabs[3]:
    st.subheader("Recommendation summary")
    if isinstance(company["recs"], pd.DataFrame) and not company["recs"].empty:
        st.dataframe(company["recs"].reset_index(), hide_index=True, use_container_width=True)
    st.subheader("Recent upgrades / downgrades")
    if isinstance(company["upgrades"], pd.DataFrame) and not company["upgrades"].empty:
        st.dataframe(company["upgrades"].head(20).reset_index(), hide_index=True, use_container_width=True)
    st.subheader("EPS revisions")
    if isinstance(company["eps_revisions"], pd.DataFrame) and not company["eps_revisions"].empty:
        st.dataframe(company["eps_revisions"].reset_index(), hide_index=True, use_container_width=True)

with tabs[4]:
    if company["news"]:
        for n in company["news"][:12]:
            title, summary, pub, url = headline_fields(n)
            if not title: continue
            st.markdown(f"**[{title}]({url})**" if url else f"**{title}**")
            if pub: st.caption(str(pub))
            if summary: st.write(summary)
            st.markdown("---")
    else: st.info("No recent news returned.")

with tabs[5]:
    con = db()
    hist = pd.read_sql_query("SELECT * FROM snapshots WHERE ticker=? ORDER BY captured_at", con, params=(selected,))
    con.close()
    if hist.empty: st.info("No snapshots saved yet.")
    else:
        st.dataframe(hist, hide_index=True, use_container_width=True)
        if hist["price"].notna().sum() > 1:
            st.line_chart(hist.set_index("captured_at")[["price"]])

st.caption("Research/educational tool only. Verify material facts against primary company filings.")
