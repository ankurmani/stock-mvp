import os
import time
import math
import datetime as dt
from typing import Dict, Any, List
from functools import lru_cache

import requests
from fastapi import FastAPI, HTTPException, Query

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "").strip()

# Free-tier friendly limits
CACHE_TTL_SECONDS = 60 * 30   # 30 min cache
MAX_UNIVERSE_LIMIT = 200
YAHOO_TIMEOUT = 25
NEWS_TIMEOUT = 20

# ------------------------------------------------------------
# TICKERS + BETTER NEWS QUERIES
# ------------------------------------------------------------
UNIVERSE = [
    "TCS.NS", "INFY.NS", "RELIANCE.NS", "HDFCBANK.NS",
    "ICICIBANK.NS", "SBIN.NS", "AXISBANK.NS",
    "ITC.NS", "LT.NS", "HINDUNILVR.NS",
    "BHARTIARTL.NS", "ASIANPAINT.NS",
    "MARUTI.NS", "SUNPHARMA.NS", "NTPC.NS",
    "ULTRACEMCO.NS", "WIPRO.NS", "HCLTECH.NS",
    "KOTAKBANK.NS", "TITAN.NS",
]

NEWS_QUERY = {
    "TCS.NS": "Tata Consultancy Services OR TCS",
    "INFY.NS": "Infosys OR INFY",
    "RELIANCE.NS": "Reliance Industries OR RIL",
    "HDFCBANK.NS": "HDFC Bank",
    "ICICIBANK.NS": "ICICI Bank",
    "SBIN.NS": "State Bank of India OR SBI",
    "AXISBANK.NS": "Axis Bank",
    "ITC.NS": "ITC Limited",
    "LT.NS": "Larsen & Toubro OR L&T",
    "BHARTIARTL.NS": "Bharti Airtel OR Airtel",
}

# ------------------------------------------------------------
# FASTAPI
# ------------------------------------------------------------
app = FastAPI(title="Stateless NSE/BSE Stock MVP")

# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------
def caution_block() -> Dict[str, Any]:
    return {
        "caution": [
            "This app is for educational/demo purposes only.",
            "This is NOT investment advice.",
            "Automated sentiment and scoring may be incorrect.",
            "Always verify from official filings and sources.",
            "Markets involve risk. You may lose money."
        ]
    }


def classify_sentiment(x: float | None) -> str:
    if x is None:
        return "neutral"
    if x >= 0.10:
        return "positive"
    if x <= -0.10:
        return "negative"
    return "neutral"


def yahoo_headers():
    return {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
    }


# ------------------------------------------------------------
# PRICE FETCH (Yahoo Finance)
# ------------------------------------------------------------
@lru_cache(maxsize=512)
def fetch_prices(ticker: str, days: int) -> Dict[str, Any]:
    period2 = int(time.time())
    period1 = period2 - int(days * 86400)

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {
        "period1": period1,
        "period2": period2,
        "interval": "1d",
        "events": "history",
    }

    r = requests.get(url, params=params, headers=yahoo_headers(), timeout=YAHOO_TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"Yahoo HTTP {r.status_code}")

    js = r.json()
    result = js.get("chart", {}).get("result", [])
    if not result:
        raise RuntimeError("Yahoo empty result")

    data = result[0]
    timestamps = data["timestamp"]
    quotes = data["indicators"]["quote"][0]

    prices = []
    for i, ts in enumerate(timestamps):
        close = quotes["close"][i]
        vol = quotes["volume"][i]
        if close is None:
            continue
        prices.append({
            "date": dt.datetime.utcfromtimestamp(ts).date().isoformat(),
            "close": float(close),
            "volume": int(vol or 0),
        })

    if len(prices) < 10:
        raise RuntimeError("Insufficient price data")

    return {
        "ticker": ticker,
        "prices": prices,
        "meta": {"returned_days": len(prices)},
    }


