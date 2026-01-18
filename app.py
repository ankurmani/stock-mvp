import datetime as dt
from typing import List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from db import get_db, engine, Base
from models import DailyScore, DailyPrice, NewsArticle

Base.metadata.create_all(bind=engine)

app = FastAPI(title="NSE/BSE News + EOD Stock Watchlist (MVP)")


# ----------------------------
# Helpers
# ----------------------------
def classify_sentiment(sent: float | None) -> str:
    if sent is None:
        return "neutral"
    if sent >= 0.10:
        return "positive"
    if sent <= -0.10:
        return "negative"
    return "neutral"


def caution_block() -> Dict[str, Any]:
    return {
        "caution": [
            "This app provides market/news information and automated scoring for educational/demo purposes.",
            "It is NOT investment advice, NOT a buy/sell recommendation, and does not guarantee returns.",
            "News sentiment is computed automatically and can be wrong or incomplete.",
            "Always verify information from primary sources (exchange filings, company announcements) and do your own research.",
            "Markets involve risk. You may lose money."
        ]
    }


def fetch_top_news_by_bucket(
    db: Session,
    ticker: str,
    limit_total: int = 5,
    hours_back: int = 72
) -> Dict[str, List[Dict[str, Any]]]:
    since_dt = dt.datetime.utcnow() - dt.timedelta(hours=hours_back)

    rows = (
        db.query(NewsArticle)
        .filter(NewsArticle.ticker == ticker)
        .filter(NewsArticle.published_at != None)
        .filter(NewsArticle.published_at >= since_dt)
        .order_by(NewsArticle.published_at.desc())
        .limit(50)
        .all()
    )

    articles = []
    for r in rows:
        bucket = classify_sentiment(r.sentiment)
        articles.append({
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "source": r.source,
            "title": r.title,
            "url": r.url,
            "sentiment": r.sentiment,
            "bucket": bucket,
        })

    def sort_key(a):
        abs_sent = abs(a["sentiment"]) if isinstance(a["sentiment"], (int, float)) else 0.0
        return abs_sent

    pos = [a for a in articles if a["bucket"] == "positive"]
    neu = [a for a in articles if a["bucket"] == "neutral"]
    neg = [a for a in articles if a["bucket"] == "negative"]

    pos = sorted(pos, key=sort_key, reverse=True)
    neu = sorted(neu, key=sort_key, reverse=True)
    neg = sorted(neg, key=sort_key, reverse=True)

    picked = []
    for group in (pos, neg, neu):
        for a in group:
            if len(picked) >= limit_total:
                break
            picked.append(a)
        if len(picked) >= limit_total:
            break

    out_pos = [a for a in picked if a["bucket"] == "positive"]
    out_neu = [a for a in picked if a["bucket"] == "neutral"]
    out_neg = [a for a in picked if a["bucket"] == "negative"]

    return {"positive": out_pos, "neutral": out_neu, "negative": out_neg}


# ----------------------------
# Routes
# ----------------------------
@app.get("/")
def home():
    return {
        "message": "Stock MVP API is running",
        "try": ["/docs", "/health", "/watchlist/today", "/company/TCS.NS?days=300"],
        **caution_block()
    }


@app.get("/health")
def health():
    return {"status": "ok", "date": dt.date.today().isoformat()}


@app.get("/watchlist/today")
def watchlist_today(
    limit: int = 20,
    news_limit: int = 5,
    news_hours_back: int = 72,
    db: Session = Depends(get_db),
):
    today = dt.date.today()
    rows = (
        db.query(DailyScore)
        .filter(DailyScore.date == today)
        .order_by(DailyScore.final_score.desc())
        .limit(limit)
        .all()
    )
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No scores for today. Run: python ingest_prices.py && python ingest_news.py && python score.py"
        )

    items = []
    for r in rows:
        news_buckets = fetch_top_news_by_bucket(
            db=db,
            ticker=r.ticker,
            limit_total=news_limit,
            hours_back=news_hours_back
        )

        items.append({
            "ticker": r.ticker,
            "final_score": r.final_score,
            "news_impact": r.news_impact,
            "momentum": r.momentum,
            "risk": r.risk,
            "reason": r.reason,
            "news": {
                "window_hours": news_hours_back,
                "limit": news_limit,
                "buckets": news_buckets
            }
        })

    return {
        "date": today.isoformat(),
        **caution_block(),
        "notes": [
            "‘Positive/Neutral/Negative’ buckets are based on automated title sentiment and can be wrong.",
            "Always open the source links and verify important claims."
        ],
        "items": items,
    }


@app.get("/company/{ticker}")
def company_detail(
    ticker: str,
    days: int = Query(default=60, ge=5, le=600, description="Number of latest trading days to return (max 600)."),
    db: Session = Depends(get_db),
):
    """
    Returns last `days` EOD records for ticker (oldest->newest).
    Example: /company/TCS.NS?days=300 for ~1-year+ data for 52-week analysis.

    Note: You must have ingested enough price history into DB.
    If you only ingested ~60 days, requesting 300 will still return max available.
    """
    prices = (
        db.query(DailyPrice)
        .filter(DailyPrice.ticker == ticker)
        .order_by(DailyPrice.date.desc())
        .limit(days)
        .all()
    )
    if not prices:
        raise HTTPException(status_code=404, detail="Ticker not found or no price data ingested.")

    prices = list(reversed(prices))

    return {
        "ticker": ticker,
        "meta": {
            "requested_days": days,
            "returned_days": len(prices),
            "asof_date": (prices[-1].date.isoformat() if prices else None),
        },
        "prices": [{"date": p.date.isoformat(), "close": p.close, "volume": p.volume} for p in prices],
        **caution_block()
    }


@app.get("/news/{ticker}")
def company_news(ticker: str, limit: int = 20, db: Session = Depends(get_db)):
    rows = (
        db.query(NewsArticle)
        .filter(NewsArticle.ticker == ticker)
        .order_by(NewsArticle.published_at.desc().nullslast(), NewsArticle.created_at.desc())
        .limit(limit)
        .all()
    )

    items = []
    for r in rows:
        items.append({
            "published_at": (r.published_at.isoformat() if r.published_at else None),
            "source": r.source,
            "title": r.title,
            "url": r.url,
            "sentiment": r.sentiment,
            "bucket": classify_sentiment(r.sentiment),
        })

    return {
        "ticker": ticker,
        **caution_block(),
        "items": items,
    }
