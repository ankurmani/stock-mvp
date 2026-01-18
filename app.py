import os
import time
import math
import datetime as dt
from typing import Dict, Any, List, Optional, Tuple

import requests
from fastapi import FastAPI, HTTPException, Query, Depends, Header

from tickers import UNIVERSE  # your list of NSE/BSE tickers like "TCS.NS"


app = FastAPI(title="NSE/BSE News + EOD Stock Watchlist (STATELESS MVP)")


# ----------------------------
# Settings (Env Vars)
# ----------------------------
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "").strip()
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN", "").strip()  # optional but recommended
CACHE_TTL_SEC = int(os.getenv("CACHE_TTL_SEC", "1800"))  # default 30 min

# Yahoo chart endpoint (no API key needed)
YAHOO_CHART_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"


# ----------------------------
# In-memory cache
# ----------------------------
_cache: Dict[str, Any] = {
    "watchlist": None,
    "watchlist_ts": 0.0,
    "prices": {},       # (ticker, days) -> {"ts":..., "data":...}
    "news": {},         # (ticker, limit, hours_back) -> {"ts":..., "data":...}
}


def caution_block() -> Dict[str, Any]:
    return {
        "caution": [
            "This app provides market/news information and automated scoring for educational/demo purposes.",
            "It is NOT investment advice, NOT a buy/sell recommendation, and does not guarantee returns.",
            "News sentiment is computed automatically (keyword-based) and can be wrong or incomplete.",
            "Always verify from primary sources (exchange filings, company announcements) and do your own research.",
            "Markets involve risk. You may lose money."
        ]
    }


# ----------------------------
# Small, dependency-free sentiment (keyword based)
# ----------------------------
_POS_WORDS = {
    "beats", "beat", "surge", "record", "profit", "profits", "growth", "upgrades", "upgrade",
    "buyback", "dividend", "strong", "wins", "win", "order", "contract", "approval",
    "raises", "raised", "guidance", "expands", "expansion", "acquires", "acquisition"
}
_NEG_WORDS = {
    "miss", "misses", "fall", "falls", "drop", "drops", "loss", "losses", "weak",
    "downgrade", "downgrades", "cut", "cuts", "probe", "fraud", "scam", "lawsuit",
    "penalty", "fine", "decline", "slump", "warning", "defaults", "default"
}


def simple_sentiment(text: str) -> float:
    """
    Returns sentiment in approx [-1, +1] using keyword hits.
    Lightweight & fast (no extra libs).
    """
    if not text:
        return 0.0
    t = text.lower()
    pos = sum(1 for w in _POS_WORDS if w in t)
    neg = sum(1 for w in _NEG_WORDS if w in t)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / max(1, total)


def classify_sentiment(sent: Optional[float]) -> str:
    if sent is None:
        return "neutral"
    if sent >= 0.10:
        return "positive"
    if sent <= -0.10:
        return "negative"
    return "neutral"


# ----------------------------
# Yahoo prices (EOD) via chart API
# ----------------------------
def fetch_yahoo_prices(ticker: str, days: int) -> Dict[str, Any]:
    """
    Fetch last `days` trading bars via Yahoo chart API (range auto-chosen).
    Returns oldest->newest arrays.
    """
    # choose range big enough for requested days
    # roughly: 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y
    if days <= 7:
        rng = "1mo"
    elif days <= 35:
        rng = "3mo"
    elif days <= 90:
        rng = "6mo"
    elif days <= 260:
        rng = "1y"
    elif days <= 520:
        rng = "2y"
    else:
        rng = "5y"

    params = {"range": rng, "interval": "1d"}
    url = YAHOO_CHART_URL.format(ticker=ticker)

    r = requests.get(url, params=params, timeout=25)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Yahoo price fetch failed for {ticker}: HTTP {r.status_code}")

    js = r.json()
    chart = (js or {}).get("chart", {})
    err = chart.get("error")
    if err:
        raise HTTPException(status_code=502, detail=f"Yahoo error for {ticker}: {err}")

    result = chart.get("result")
    if not result:
        raise HTTPException(status_code=404, detail=f"No price data for {ticker}")

    res0 = result[0]
    ts = res0.get("timestamp", [])
    ind = (res0.get("indicators") or {}).get("quote", [])
    if not ts or not ind:
        raise HTTPException(status_code=404, detail=f"No usable price series for {ticker}")

    q0 = ind[0]
    closes = q0.get("close", [])
    volumes = q0.get("volume", [])

    rows = []
    for i in range(len(ts)):
        c = closes[i] if i < len(closes) else None
        v = volumes[i] if i < len(volumes) else None
        if c is None:
            continue
        d = dt.datetime.utcfromtimestamp(ts[i]).date().isoformat()
        rows.append({"date": d, "close": float(c), "volume": int(v) if v is not None else 0})

    # keep last `days` rows
    if len(rows) > days:
        rows = rows[-days:]

    return {"ticker": ticker, "prices": rows}


