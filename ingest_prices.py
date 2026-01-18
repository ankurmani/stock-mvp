import datetime as dt
import time
import pandas as pd
import yfinance as yf
from sqlalchemy.exc import IntegrityError

from db import SessionLocal, engine, Base
from models import Company, DailyPrice
from tickers import UNIVERSE

def init_db():
    Base.metadata.create_all(bind=engine)

def upsert_company(db, ticker: str):
    c = db.query(Company).filter(Company.ticker == ticker).first()
    if not c:
        db.add(Company(ticker=ticker))
        db.commit()

def chunked(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

def ingest_prices(days: int = 120, chunk_size: int = 20, sleep_sec: float = 2.0, max_retries: int = 3):
    """
    Batch-download prices to avoid Yahoo rate limits.
    - Downloads tickers in chunks (e.g., 20 at a time)
    - Sleeps between chunks
    - Retries on rate limit errors
    """
    init_db()
    db = SessionLocal()
    try:
        end = dt.date.today()
        start = end - dt.timedelta(days=days * 2)  # weekend buffer

        for t in UNIVERSE:
            upsert_company(db, t)

        for group in chunked(UNIVERSE, chunk_size):
            tickers_str = " ".join(group)

            for attempt in range(1, max_retries + 1):
                try:
                    df = yf.download(
                        tickers_str,
                        start=start.isoformat(),
                        end=(end + dt.timedelta(days=1)).isoformat(),
                        group_by="ticker",
                        auto_adjust=False,
                        threads=False,   # important: avoid parallel requests
                        progress=False
                    )
                    break
                except Exception as e:
                    msg = str(e)
                    if "Rate limited" in msg or "Too Many Requests" in msg:
                        wait = sleep_sec * attempt * 3
                        print(f"[prices] Rate limited. Sleeping {wait:.1f}s (attempt {attempt}/{max_retries})")
                        time.sleep(wait)
                        df = None
                        continue
                    raise

            if df is None or df.empty:
                print(f"[prices] No data for chunk: {group}")
                time.sleep(sleep_sec)
                continue

            # When multiple tickers, yfinance returns MultiIndex columns
            # If only one ticker in chunk, columns may be flat.
            for ticker in group:
                try:
                    sub = df[ticker].dropna()
                except Exception:
                    # fallback for single ticker case
                    sub = df.dropna()

                if sub is None or sub.empty or "Close" not in sub.columns:
                    print(f"[prices] No usable data for {ticker}")
                    continue

                sub = sub.reset_index()
                inserted = 0
                for _, row in sub.iterrows():
                    d = row["Date"].date() if hasattr(row["Date"], "date") else row["Date"]
                    close = float(row["Close"])
                    vol = float(row["Volume"]) if "Volume" in row and pd.notna(row["Volume"]) else None

                    rec = DailyPrice(ticker=ticker, date=d, close=close, volume=vol)
                    db.add(rec)
                    try:
                        db.commit()
                        inserted += 1
                    except IntegrityError:
                        db.rollback()

                print(f"[prices] OK {ticker} inserted={inserted} rows={len(sub)}")

            time.sleep(sleep_sec)
    finally:
        db.close()

if __name__ == "__main__":
    ingest_prices(days=180, chunk_size=15, sleep_sec=2.5, max_retries=3)
