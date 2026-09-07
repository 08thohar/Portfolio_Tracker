
import json, requests
import pandas as pd
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="Portfolio Intelligence", layout="wide")
st.title("Portfolio Intelligence")
st.caption("Free-data version with SEC fallback for US-listed companies")

SEC_HEADERS = {
    "User-Agent": "Portfolio Intelligence personal research app contact@example.com"
}

def safe_float(x):
    try:
        if x is None: return None
        return float(x)
    except:
        return None

def load_tickers():
    with open("portfolio.json","r",encoding="utf-8") as f:
        return json.load(f)["tickers"]

@st.cache_data(ttl=900)
def yf_info(ticker):
    out={"source":"Yahoo Finance / yfinance","ok":False}
    try:
        t=yf.Ticker(ticker)
        info=t.get_info()
        fast=dict(t.fast_info)
        out.update({
            "ok":True,
            "name":info.get("shortName") or info.get("longName") or ticker,
            "price":safe_float(fast.get("lastPrice") or info.get("currentPrice")),
            "currency":info.get("currency","USD"),
            "market_cap":safe_float(info.get("marketCap") or fast.get("marketCap")),
            "forward_pe":safe_float(info.get("forwardPE")),
            "trailing_pe":safe_float(info.get("trailingPE")),
            "revenue_growth":safe_float(info.get("revenueGrowth")),
            "profit_margin":safe_float(info.get("profitMargins")),
            "sector":info.get("sector"),
            "industry":info.get("industry"),
        })
    except Exception as e:
        out["error"]=str(e)
    return out

@st.cache_data(ttl=900)
def yf_prices(tickers):
    try:
        d=yf.download(list(tickers),period="1y",auto_adjust=True,progress=False)
        if isinstance(d.columns,pd.MultiIndex):
            return d["Close"].dropna(how="all")
        return d[["Close"]].rename(columns={"Close":tickers[0]}).dropna(how="all")
    except:
        return pd.DataFrame()

@st.cache_data(ttl=21600)
def sec_ticker_map():
    try:
        r=requests.get("https://www.sec.gov/files/company_tickers.json",headers=SEC_HEADERS,timeout=20)
        r.raise_for_status()
        data=r.json()
        return {v["ticker"].upper():str(v["cik_str"]).zfill(10) for v in data.values()}
    except:
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

def latest_annual_or_ttm(units):
    if not units: return None
    vals=[]
    for x in units:
        val=safe_float(x.get("val"))
        if val is None: continue
        form=x.get("form","")
        fy=x.get("fy")
        fp=x.get("fp","")
        end=x.get("end","")
        filed=x.get("filed","")
        frame=x.get("frame","")
        vals.append((end,filed,form,fy,fp,frame,val))
    if not vals: return None
    vals.sort(reverse=True)
    # Prefer recent annual, then any recent filing fact.
    for v in vals:
        if v[2] in ("10-K","20-F") and v[4]=="FY":
            return v[6]
    return vals[0][6]

def recent_quarters(units, n=4):
    if not units: return []
    vals=[]
    seen=set()
    for x in units:
        val=safe_float(x.get("val"))
        end=x.get("end")
        form=x.get("form")
        fp=x.get("fp")
        if val is None or not end: continue
        if form not in ("10-Q","10-K"): continue
        key=(end,val)
        if key in seen: continue
        seen.add(key)
        vals.append((end,val,fp,form))
    vals.sort(reverse=True)
    return vals[:n]