def get_prices_cached(ticker: str, days: int) -> Dict[str, Any]:
    key = (ticker, days)
    now = time.time()
    hit = _cache["prices"].get(key)
    if hit and (now - hit["ts"] <= CACHE_TTL_SEC):
        return hit["data"]

    data = fetch_yahoo_prices(ticker, days)
    _cache["prices"][key] = {"ts": now, "data": data}
    return data


# ----------------------------
# News via NewsAPI (optional)
# ----------------------------
def fetch_news_newsapi(ticker: str, limit: int, hours_back: int) -> Dict[str, Any]:
    """
    Fetch news from NewsAPI 'everything'. Requires NEWSAPI_KEY.
    We query using the base symbol (e.g., "TCS" from "TCS.NS").
    """
    if not NEWSAPI_KEY:
        return {"ticker": ticker, "items": []}

    since = (dt.datetime.utcnow() - dt.timedelta(hours=hours_back)).isoformat(timespec="seconds") + "Z"
    q = ticker.replace(".NS", "").replace(".BO", "")
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": q,
        "from": since,
        "sortBy": "publishedAt",
        "language": "en",
        "pageSize": min(max(limit, 1), 50),
        "apiKey": NEWSAPI_KEY,
    }
    r = requests.get(url, params=params, timeout=25)
    if r.status_code != 200:
        # fail soft
        return {"ticker": ticker, "items": []}

    js = r.json() or {}
    arts = js.get("articles", []) or []

    items = []
    for a in arts[:limit]:
        title = (a.get("title") or "").strip()
        url_ = (a.get("url") or "").strip()
        src = ((a.get("source") or {}).get("name") or "Unknown").strip()
        pub = (a.get("publishedAt") or "").strip()

        sent = simple_sentiment(title)
        items.append({
            "published_at": pub,
            "source": src,
            "title": title,
            "url": url_,
            "sentiment": sent,
            "bucket": classify_sentiment(sent),
        })

    return {"ticker": ticker, "items": items}


def get_news_cached(ticker: str, limit: int, hours_back: int) -> Dict[str, Any]:
    key = (ticker, limit, hours_back)
    now = time.time()
    hit = _cache["news"].get(key)
    if hit and (now - hit["ts"] <= CACHE_TTL_SEC):
        return hit["data"]

    data = fetch_news_newsapi(ticker, limit=limit, hours_back=hours_back)
    _cache["news"][key] = {"ts": now, "data": data}
    return data


# ----------------------------
# Scoring (stateless)
# ----------------------------
def compute_score_from_series(ticker: str, prices: List[Dict[str, Any]], news_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    closes = [p["close"] for p in prices if p.get("close") is not None]
    if len(closes) < 25:
        raise ValueError("not enough price history")

    def ret(n_days: int) -> float:
        if len(closes) >= (n_days + 1):
            return (closes[-1] / closes[-(n_days + 1)] - 1.0)
        return 0.0

    r1 = ret(1)
    r5 = ret(5)
    r20 = ret(20)

    momentum = (r1 * 50.0) + (r5 * 30.0) + (r20 * 20.0)

    # risk = 30D vol proxy
    if len(closes) >= 31:
        rets_1d = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(len(closes) - 30, len(closes))]
        mean = sum(rets_1d) / len(rets_1d)
        var = sum((x - mean) ** 2 for x in rets_1d) / max(1, len(rets_1d) - 1)
        vol = math.sqrt(var)
    else:
        vol = 0.0
    risk = vol * 100.0

    n_count = len(news_items)
    avg_sent = sum((n.get("sentiment") or 0.0) for n in news_items) / n_count if n_count else 0.0

    news_impact = (avg_sent * 60.0) + (min(n_count, 10) * 4.0)

    is_downtrend = (r5 < 0.0) and (r20 < 0.0)
    has_positive_news = (news_impact >= 8.0)
    has_bounce = (r1 > 0.0) or (r5 > -0.01)

    turnaround_bonus = 0.0
    if is_downtrend and has_positive_news:
        base = min(12.0, news_impact * 0.6)
        turnaround_bonus = base + (3.0 if has_bounce else 0.0)

    final_score = (0.5 * news_impact) + (0.3 * momentum) - (0.2 * risk) + turnaround_bonus

    label = "Watch"
    if news_impact > 10 and momentum > 0:
        label = "Catalyst + Momentum"
    if is_downtrend and has_positive_news:
        label = "Turnaround Watch"
    if risk > 4.0 and final_score > 0:
        label = "High Risk Watch"

    reason_parts = []
    if n_count:
        if avg_sent >= 0.10:
            reason_parts.append(f"News: Positive sentiment ({avg_sent:.2f}) across {n_count} articles (window).")
        elif avg_sent <= -0.10:
            reason_parts.append(f"News: Negative sentiment ({avg_sent:.2f}) across {n_count} articles (window).")
        else:
            reason_parts.append(f"News: Mixed/neutral sentiment ({avg_sent:.2f}) across {n_count} articles (window).")
    else:
        reason_parts.append("News: No articles available (or NEWSAPI_KEY not set).")

    if is_downtrend and has_positive_news:
        reason_parts.append("Setup: Downtrend + fresh positive catalyst (needs confirmation).")

    reason_parts.append(f"Returns: 1D={r1*100:.2f}%, 5D={r5*100:.2f}%, 20D={r20*100:.2f}%.")
    reason_parts.append(f"Risk: 30D vol proxy={risk:.2f}.")
    reason_parts.append(f"Label: {label}.")

    return {
        "ticker": ticker,
        "final_score": float(final_score),
        "news_impact": float(news_impact),
        "momentum": float(momentum),
        "risk": float(risk),
        "reason": " ".join(reason_parts),
    }


