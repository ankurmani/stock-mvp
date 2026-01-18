import os
from dotenv import load_dotenv

load_dotenv()
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "").strip()
DB_URL = os.getenv("DB_URL", "sqlite:///./data/stock_mvp.db")

# Optional: NewsAPI (recommended). If empty, news ingestion will be skipped.
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "").strip()

# Universe size: keep it small for MVP.
UNIVERSE_NAME = os.getenv("UNIVERSE_NAME", "NIFTY50")
