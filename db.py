from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from config import DB_URL
import os

# Ensure data folder exists for SQLite
if DB_URL.startswith("sqlite:///./"):
    os.makedirs("./data", exist_ok=True)

engine = create_engine(DB_URL, echo=False, connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
