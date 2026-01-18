import os
import requests
import streamlit as st

try:
    import pandas as pd
except Exception:
    pd = None

import plotly.graph_objects as go

# ---------------------------
# Config
# ---------------------------
API_BASE = os.getenv("API_BASE", "https://stock-mvp-q1xs.onrender.com").rstrip("/")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN", "ankur123refresh").strip()


# ---------------------------
# HTTP helpers (bigger timeouts)
# ---------------------------
def api_get(path: str, params=None, timeout: int = 180):
    url = f"{API_BASE}{path}"
    r = requests.get(url, params=params, timeout=timeout)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"detail": "Non-JSON response", "text": r.text}


def api_post(path: str, headers=None, params=None, timeout: int = 60):
    url = f"{API_BASE}{path}"
    r = requests.post(url, headers=headers or {}, params=params, timeout=timeout)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"detail": "Non-JSON response", "text": r.text}


# ---------------------------
# Cached fetchers
# ---------------------------
@st.cache_data(ttl=60)
def cached_watchlist(limit: int, news_limit: int, news_hours_back: int, watchlist_price_days: int, universe_limit: int):
    return api_get(
        "/watchlist/today",
        params={
            "limit": limit,
            "news_limit": news_limit,
            "news_hours_back": news_hours_back,
            "price_days": watchlist_price_days,
            "universe_limit": universe_limit,
        },
        timeout=240,
    )


@st.cache_data(ttl=60)
def cached_company(ticker: str, days: int):
    return api_get(f"/company/{ticker}", params={"days": days}, timeout=120)


@st.cache_data(ttl=60)
def cached_news(ticker: str, limit: int, hours_back: int):
    return api_get(f"/news/{ticker}", params={"limit": limit, "hours_back": hours_back}, timeout=120)


# ---------------------------
# Utils
# ---------------------------
def risk_label(risk_value: float) -> str:
    if risk_value < 1.5:
        return "Low"
    if risk_value < 3.0:
        return "Medium"
    return "High"


def sentiment_label(news_impact: float) -> str:
    if news_impact > 10:
        return "Positive"
    if news_impact < -10:
        return "Negative"
    return "Neutral"


def safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


def compute_moving_average(values, window: int):
    if not values or window <= 1:
        return None
    ma = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        ma.append(sum(values[start : i + 1]) / (i - start + 1))
    return ma


# ---------------------------
# Page setup
# ---------------------------
st.set_page_config(page_title="NSE/BSE Stock Watchlist (Stateless)", layout="wide")
st.title("📈 NSE/BSE Stock Watchlist (Stateless MVP)")
st.caption(f"Backend API: {API_BASE}")


# ---------------------------
# Sidebar controls
# ---------------------------
st.sidebar.header("Controls")

limit = st.sidebar.slider("How many stocks to show?", min_value=5, max_value=200, value=20, step=5)

min_score = st.sidebar.slider("Min Final Score", min_value=-200, max_value=200, value=-200, step=10)
max_risk = st.sidebar.slider("Max Risk (vol proxy)", min_value=0.0, max_value=10.0, value=10.0, step=0.5)

sent_filter = st.sidebar.multiselect(
    "News Sentiment Bucket",
    options=["Positive", "Neutral", "Negative"],
    default=["Positive", "Neutral", "Negative"],
)

risk_filter = st.sidebar.multiselect(
    "Risk Bucket",
    options=["Low", "Medium", "High"],
    default=["Low", "Medium", "High"],
)

ticker_search = st.sidebar.text_input("Search ticker (e.g., TCS.NS)", value="").strip().upper()

st.sidebar.markdown("---")
st.sidebar.subheader("Free-tier performance")

universe_limit = st.sidebar.slider("Universe size (tickers to scan)", 5, 200, 20, 5)
watchlist_price_days = st.sidebar.selectbox("Watchlist price history (days)", [60, 90, 120, 200], index=2)

st.sidebar.markdown("---")
st.sidebar.subheader("Details page")