# ------------------------------------------------------------
# NEWS FETCH (NewsAPI)
# ------------------------------------------------------------
@lru_cache(maxsize=512)
def fetch_news(ticker: str, limit: int, hours_back: int) -> Dict[str, Any]:
    if not NEWSAPI_KEY:
        return {"ticker": ticker, "items": [], "error": "NEWSAPI_KEY not set"}

    q = NEWS_QUERY.get(ticker, ticker.replace(".NS", "").replace(".BO", ""))

    since = (dt.datetime.utcnow() - dt.timedelta(hours=hours_back)).isoformat() + "Z"

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": q,
        "language": "en",
        "sortBy": "publishedAt",
        "from": since,
        "pageSize": min(limit, 20),
        "apiKey": NEWSAPI_KEY,
    }

    r = requests.get(url, params=params, timeout=NEWS_TIMEOUT)

    if r.status_code != 200:
        return {
            "ticker": ticker,
            "items": [],
            "error": {
                "status_code": r.status_code,
                "message": r.text[:300],
            },
        }

    js = r.json()
    items = []

    for a in js.get("articles", []):
        title = a.get("title") or ""
        sentiment = 0.0
        if any(w in title.lower() for w in ["profit", "growth", "beat", "wins"]):
            sentiment = 0.4
        if any(w in title.lower() for w in ["loss", "fall", "probe", "decline"]):
            sentiment = -0.4

        items.append({
            "published_at": a.get("publishedAt"),
            "source": a.get("source", {}).get("name"),
            "title": title,
            "url": a.get("url"),
            "sentiment": sentiment,
            "bucket": classify_sentiment(sentiment),
        })

    return {"ticker": ticker, "items": items}


# ------------------------------------------------------------
# SCORING
# ------------------------------------------------------------
def compute_score(prices: List[Dict[str, Any]], news_items: List[Dict[str, Any]]) -> Dict[str, float]:
    closes = [p["close"] for p in prices]
    r1 = (closes[-1] / closes[-2] - 1) if len(closes) >= 2 else 0.0
    r5 = (closes[-1] / closes[-6] - 1) if len(closes) >= 6 else 0.0

    momentum = (r1 * 60) + (r5 * 40)

    rets = [(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes))]
    vol = math.sqrt(sum(r * r for r in rets) / max(len(rets), 1))
    risk = vol * 100

    avg_sent = sum(n["sentiment"] for n in news_items) / max(len(news_items), 1)
    news_impact = (avg_sent * 60) + (len(news_items) * 4)

    final_score = (0.5 * news_impact) + (0.3 * momentum) - (0.2 * risk)

    return {
        "momentum": momentum,
        "risk": risk,
        "news_impact": news_impact,
        "final_score": final_score,
    }


# ------------------------------------------------------------
# WATCHLIST
# ------------------------------------------------------------
@app.get("/watchlist/today")
def watchlist_today(
    limit: int = Query(20, ge=5, le=200),
    price_days: int = Query(120, ge=30, le=600),
    news_limit: int = Query(5, ge=0, le=20),
    news_hours_back: int = Query(72, ge=6, le=168),
    universe_limit: int = Query(20, ge=5, le=MAX_UNIVERSE_LIMIT),
):
    items = []
    failed = 0
    errors = []

    for ticker in UNIVERSE[:universe_limit]:
        try:
            p = fetch_prices(ticker, price_days)
            n = fetch_news(ticker, news_limit, news_hours_back)
            s = compute_score(p["prices"], n["items"])

            items.append({
                "ticker": ticker,
                **s,
                "reason": "Stateless score computed from momentum, volatility, and recent news.",
            })

        except Exception as e:
            failed += 1
            if len(errors) < 5:
                errors.append({"ticker": ticker, "error": str(e)})

    items.sort(key=lambda x: x["final_score"], reverse=True)
    items = items[:limit]

    return {
        "date": dt.date.today().isoformat(),
        **caution_block(),
        "params": {
            "limit": limit,
            "price_days": price_days,
            "news_limit": news_limit,
            "news_hours_back": news_hours_back,
            "universe_limit": universe_limit,
            "universe_total": len(UNIVERSE),
        },
        "debug": {
            "scanned": universe_limit,
            "succeeded": len(items),
            "failed": failed,
            "sample_errors": errors,
        },
        "items": items,
    }


# ------------------------------------------------------------
# COMPANY DETAILS
# ------------------------------------------------------------
@app.get("/company/{ticker}")
def company_detail(
    ticker: str,
    days: int = Query(300, ge=30, le=600),
):
    p = fetch_prices(ticker, days)
    return {
        "ticker": ticker,
        "prices": p["prices"],
        "meta": p["meta"],
        **caution_block(),
    }


# ------------------------------------------------------------
# NEWS
# ------------------------------------------------------------
@app.get("/news/{ticker}")
def company_news(
    ticker: str,
    limit: int = Query(10, ge=0, le=20),
    hours_back: int = Query(72, ge=6, le=168),
):
    n = fetch_news(ticker, limit, hours_back)
    return {
        "ticker": ticker,
        **caution_block(),
        **n,
    }


# ------------------------------------------------------------
# HEALTH
# ------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "date": dt.date.today().isoformat()}
