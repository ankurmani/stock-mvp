# 📈 NewsPulse Stocks
### *Explainable, News-Driven Stock Watchlist for NSE/BSE (Stateless MVP)*

A **news-aware stock analysis and ranking platform** for Indian equity markets (NSE/BSE).  
This application combines **price momentum**, **risk (volatility)**, and **recent news sentiment** to generate an **explainable daily watchlist** — designed for learning, experimentation, and demos.

> ⚠️ This project is for **educational and demonstration purposes only**. It does **not** provide investment advice.

---

## 🔗 Live Demo & Resources

### 🎥 YouTube Demo  
👉 https://www.youtube.com/watch?v=ILoXpdKOvX8

### 🌐 Deployed Application (Streamlit Cloud)  
👉 https://uiapppy-szdys8xbxdvjohjt7ko3pz.streamlit.app/

---

## 🚀 What This Application Does

**NewsPulse Stocks** helps users understand **how market news and price behavior together influence stock movement**.

For each stock, the system:
- Analyzes **recent price momentum**
- Estimates **risk using volatility**
- Fetches and evaluates **recent company news**
- Produces a **transparent final score** with human-readable reasoning

The focus is on **explainability and insight**, not automated trading.

---

## ✨ Key Features

### 1️⃣ Daily Stock Watchlist
- Ranks selected NSE/BSE stocks using a composite score:
  - **Momentum** (1-day & 5-day returns)
  - **Risk** (volatility proxy)
  - **News Impact** (sentiment + article count)
- Fully explainable scoring (no black-box decisions)

---

### 2️⃣ News-Aware Insights
- Integrates **real-time company news** via NewsAPI (stateless, on-demand)
- Automatically classifies news into:
  - 🟢 Positive
  - ⚪ Neutral
  - 🔴 Negative
- Highlights potential **turnaround situations** where:
  - Price trend is weak
  - But positive news acts as a catalyst

---

### 3️⃣ Interactive Price & Volume Charts
- Single interactive Plotly chart showing:
  - Close price
  - Trading volume
  - Moving averages (MA20 / MA50)
- Zoom, pan, and hover for exact values
- Select any date to see **exact close price and volume**

---

### 4️⃣ Range & 52-Week-Style Analysis
- Shows:
  - Current price vs recent high/low
  - Position within available historical range
- Transparently indicates when full 52-week data is not available

---

### 5️⃣ Explainability First
For every stock, the UI displays:
- Final score
- Momentum value
- Risk level (Low / Medium / High)
- News impact
- A clear **“Why today?”** explanation

---

### 6️⃣ Stateless & Free-Tier Friendly Architecture
- ❌ No database
- ❌ No persistent disk
- ✅ On-demand computation
- ✅ In-memory caching only

This allows **100% free deployment** using:
- **Render** (FastAPI backend)
- **Streamlit Cloud** (UI)

---

## 🧠 Architecture Overview

```
Streamlit UI (Frontend)
        ↓
FastAPI Backend (Stateless)
        ↓
Yahoo Finance (Price & Volume)
NewsAPI (Company News)
```

- No user data stored
- No financial data persisted
- Results recomputed safely on refresh

---

## 🛠️ Technology Stack

**Frontend**
- Streamlit
- Plotly
- Pandas (optional, for tables)

**Backend**
- FastAPI
- Requests
- In-memory caching (`lru_cache`)

**Data Sources**
- Yahoo Finance (price & volume)
- NewsAPI (company news)

---

## ⚙️ How Scoring Works (High-Level)

> Weights are heuristic and designed for **clarity and explainability**, not trading performance.

```
final_score =
    0.5 × news_impact
  + 0.3 × momentum
  − 0.2 × risk
```

Where:
- **Momentum** → short-term price returns
- **Risk** → volatility-based penalty
- **News Impact** → sentiment strength + article volume

---

## ⚠️ Disclaimer

> This application is provided **for educational and demonstration purposes only**.

- NOT investment advice
- NOT a buy/sell recommendation
- Automated sentiment can be incorrect
- Market data may be delayed or incomplete
- Always verify using official company filings
- Stock markets involve risk — you may lose money

---

## 🎯 Intended Use Cases

- Learning how **news affects stock prices**
- Demonstrating **AI-assisted financial analysis**
- Portfolio / resume project (AI, ML, Data, FinTech)
- Prototyping news-driven market research ideas

---

## 📌 Future Enhancements

- RSS-based news fallback (no API key required)
- News markers directly on price charts
- Confidence score for signals
- Sector-wise aggregation
- Long-term trend vs short-term news divergence detection

---

## 👤 Author

Built by **Ankur Mani**  
Focused on AI, deep learning, and practical system design.

---

⭐ If you found this project useful, consider starring the repository!
