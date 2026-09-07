
import os, json, sqlite3, requests
from datetime import datetime, timezone
import pandas as pd
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="AI Portfolio Intelligence", layout="wide")
st.title("AI Portfolio Intelligence")
st.caption("Market data, earnings, financials, analyst views, news and SEC-backed fallbacks.")

DB_PATH = "portfolio.db"
SEC_HEADERS = {"User-Agent": "Portfolio Intelligence personal research app contact@example.com"}

def load_tickers():
    with open("portfolio.json","r",encoding="utf-8") as f:
        return json.load(f)["tickers"]

def safe_num(x):
    try:
        return float(x) if x is not None else None
    except Exception:
        return None

def db():
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "CREATE TABLE IF NOT EXISTS snapshots("
        "captured_at TEXT,ticker TEXT,price REAL,market_cap REAL,trailing_pe REAL,forward_pe REAL,"
        "target_mean REAL,target_low REAL,target_high REAL,recommendation_mean REAL,revenue_growth REAL,"
        "earnings_growth REAL,profit_margin REAL,PRIMARY KEY(captured_at,ticker))"
    )
    return con

@st.cache_data(ttl=900)
def fetch_company(ticker):
    t = yf.Ticker(ticker)
    info = {}
    try: info = t.get_info()
    except Exception: pass
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
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "price": safe_num(fast.get("lastPrice") or info.get("currentPrice")),
        "currency": info.get("currency","USD"),
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
            return d["Close"].dropna(how="all")
        return d[["Close"]].rename(columns={"Close":tickers[0]}).dropna(how="all")
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=21600)
def sec_ticker_map():
    try:
        r=requests.get("https://www.sec.gov/files/company_tickers.json",headers=SEC_HEADERS,timeout=20)
        r.raise_for_status()
        data=r.json()
        return {v["ticker"].upper():str(v["cik_str"]).zfill(10) for v in data.values()}
    except Exception:
        return {}

@st.cache_data(ttl=21600)
def sec_companyfacts(ticker):
    cik=sec_ticker_map().get(ticker.upper())
    if not cik:
        return {"available":False}
    try:
        r=requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",headers=SEC_HEADERS,timeout=20)
        r.raise_for_status()
        return {"available":True,"cik":cik,"data":r.json()}
    except Exception as e:
        return {"available":False,"error":str(e)}

def fact_units(sec, candidates):
    if not sec.get("available"): return None
    facts=sec["data"].get("facts",{}).get("us-gaap",{})
    for tag in candidates:
        obj=facts.get(tag)
        if not obj: continue
        units=obj.get("units",{})
        for unit in ("USD","shares","USD/shares"):
            if unit in units:
                return units[unit]
    return None

def latest_value(units):
    if not units: return None
    vals=[]
    for x in units:
        val=safe_num(x.get("val"))
        if val is None: continue
        vals.append((x.get("end",""),x.get("filed",""),x.get("form",""),x.get("fp",""),val))
    vals.sort(reverse=True)
    for v in vals:
        if v[2] in ("10-K","20-F") and v[3]=="FY":
            return v[4]
    return vals[0][4] if vals else None

def recent_facts(units, n=8):
    if not units: return []
    vals=[]; seen=set()
    for x in units:
        val=safe_num(x.get("val"))
        end=x.get("end"); form=x.get("form"); fp=x.get("fp")
        if val is None or not end or form not in ("10-Q","10-K","20-F","6-K"): continue
        key=(end,val,form,fp)
        if key in seen: continue
        seen.add(key)
        vals.append((end,val,fp,form))
    vals.sort(reverse=True)
    return vals[:n]

def sec_metrics(ticker):
    sec=sec_companyfacts(ticker)
    if not sec.get("available"):
        return {"available":False,"error":sec.get("error")}
    revenue_units=fact_units(sec,["RevenueFromContractWithCustomerExcludingAssessedTax","Revenues","SalesRevenueNet"])
    ni_units=fact_units(sec,["NetIncomeLoss","ProfitLoss"])
    revenue=latest_value(revenue_units)
    net_income=latest_value(ni_units)
    margin=(net_income/revenue) if revenue not in (None,0) and net_income is not None else None
    return {
        "available":True,
        "revenue":revenue,
        "net_income":net_income,
        "profit_margin":margin,
        "revenue_facts":recent_facts(revenue_units),
        "net_income_facts":recent_facts(ni_units),
    }