def sec_metrics(ticker):
    sec=sec_companyfacts(ticker)
    if not sec.get("available"):
        return {"available":False,"error":sec.get("error")}
    revenue_units=fact_units(sec,[
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet"
    ])
    ni_units=fact_units(sec,[
        "NetIncomeLoss",
        "ProfitLoss"
    ])
    shares_units=fact_units(sec,[
        "CommonStocksIncludingAdditionalPaidInCapitalMember", # unlikely, fallback ignored if unit mismatch
        "EntityCommonStockSharesOutstanding",
        "CommonStockSharesOutstanding"
    ])
    revenue=latest_annual_or_ttm(revenue_units)
    net_income=latest_annual_or_ttm(ni_units)
    shares=latest_annual_or_ttm(shares_units)
    margin=(net_income/revenue) if revenue not in (None,0) and net_income is not None else None
    return {
        "available":True,
        "revenue":revenue,
        "net_income":net_income,
        "shares":shares,
        "profit_margin":margin,
        "revenue_quarters":recent_quarters(revenue_units,8),
        "net_income_quarters":recent_quarters(ni_units,8),
        "cik":sec["cik"]
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
                rows.append({
                    "Form":form,
                    "Filed":recent["filingDate"][i],
                    "Report date":recent["reportDate"][i],
                    "URL":url
                })
            if len(rows)>=15: break
        return rows
    except:
        return []

def fmt_money(x):
    if x is None:return "N/A"
    if abs(x)>=1e12:return f"${x/1e12:.2f}T"
    if abs(x)>=1e9:return f"${x/1e9:.2f}B"
    if abs(x)>=1e6:return f"${x/1e6:.2f}M"
    return f"${x:,.0f}"

def fmt_pct(x):
    return "N/A" if x is None else f"{x*100:.1f}%"

tickers=load_tickers()
prices=yf_prices(tuple(tickers))

with st.sidebar:
    st.header("Portfolio")
    ticker=st.selectbox("Company",tickers)
    if st.button("Refresh online data"):
        st.cache_data.clear()
        st.rerun()

y=yf_info(ticker)
s=sec_metrics(ticker)
filings=sec_filings(ticker)

name=y.get("name") or ticker
price=y.get("price")
market_cap=y.get("market_cap")

# SEC fallback for market cap if Yahoo market cap missing and SEC shares available
if market_cap is None and price is not None and s.get("shares"):
    market_cap=price*s["shares"]

profit_margin=y.get("profit_margin")
profit_source="Yahoo Finance / yfinance"
if profit_margin is None and s.get("profit_margin") is not None:
    profit_margin=s["profit_margin"]
    profit_source="SEC company facts"

st.subheader("Portfolio overview")
if not prices.empty:
    norm=prices/prices.ffill().iloc[0]*100
    st.line_chart(norm)

st.markdown("---")
st.header(f"{ticker} — {name}")

c1,c2,c3,c4,c5=st.columns(5)
c1.metric("Price",f"{y.get('currency','USD')} {price:.2f}" if price else "N/A")
c2.metric("Market cap",fmt_money(market_cap))
c3.metric("Forward P/E",f"{y['forward_pe']:.1f}" if y.get("forward_pe") else "N/A")
c4.metric("Revenue growth",fmt_pct(y.get("revenue_growth")))
c5.metric("Net profit margin",fmt_pct(profit_margin))

st.caption(f"Price source: Yahoo Finance / yfinance · Net margin source: {profit_source}")

tabs=st.tabs(["Overview","SEC Fundamentals","Analysts","SEC Filings","Data Health"])

with tabs[0]:
    st.write(f"**Sector:** {y.get('sector') or 'N/A'}")
    st.write(f"**Industry:** {y.get('industry') or 'N/A'}")
    if not y.get("ok"):
        st.warning("Yahoo Finance did not return the company profile cleanly. SEC fallback is being used where possible.")

with tabs[1]:
    if s.get("available"):
        a,b=st.columns(2)
        a.metric("Latest annual revenue",fmt_money(s.get("revenue")))
        b.metric("Latest annual net income",fmt_money(s.get("net_income")))
        st.caption("Source: SEC XBRL company facts")
        if s.get("revenue_quarters"):
            st.subheader("Recent reported revenue facts")
            st.dataframe(pd.DataFrame(s["revenue_quarters"],columns=["Period end","Value","Fiscal period","Form"]),
                         hide_index=True,use_container_width=True)
        if s.get("net_income_quarters"):
            st.subheader("Recent reported net-income facts")
            st.dataframe(pd.DataFrame(s["net_income_quarters"],columns=["Period end","Value","Fiscal period","Form"]),
                         hide_index=True,use_container_width=True)
    else:
        st.info("SEC company facts are not available for this ticker.")

with tabs[2]:
    st.info(
        "Reliable current analyst ratings and price targets are not available from the free official sources used by this version. "
        "Rather than show blank or misleading data, this section is intentionally marked unavailable."
    )
    if y.get("forward_pe") is not None:
        st.write(f"Yahoo fallback forward P/E: **{y['forward_pe']:.2f}**")

with tabs[3]:
    if filings:
        for row in filings:
            st.markdown(f"**{row['Form']}** — filed {row['Filed']} · report date {row['Report date']} · [Open SEC filing]({row['URL']})")
    else:
        st.info("No SEC filing feed found for this ticker.")

with tabs[4]:
    rows=[
        ["Yahoo Finance / yfinance","OK" if y.get("ok") else "Partial/failed","Price, profile, valuation fallback"],
        ["SEC EDGAR company facts","OK" if s.get("available") else "Unavailable","Revenue, net income, filings"],
        ["Analyst targets","Unavailable on free official sources","Not fabricated"],
    ]
    st.dataframe(pd.DataFrame(rows,columns=["Source","Status","Purpose"]),hide_index=True,use_container_width=True)
    if y.get("error"):
        st.code("Yahoo error: "+y["error"])
    if s.get("error"):
        st.code("SEC error: "+str(s["error"]))

st.caption("Research/educational use only. Free sources can be delayed or incomplete. Verify material facts against primary filings.")