def build_watchlist(limit: int, news_limit: int, news_hours_back: int, price_days: int) -> Dict[str, Any]:
    items = []
    for ticker in UNIVERSE:
        try:
            p = get_prices_cached(ticker, days=price_days)
            n = get_news_cached(ticker, limit=news_limit, hours_back=news_hours_back)
            score = compute_score_from_series(ticker, p["prices"], n["items"])

            # attach small news buckets for UI (top N)
            buckets = {"positive": [], "neutral": [], "negative": []}
            for it in n["items"][:news_limit]:
                buckets[it["bucket"]].append(it)

            score["news"] = {
                "window_hours": news_hours_back,
                "limit": news_limit,
                "buckets": buckets
            }
            items.append(score)
        except Exception:
            # fail soft per ticker
            continue

    items.sort(key=lambda x: x["final_score"], reverse=True)
    items = items[:limit]

    return {
        "date": dt.date.today().isoformat(),
        **caution_block(),
        "notes": [
            "Data is computed on-demand and cached in memory (free-tier friendly).",
            "If the server restarts, cache clears and data is recomputed.",
            "News sentiment is keyword-based; open sources to verify important claims.",
        ],
        "items": items
    }


def get_watchlist_cached(limit: int, news_limit: int, news_hours_back: int, price_days: int) -> Dict[str, Any]:
    now = time.time()
    if _cache["watchlist"] and (now - _cache["watchlist_ts"] <= CACHE_TTL_SEC):
        wl = _cache["watchlist"]
        # If user asks smaller limit than cached, slice
        wl2 = dict(wl)
        wl2["items"] = wl["items"][:limit]
        return wl2

    wl = build_watchlist(limit=limit, news_limit=news_limit, news_hours_back=news_hours_back, price_days=price_days)
    _cache["watchlist"] = wl
    _cache["watchlist_ts"] = now
    return wl


# ----------------------------
# Token dependency for refresh
# ----------------------------
def require_refresh_token(x_refresh_token: Optional[str] = Header(default=None)):
    # If REFRESH_TOKEN is not set, allow refresh (dev mode).
    if not REFRESH_TOKEN:
        return True
    if not x_refresh_token or x_refresh_token.strip() != REFRESH_TOKEN:
        raise HTTPException(status_code=401, detail="Missing/invalid X-REFRESH-TOKEN")
    return True


# ----------------------------
# Routes
# ----------------------------
@app.get("/")
def home():
    return {
        "message": "Stateless Stock MVP API is running",
        "try": ["/docs", "/health", "/watchlist/today", "/company/TCS.NS?days=300", "/news/TCS.NS?limit=10"],
        **caution_block()
    }


@app.get("/health")
def health():
    return {"status": "ok", "date": dt.date.today().isoformat(), "cache_ttl_sec": CACHE_TTL_SEC}


@app.post("/refresh")
def refresh(_: bool = Depends(require_refresh_token)):
    # clear caches
    _cache["watchlist"] = None
    _cache["watchlist_ts"] = 0.0
    _cache["prices"].clear()
    _cache["news"].clear()
    return {"ok": True, "message": "Cache cleared. Next request will recompute."}


@app.get("/watchlist/today")
def watchlist_today(
    limit: int = Query(default=20, ge=5, le=200),
    news_limit: int = Query(default=5, ge=0, le=20),
    news_hours_back: int = Query(default=72, ge=6, le=168),
    price_days: int = Query(default=300, ge=30, le=600),
):
    wl = get_watchlist_cached(limit=limit, news_limit=news_limit, news_hours_back=news_hours_back, price_days=price_days)
    return wl


@app.get("/company/{ticker}")
def company_detail(
    ticker: str,
    days: int = Query(default=300, ge=5, le=600),
):
    data = get_prices_cached(ticker, days=days)
    return {
        "ticker": ticker,
        "meta": {"requested_days": days, "returned_days": len(data["prices"]), "asof_date": (data["prices"][-1]["date"] if data["prices"] else None)},
        "prices": data["prices"],
        **caution_block()
    }


@app.get("/news/{ticker}")
def company_news(
    ticker: str,
    limit: int = Query(default=25, ge=1, le=50),
    hours_back: int = Query(default=72, ge=6, le=168),
):
    data = get_news_cached(ticker, limit=limit, hours_back=hours_back)
    return {
        "ticker": ticker,
        **caution_block(),
        "items": data["items"],
    }
