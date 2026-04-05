"""
brain-python/app/main.py
========================
Lahraoui-NeuralForex-Pro – AI Brain Service
FastAPI application that:
  • Streams EUR/USD live ticks from MetaTrader 5
  • Computes technical indicators (RSI, MACD) and order-flow features
  • Serves Deep-Learning (LSTM/Transformer) price predictions
  • Exposes NLP-based economic sentiment from FED & ECB news

Author : Anas Lahraoui
"""

import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.data_feed import DataFeedService
from app.model import NeuralForexModel
from app.sentiment import SentimentAnalyzer

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Service singletons (initialised during lifespan)
# ---------------------------------------------------------------------------
data_feed: DataFeedService | None = None
model: NeuralForexModel | None = None
sentiment_analyzer: SentimentAnalyzer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle hook."""
    global data_feed, model, sentiment_analyzer

    logger.info("Starting Lahraoui-NeuralForex-Pro Brain Service …")

    data_feed = DataFeedService()
    await data_feed.connect()

    model = NeuralForexModel()
    model.load_or_build()

    sentiment_analyzer = SentimentAnalyzer()

    yield  # application runs here

    logger.info("Shutting down Brain Service …")
    await data_feed.disconnect()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Lahraoui-NeuralForex-Pro Brain",
    description="Real-Time EUR/USD AI Prediction & Sentiment Service",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health / heartbeat
# ---------------------------------------------------------------------------
@app.get("/health", tags=["ops"])
async def health_check():
    """Simple liveness probe used by the Java executor heartbeat monitor."""
    return {"status": "ok", "service": "brain-python"}


# ---------------------------------------------------------------------------
# Live tick endpoint
# ---------------------------------------------------------------------------
@app.get("/ticks/latest", tags=["market-data"])
async def get_latest_tick():
    """Return the most recent EUR/USD tick with computed indicators."""
    if data_feed is None:
        raise HTTPException(status_code=503, detail="Data feed not initialised")
    try:
        tick = await data_feed.get_latest_tick()
        return tick
    except Exception as exc:
        logger.error("Error fetching tick: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/ticks/history", tags=["market-data"])
async def get_tick_history(bars: int = 200):
    """Return the last *bars* OHLCV candles with technical features."""
    if data_feed is None:
        raise HTTPException(status_code=503, detail="Data feed not initialised")
    try:
        history = await data_feed.get_history(bars=bars)
        return history
    except Exception as exc:
        logger.error("Error fetching history: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Prediction endpoint
# ---------------------------------------------------------------------------
@app.get("/predict", tags=["ai"])
async def predict():
    """
    Run the LSTM/Transformer model on the latest feature window and return
    a directional prediction (BUY / SELL / HOLD) with a confidence score.
    """
    if data_feed is None or model is None:
        raise HTTPException(status_code=503, detail="Services not ready")
    try:
        history = await data_feed.get_history(bars=model.sequence_length)
        prediction = model.predict(history)
        return prediction
    except Exception as exc:
        logger.error("Prediction error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Sentiment endpoint
# ---------------------------------------------------------------------------
@app.get("/sentiment", tags=["nlp"])
async def get_sentiment():
    """
    Analyse the latest FED and ECB economic news headlines and return
    aggregated sentiment scores (bullish / bearish / neutral for USD/EUR).
    """
    if sentiment_analyzer is None:
        raise HTTPException(status_code=503, detail="Sentiment analyser not ready")
    try:
        result = await sentiment_analyzer.analyse()
        return result
    except Exception as exc:
        logger.error("Sentiment error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("BRAIN_PORT", "8000")),
        reload=False,
    )