@st.cache_data(ttl=1800)
def sec_filings(ticker):
    cik=sec_ticker_map().get(ticker.upper())
    if not cik: return []
    try:
        r=requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json",headers=SEC_HEADERS,timeout=20)
        r.raise_for_status()
        recent=r.json().get("filings",{}).get("recent",{})
        rows=[]
        for i,form in enumerate(recent.get("form",[])):
            if form in ("10-K","10-Q","8-K","20-F","6-K"):
                acc=recent["accessionNumber"][i]
                primary=recent["primaryDocument"][i]
                url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-','')}/{primary}"
                rows.append({"Form":form,"Filed":recent["filingDate"][i],"Report date":recent["reportDate"][i],"URL":url})
            if len(rows)>=15: break
        return rows
    except Exception:
        return []

def fmt_money(x):
    if x is None: return "N/A"
    if abs(x)>=1e12: return f"${x/1e12:.2f}T"
    if abs(x)>=1e9: return f"${x/1e9:.2f}B"
    if abs(x)>=1e6: return f"${x/1e6:.2f}M"
    return f"${x:,.0f}"

def fmt_pct(x):
    return "N/A" if x is None else f"{x*100:.1f}%"

def headline_fields(item):
    c = item.get("content", item) if isinstance(item, dict) else {}
    title = c.get("title") or (item.get("title","") if isinstance(item,dict) else "")
    summary = c.get("summary") or c.get("description") or ""
    pub = c.get("pubDate") or c.get("providerPublishTime")
    url=""
    if isinstance(c.get("canonicalUrl"),dict): url=c["canonicalUrl"].get("url","")
    if not url and isinstance(c.get("clickThroughUrl"),dict): url=c["clickThroughUrl"].get("url","")
    return title,summary,pub,url

def save_snapshot(company, profit_margin):
    now=datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    tg=company["targets"] if isinstance(company["targets"],dict) else {}
    con=db()
    con.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(
        now,company["ticker"],company["price"],company["market_cap"],company["trailing_pe"],
        company["forward_pe"],safe_num(tg.get("mean")),safe_num(tg.get("low")),safe_num(tg.get("high")),
        company["recommendation_mean"],company["revenue_growth"],company["earnings_growth"],profit_margin
    ))
    con.commit(); con.close()

tickers=load_tickers()
prices=fetch_prices(tuple(tickers),"1y")

with st.sidebar:
    st.header("Portfolio")
    selected=st.selectbox("Company",tickers)
    if st.button("Refresh online data"):
        st.cache_data.clear(); st.rerun()
    st.caption("Yahoo data is used first; SEC is used as a free fallback for missing fundamentals.")

company=fetch_company(selected)
sec=sec_metrics(selected)
filings=sec_filings(selected)

profit_margin=company["profit_margin"]
profit_source="Yahoo Finance / yfinance"
if profit_margin is None and sec.get("profit_margin") is not None:
    profit_margin=sec["profit_margin"]
    profit_source="SEC company facts"

st.subheader("Portfolio overview")
if not prices.empty:
    norm=prices/prices.ffill().iloc[0]*100
    st.line_chart(norm)
    perf=[]
    for t in tickers:
        if t in prices.columns and prices[t].dropna().shape[0]>1:
            s=prices[t].dropna()
            perf.append([t,s.iloc[-1],(s.iloc[-1]/s.iloc[0]-1)*100])
    if perf:
        st.dataframe(pd.DataFrame(perf,columns=["Ticker","Last price","1Y return %"]).sort_values("1Y return %",ascending=False),
                     hide_index=True,use_container_width=True)

st.markdown("---")
st.header(f"{selected} — {company['name']}")

c1,c2,c3,c4,c5=st.columns(5)
c1.metric("Price",f"{company['currency']} {company['price']:.2f}" if company["price"] else "N/A")
c2.metric("Market cap",fmt_money(company["market_cap"]))
c3.metric("Forward P/E",f"{company['forward_pe']:.1f}" if company["forward_pe"] else "N/A")
c4.metric("Revenue growth",fmt_pct(company["revenue_growth"]))
c5.metric("Net profit margin",fmt_pct(profit_margin))
st.caption(f"Price source: Yahoo Finance / yfinance · Net margin source: {profit_source}")

tabs=st.tabs(["AI Brief","Earnings","Quarterly Financials","Analysts","News","SEC Fundamentals","SEC Filings","History","Data Health"])

with tabs[0]:
    st.info("AI brief is currently disabled until you choose to connect an AI API.")

with tabs[1]:
    if isinstance(company["earnings"],pd.DataFrame) and not company["earnings"].empty:
        st.dataframe(company["earnings"].reset_index(),hide_index=True,use_container_width=True)
    else:
        st.info("Yahoo did not return earnings history for this ticker.")

with tabs[2]:
    for label,df in [("Income statement",company["income"]),("Cash flow",company["cashflow"]),("Balance sheet",company["balance"])]:
        st.subheader(label)
        if isinstance(df,pd.DataFrame) and not df.empty:
            st.dataframe(df,use_container_width=True)
        else:
            st.caption("Yahoo did not return this statement.")

