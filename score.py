import datetime as dt
import numpy as np
from sqlalchemy.exc import IntegrityError

from db import SessionLocal, engine, Base
from models import DailyPrice, NewsArticle, DailyScore
from tickers import UNIVERSE


def init_db():
    Base.metadata.create_all(bind=engine)


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def compute_scores(for_date: dt.date | None = None, lookback_prices: int = 120):
    """
    Score each ticker for `for_date` (default: today).
    Uses:
      - News Impact (48h): avg sentiment + news count
      - Momentum: 1D + 5D + 20D returns (scaled)
      - Risk: 30D volatility proxy
      - Turnaround bonus: downtrend + positive catalyst
    """
    init_db()
    db = SessionLocal()
    try:
        if for_date is None:
            for_date = dt.date.today()

        since_dt = dt.datetime.utcnow() - dt.timedelta(hours=48)

        for ticker in UNIVERSE:
            # ---------- Load prices ----------
            prices = (
                db.query(DailyPrice)
                .filter(DailyPrice.ticker == ticker)
                .order_by(DailyPrice.date.desc())
                .limit(lookback_prices)
                .all()
            )
            if len(prices) < 25:
                # Need at least ~21 trading days for r20 + some buffer
                continue

            # Oldest -> newest
            prices_sorted = list(reversed(prices))
            closes = np.array([p.close for p in prices_sorted], dtype=float)

            # ---------- Returns ----------
            def ret(n_days: int) -> float:
                # return from n trading days ago to today
                if len(closes) >= (n_days + 1):
                    return float(closes[-1] / closes[-(n_days + 1)] - 1.0)
                return 0.0

            r1 = ret(1)
            r5 = ret(5)
            r20 = ret(20)

            # Momentum score (scaled)
            # Use all three: emphasizes fresh move but respects trend.
            momentum = (r1 * 50.0) + (r5 * 30.0) + (r20 * 20.0)

            # ---------- Risk (30D vol proxy) ----------
            if len(closes) >= 31:
                rets_1d = np.diff(closes[-31:]) / closes[-31:-1]
                vol = float(np.std(rets_1d)) if len(rets_1d) > 5 else 0.0
            else:
                vol = 0.0
            risk = vol * 100.0

            # ---------- News (48h) ----------
            news = (
                db.query(NewsArticle)
                .filter(NewsArticle.ticker == ticker)
                .filter(NewsArticle.published_at != None)
                .filter(NewsArticle.published_at >= since_dt)
                .all()
            )
            n_count = len(news)
            avg_sent = float(np.mean([n.sentiment or 0.0 for n in news])) if n_count else 0.0

            # News impact score: sentiment + volume
            news_impact = (avg_sent * 60.0) + (min(n_count, 10) * 4.0)

            # ---------- Turnaround logic ----------
            is_downtrend = (r5 < 0.0) and (r20 < 0.0)
            has_positive_news = (news_impact >= 8.0)

            # Confirmation: stock is downtrend but today is green (or strong bounce)
            has_bounce = (r1 > 0.0) or (r5 > -0.01)  # tiny stabilization allowed

            turnaround_bonus = 0.0
            if is_downtrend and has_positive_news:
                # Give a capped bonus; extra if bounce confirmation exists
                base = min(12.0, news_impact * 0.6)
                turnaround_bonus = base + (3.0 if has_bounce else 0.0)

            # ---------- Final score ----------
            final_score = (0.5 * news_impact) + (0.3 * momentum) - (0.2 * risk) + turnaround_bonus

            # ---------- Labeling (for interpretability) ----------
            # These are heuristic labels for UI, not financial advice.
            label = "Watch"
            if risk > 4.0 and final_score > 0:
                label = "High Risk Watch"
            if news_impact > 10 and momentum > 0:
                label = "Catalyst + Momentum"
            if is_downtrend and has_positive_news:
                label = "Turnaround Watch"

            # ---------- Reasons ----------
            reason_parts = []

            if n_count:
                if avg_sent >= 0.10:
                    reason_parts.append(f"News: Positive sentiment ({avg_sent:.2f}) across {n_count} articles (48h).")
                elif avg_sent <= -0.10:
                    reason_parts.append(f"News: Negative sentiment ({avg_sent:.2f}) across {n_count} articles (48h).")
                else:
                    reason_parts.append(f"News: Mixed/neutral sentiment ({avg_sent:.2f}) across {n_count} articles (48h).")
            else:
                reason_parts.append("News: No major articles detected in last 48h (or news ingestion not enabled).")

            if is_downtrend and has_positive_news:
                if has_bounce:
                    reason_parts.append("Setup: Downtrend + fresh positive catalyst with early bounce (needs confirmation).")
                else:
                    reason_parts.append("Setup: Downtrend + fresh positive catalyst (higher risk; wait for confirmation).")

            reason_parts.append(f"Returns: 1D={r1*100:.2f}%, 5D={r5*100:.2f}%, 20D={r20*100:.2f}%.")
            reason_parts.append(f"Risk: 30D volatility proxy={risk:.2f}.")
            reason_parts.append(f"Label: {label}.")

            score_row = DailyScore(
                ticker=ticker,
                date=for_date,
                news_impact=float(news_impact),
                momentum=float(momentum),
                risk=float(risk),
                final_score=float(final_score),
                reason=" ".join(reason_parts),
            )
            db.add(score_row)

            try:
                db.commit()
            except IntegrityError:
                db.rollback()  # already scored today (or unique constraint hit)

        print("[score] Done.")
    finally:
        db.close()


if __name__ == "__main__":
    compute_scores()