news_limit = st.sidebar.slider("News per stock (watchlist buckets)", min_value=0, max_value=20, value=5, step=1)
news_hours_back = st.sidebar.selectbox("News window (hours)", [24, 48, 72, 96, 168], index=2)

chart_days = st.sidebar.selectbox("Chart range (days)", [5, 10, 30, 60, 120], index=2)
history_days = st.sidebar.selectbox("History to fetch (for 52W)", [120, 200, 300, 400, 600], index=2)

show_ma20 = st.sidebar.checkbox("Show MA20", value=True)
show_ma50 = st.sidebar.checkbox("Show MA50", value=False)

st.sidebar.markdown("---")
st.sidebar.subheader("Backend")

if st.sidebar.button("🔄 Refresh Data Now"):
    headers = {}
    if REFRESH_TOKEN:
        headers["X-REFRESH-TOKEN"] = REFRESH_TOKEN
    s, j = api_post("/refresh", headers=headers, timeout=60)
    if s == 200:
        st.sidebar.success("Cache cleared. Reloading…")
        st.cache_data.clear()
        st.rerun()
    else:
        st.sidebar.error(f"Refresh failed: {j}")

st.sidebar.markdown("---")
st.sidebar.write("API Docs:", f"{API_BASE}/docs")
st.sidebar.write("Health:", f"{API_BASE}/health")


# ---------------------------
# Load watchlist
# ---------------------------
with st.spinner("Fetching watchlist (free-tier can be slow on first load)..."):
    status, data = cached_watchlist(limit, news_limit, news_hours_back, watchlist_price_days, universe_limit)

if status != 200:
    st.error(f"Backend error: {data}")
    st.stop()

items = data.get("items", []) or []
date = data.get("date", "")

st.subheader(f"Today’s Watchlist — {date}")

# show caution
caution = data.get("caution", None)
if caution:
    with st.expander("⚠️ Caution / Disclaimer", expanded=False):
        for line in caution:
            st.write("• " + line)

# show debug + params always (so you don't guess)
with st.expander("🧪 Backend Debug (click to expand)", expanded=False):
    st.json({"params": data.get("params", {}), "debug": data.get("debug", {})})
    st.write("Backend returned items:", len(items))

# If backend returned nothing, stop early with actionable info
if len(items) == 0:
    st.error("Backend returned 0 items. This means all tickers failed to fetch/score.")
    dbg = data.get("debug", {})
    if dbg:
        st.write("Sample backend errors:")
        st.json(dbg.get("sample_errors", []))
        st.info(dbg.get("hint", ""))
    st.stop()


# ---------------------------
# Apply filters
# ---------------------------
filtered = []
for it in items:
    if it.get("final_score", -9999) < min_score:
        continue
    if it.get("risk", 9999) > max_risk:
        continue

    s_label = sentiment_label(it.get("news_impact", 0.0))
    r_label = risk_label(it.get("risk", 0.0))

    if s_label not in sent_filter:
        continue
    if r_label not in risk_filter:
        continue
    if ticker_search and ticker_search not in it.get("ticker", ""):
        continue

    it2 = dict(it)
    it2["sentiment_bucket"] = s_label
    it2["risk_bucket"] = r_label
    filtered.append(it2)

# If filtering removes everything, show why
if not filtered:
    st.warning("No stocks match your filters, but backend did return items.")
    st.write("Try setting Min Final Score lower and Max Risk higher.")
    st.write("Sample backend items (first 5):")
    st.json(items[:5])
    st.stop()

left, right = st.columns([0.42, 0.58], gap="large")