with tabs[3]:
    any_analyst=False
    tg=company["targets"] if isinstance(company["targets"],dict) else {}
    if tg:
        any_analyst=True
        st.subheader("Price targets")
        cols=st.columns(4)
        cols[0].metric("Current",tg.get("current","N/A"))
        cols[1].metric("Mean",tg.get("mean","N/A"))
        cols[2].metric("Low",tg.get("low","N/A"))
        cols[3].metric("High",tg.get("high","N/A"))

    if company["recommendation_key"] or company["recommendation_mean"] is not None:
        any_analyst=True
        st.subheader("Consensus")
        st.write(f"Recommendation: **{company['recommendation_key'] or 'N/A'}**")
        if company["recommendation_mean"] is not None:
            st.write(f"Recommendation mean: **{company['recommendation_mean']:.2f}**")

    if isinstance(company["recs"],pd.DataFrame) and not company["recs"].empty:
        any_analyst=True
        st.subheader("Recommendation summary")
        st.dataframe(company["recs"].reset_index(),hide_index=True,use_container_width=True)

    if isinstance(company["upgrades"],pd.DataFrame) and not company["upgrades"].empty:
        any_analyst=True
        st.subheader("Recent upgrades / downgrades")
        st.dataframe(company["upgrades"].head(20).reset_index(),hide_index=True,use_container_width=True)

    if isinstance(company["eps_revisions"],pd.DataFrame) and not company["eps_revisions"].empty:
        any_analyst=True
        st.subheader("EPS revisions")
        st.dataframe(company["eps_revisions"].reset_index(),hide_index=True,use_container_width=True)

    if not any_analyst:
        st.info("Yahoo did not return analyst data for this ticker. Other tickers may still have analyst coverage.")

with tabs[4]:
    if company["news"]:
        for n in company["news"][:12]:
            title,summary,pub,url=headline_fields(n)
            if not title: continue
            st.markdown(f"**[{title}]({url})**" if url else f"**{title}**")
            if pub: st.caption(str(pub))
            if summary: st.write(summary)
            st.markdown("---")
    else:
        st.info("Yahoo did not return recent news for this ticker.")

with tabs[5]:
    if sec.get("available"):
        a,b,c=st.columns(3)
        a.metric("Latest annual revenue",fmt_money(sec.get("revenue")))
        b.metric("Latest annual net income",fmt_money(sec.get("net_income")))
        c.metric("SEC-derived net margin",fmt_pct(sec.get("profit_margin")))
        if sec.get("revenue_facts"):
            st.subheader("Recent revenue facts")
            st.dataframe(pd.DataFrame(sec["revenue_facts"],columns=["Period end","Value","Fiscal period","Form"]),
                         hide_index=True,use_container_width=True)
        if sec.get("net_income_facts"):
            st.subheader("Recent net-income facts")
            st.dataframe(pd.DataFrame(sec["net_income_facts"],columns=["Period end","Value","Fiscal period","Form"]),
                         hide_index=True,use_container_width=True)
    else:
        st.info("SEC company facts unavailable for this ticker.")

with tabs[6]:
    if filings:
        for row in filings:
            st.markdown(f"**{row['Form']}** — filed {row['Filed']} · report date {row['Report date']} · [Open SEC filing]({row['URL']})")
    else:
        st.info("No SEC filing feed found for this ticker.")

with tabs[7]:
    con=db()
    hist=pd.read_sql_query("SELECT * FROM snapshots WHERE ticker=? ORDER BY captured_at",con,params=(selected,))
    con.close()
    if hist.empty:
        st.info("No saved snapshots yet.")
    else:
        st.dataframe(hist,hide_index=True,use_container_width=True)
    if st.button("Save current snapshot"):
        save_snapshot(company,profit_margin)
        st.success("Snapshot saved.")

with tabs[8]:
    rows=[
        ["Yahoo price/profile","Available" if company["price"] is not None else "Partial","Price, market cap, valuation, analyst data, news"],
        ["Yahoo analyst data","Available" if (
            bool(company["targets"]) or
            (isinstance(company["recs"],pd.DataFrame) and not company["recs"].empty) or
            (isinstance(company["upgrades"],pd.DataFrame) and not company["upgrades"].empty)
        ) else "Unavailable for this ticker","Targets, ratings, revisions"],
        ["SEC company facts","Available" if sec.get("available") else "Unavailable","Revenue, net income, margin fallback"],
        ["SEC filings","Available" if filings else "Unavailable","10-K, 10-Q, 8-K, 20-F, 6-K links"],
    ]
    st.dataframe(pd.DataFrame(rows,columns=["Source","Status","Purpose"]),hide_index=True,use_container_width=True)

st.caption("Research/educational use only. Free sources can be delayed or incomplete. Verify material facts against primary filings.")
