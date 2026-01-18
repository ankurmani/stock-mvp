import datetime as dt
import requests
from textblob import TextBlob
from sqlalchemy.exc import IntegrityError

from db import SessionLocal, engine, Base
from models import NewsArticle, Company
from config import NEWSAPI_KEY
from tickers import UNIVERSE

def init_db():
    Base.metadata.create_all(bind=engine)

def sentiment_score(text: str) -> float:
    """
    TextBlob polarity is in [-1, 1]. Good enough for MVP.
    """
    try:
        return float(TextBlob(text).sentiment.polarity)
    except Exception:
        return 0.0

def company_query_from_ticker(ticker: str) -> str:
    # Very simple mapping for MVP: use the base symbol as query
    # Example: RELIANCE.NS -> RELIANCE
    base = ticker.split(".")[0]
    # Handle BAJAJ-AUTO etc.
    base = base.replace("-", " ")
    return base

def ingest_news(days_back: int = 2):
    init_db()
    if not NEWSAPI_KEY:
        print("[news] NEWSAPI_KEY is empty. Skipping news ingestion.")
        return

    db = SessionLocal()
    try:
        to_date = dt.datetime.utcnow()
        from_date = to_date - dt.timedelta(days=days_back)

        for ticker in UNIVERSE:
            q = company_query_from_ticker(ticker)
            url = "https://newsapi.org/v2/everything"
            params = {
                "q": q,
                "from": from_date.date().isoformat(),
                "to": to_date.date().isoformat(),
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 15,
                "apiKey": NEWSAPI_KEY,
            }
            r = requests.get(url, params=params, timeout=30)
            if r.status_code != 200:
                print(f"[news] {ticker} query='{q}' failed: {r.status_code} {r.text[:120]}")
                continue

            data = r.json()
            articles = data.get("articles", [])
            if not articles:
                print(f"[news] No articles for {ticker} (q='{q}')")
                continue

            # Ensure company exists
            if not db.query(Company).filter(Company.ticker == ticker).first():
                db.add(Company(ticker=ticker))
                db.commit()

            inserted = 0
            for a in articles:
                title = (a.get("title") or "").strip()
                if not title:
                    continue
                published_at = a.get("publishedAt")
                published_dt = None
                if published_at:
                    try:
                        published_dt = dt.datetime.fromisoformat(published_at.replace("Z", "+00:00")).replace(tzinfo=None)
                    except Exception:
                        published_dt = None

                src = (a.get("source") or {}).get("name")
                link = a.get("url")
                s = sentiment_score(title)

                rec = NewsArticle(
                    ticker=ticker,
                    published_at=published_dt,
                    source=src,
                    title=title[:500],
                    url=link,
                    sentiment=s,
                )
                db.add(rec)
                try:
                    db.commit()
                    inserted += 1
                except IntegrityError:
                    db.rollback()

            print(f"[news] OK {ticker} inserted={inserted}/{len(articles)}")
    finally:
        db.close()

if __name__ == "__main__":
    ingest_news(days_back=3)