# ---------------------------
# Left: selection + table
# ---------------------------
with left:
    st.markdown("### 📌 Stocks")

    ticker_options = [
        f'{x["ticker"]}  |  score={x["final_score"]:.2f}  |  {x["sentiment_bucket"]}  |  risk={x["risk_bucket"]}'
        for x in filtered
    ]
    selected_label = st.radio("Select a stock", ticker_options, index=0)
    selected_ticker = selected_label.split("|")[0].strip()

    st.markdown("#### Quick table")
    if pd is not None:
        df_show = pd.DataFrame(filtered)[
            ["ticker", "final_score", "news_impact", "momentum", "risk", "sentiment_bucket", "risk_bucket"]
        ].sort_values("final_score", ascending=False)
        st.dataframe(df_show, use_container_width=True, hide_index=True)
    else:
        st.json(filtered[:10])


# ---------------------------
# Right: details + charts + news
# ---------------------------
with right:
    st.markdown(f"### 🔍 Details: `{selected_ticker}`")

    sel = next((x for x in filtered if x["ticker"] == selected_ticker), None)
    if sel:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Final Score", f'{sel["final_score"]:.2f}')
        c2.metric("News Impact", f'{sel["news_impact"]:.2f}', sentiment_label(sel["news_impact"]))
        c3.metric("Momentum", f'{sel["momentum"]:.2f}')
        c4.metric("Risk", f'{sel["risk"]:.2f}', risk_label(sel["risk"]))

        st.markdown("**Why today?**")
        st.info(sel.get("reason", "No reason available."))

    # Prices (selected ticker)
    s2, company = cached_company(selected_ticker, days=history_days)
    if s2 != 200:
        st.warning(f"Could not load price data: {company}")
        st.stop()

    prices = company.get("prices", []) or []
    if not prices:
        st.warning("No price points returned.")
        st.stop()

    meta = company.get("meta", {})
    returned_days = meta.get("returned_days", len(prices))

    all_dates = [p["date"] for p in prices]
    all_closes = [safe_float(p.get("close")) for p in prices]
    all_volumes = [safe_float(p.get("volume"), default=0.0) for p in prices]

    dates = all_dates[-chart_days:] if len(all_dates) > chart_days else all_dates
    closes = all_closes[-chart_days:] if len(all_closes) > chart_days else all_closes
    volumes = all_volumes[-chart_days:] if len(all_volumes) > chart_days else all_volumes

    # Range / 52W analysis
    range_label = "52-week" if returned_days >= 252 else f"{returned_days}-day (available) range"
    current = all_closes[-1] if all_closes else (closes[-1] if closes else 0.0)
    hi = max(all_closes) if all_closes else current
    lo = min(all_closes) if all_closes else current

    dist_from_hi = ((current / hi) - 1.0) * 100.0 if hi else 0.0
    dist_from_lo = ((current / lo) - 1.0) * 100.0 if lo else 0.0

    pos = 0.0
    if hi > lo:
        pos = ((current - lo) / (hi - lo)) * 100.0
    pos = max(0.0, min(100.0, pos))

    st.markdown("#### 📊 Range analysis")
    a1, a2, a3, a4 = st.columns(4)
    a1.metric(f"{range_label} Low", f"{lo:.2f}")
    a2.metric(f"{range_label} High", f"{hi:.2f}")
    a3.metric("From High", f"{dist_from_hi:.2f}%")
    a4.metric("From Low", f"+{dist_from_lo:.2f}%")
    st.write(f"Position in range: **{pos:.1f}%** (0% = near low, 100% = near high)")
    st.progress(int(pos))
    st.caption(f"History fetched: requested={history_days}, returned={returned_days}.")

    # ONE interactive chart (price + MA + volume)
    st.markdown(f"#### 📉 Price + Volume (interactive) — last {min(chart_days, len(dates))} days")

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=dates,
            y=closes,
            mode="lines+markers",
            name="Close",
            line=dict(width=3),
            marker=dict(size=6),
            hovertemplate="Date: %{x}<br>Close: %{y:.2f}<extra></extra>",
        )
    )

    if show_ma20 and len(closes) >= 20:
        ma20 = compute_moving_average(closes, 20)
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=ma20,
                mode="lines",
                name="MA20",
                line=dict(width=2, dash="dot"),
                hovertemplate="Date: %{x}<br>MA20: %{y:.2f}<extra></extra>",
            )
        )

    if show_ma50 and len(closes) >= 50:
        ma50 = compute_moving_average(closes, 50)
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=ma50,
                mode="lines",
                name="MA50",
                line=dict(width=2, dash="dash"),
                hovertemplate="Date: %{x}<br>MA50: %{y:.2f}<extra></extra>",
            )
        )

    fig.add_trace(
        go.Bar(
            x=dates,
            y=volumes,
            name="Volume",
            opacity=0.30,
            yaxis="y2",
            hovertemplate="Date: %{x}<br>Volume: %{y:,.0f}<extra></extra>",
        )
    )

    fig.update_layout(
        height=560,
        template="plotly_white",
        xaxis=dict(
            title=dict(text="Date", font=dict(size=16)),
            tickfont=dict(size=13),
            rangeslider=dict(visible=False),
        ),
        yaxis=dict(
            title=dict(text="Close Price", font=dict(size=16)),
            tickfont=dict(size=13),
        ),
        yaxis2=dict(
            title=dict(text="Volume", font=dict(size=16)),
            tickfont=dict(size=13),
            overlaying="y",
            side="right",
            showgrid=False,
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.12,
            xanchor="right",
            x=1,
            font=dict(size=14),
            bgcolor="rgba(255,255,255,0.7)",
            bordercolor="rgba(0,0,0,0.2)",
            borderwidth=1,
        ),
        hoverlabel=dict(font=dict(size=14), bgcolor="white", bordercolor="black"),
        margin=dict(l=60, r=60, t=70, b=60),
    )

    st.plotly_chart(fig, use_container_width=True)

    # Exact value selector
    st.markdown("#### 📅 Exact values on a specific day")
    chosen_date = st.selectbox("Select a date", options=list(dates), index=len(dates) - 1)
    idx = list(dates).index(chosen_date)
    close_val = closes[idx]
    vol_val = volumes[idx]
    m1, m2 = st.columns(2)
    m1.metric("Close", f"{close_val:.2f}")
    m2.metric("Volume", f"{vol_val:,.0f}")

    # News (separate endpoint)
    st.markdown("#### 📰 News (latest)")
    s3, news = cached_news(selected_ticker, limit=25, hours_back=news_hours_back)
    if s3 != 200:
        st.warning(f"Could not load news: {news}")
    else:
        news_items = news.get("items", []) or []
        if not news_items:
            st.write("No news available. (If using NewsAPI, set NEWSAPI_KEY on backend.)")
        else:
            pos_news, neu_news, neg_news = [], [], []
            for n in news_items:
                sent = n.get("sentiment", None)
                if isinstance(sent, (int, float)) and sent >= 0.10:
                    pos_news.append(n)
                elif isinstance(sent, (int, float)) and sent <= -0.10:
                    neg_news.append(n)
                else:
                    neu_news.append(n)

            tab1, tab2, tab3 = st.tabs(
                [f"Positive ({len(pos_news)})", f"Neutral ({len(neu_news)})", f"Negative ({len(neg_news)})"]
            )

            def render_news_block(items_block):
                for n in items_block[:20]:
                    title = n.get("title", "")
                    src = n.get("source", "Unknown")
                    pub = n.get("published_at", "")
                    url = n.get("url", "")
                    sent = n.get("sentiment", None)
                    sent_txt = f"{sent:.2f}" if isinstance(sent, (int, float)) else "n/a"
                    st.markdown(f"- **{title}**  \n  *{src}* | {pub} | sentiment: `{sent_txt}`")
                    if url:
                        st.markdown(f"  ↳ {url}")

            with tab1:
                render_news_block(pos_news)
            with tab2:
                render_news_block(neu_news)
            with tab3:
                render_news_block(neg_news)

    st.markdown("---")
    st.warning(
        "⚠️ Caution: This tool provides information and automated scoring for learning/demo purposes. "
        "It is NOT investment advice. News sentiment is automated and may be wrong. "
        "Always verify from official filings and do your own research."
    )
