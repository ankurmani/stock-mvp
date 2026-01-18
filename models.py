from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Text, UniqueConstraint, Index
from sqlalchemy.sql import func
from db import Base

class Company(Base):
    __tablename__ = "companies"
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)  # optional

class DailyPrice(Base):
    __tablename__ = "daily_prices"
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, index=True, nullable=False)
    date = Column(Date, index=True, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_price_ticker_date"),
        Index("ix_price_ticker_date", "ticker", "date"),
    )

class NewsArticle(Base):
    __tablename__ = "news_articles"
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, index=True, nullable=False)
    published_at = Column(DateTime, index=True, nullable=True)
    source = Column(String, nullable=True)
    title = Column(String, nullable=False)
    url = Column(String, nullable=True)
    sentiment = Column(Float, nullable=True)  # -1..1 approx

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_news_ticker_published", "ticker", "published_at"),
    )

class DailyScore(Base):
    __tablename__ = "daily_scores"
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, index=True, nullable=False)
    date = Column(Date, index=True, nullable=False)

    news_impact = Column(Float, nullable=False, default=0.0)
    momentum = Column(Float, nullable=False, default=0.0)
    risk = Column(Float, nullable=False, default=0.0)
    final_score = Column(Float, nullable=False, default=0.0)

    reason = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_score_ticker_date"),
        Index("ix_score_date_final", "date", "final_score"),
    )
