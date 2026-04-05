"""
brain-python/app/sentiment.py
==============================
NLP Sentiment Analyser for FED & ECB economic communications.

Strategy
--------
1. Fetch the latest RSS headlines from FED and ECB news feeds.
2. Run each headline through a pre-trained FinBERT-style sentiment model
   (via HuggingFace Transformers).
3. Aggregate scores per institution and produce a composite USD/EUR bias.

The result drives the NLP feature that the Deep Learning model can use as
an auxiliary signal during live trading.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentiment model
# ---------------------------------------------------------------------------
try:
    from transformers import pipeline  # type: ignore[import]

    _TRANSFORMERS_AVAILABLE = True
except ImportError:
    pipeline = None  # type: ignore[assignment]
    _TRANSFORMERS_AVAILABLE = False
    logger.warning("Transformers not available – sentiment will use keyword heuristic")

# ---------------------------------------------------------------------------
# RSS / news source configuration
# ---------------------------------------------------------------------------
NEWS_SOURCES = {
    "FED": [
        "https://www.federalreserve.gov/feeds/press_all.xml",
        "https://www.federalreserve.gov/feeds/speeches.xml",
    ],
    "ECB": [
        "https://www.ecb.europa.eu/rss/press.html",
        "https://www.ecb.europa.eu/rss/speeches.html",
    ],
}

# Simple keyword heuristic (fallback when Transformers absent)
_HAWKISH_KEYWORDS = {
    "rate hike", "tighten", "hawkish", "inflation concern", "raise rates",
    "policy tightening", "higher rates", "restrictive",
}
_DOVISH_KEYWORDS = {
    "rate cut", "easing", "dovish", "stimulus", "lower rates",
    "accommodative", "pause", "pivot",
}


class SentimentAnalyzer:
    """
    Analyses FED and ECB news sentiment and returns a per-institution
    bias score in the range [-1, +1]:
        +1 = maximally hawkish (currency-positive)
        -1 = maximally dovish (currency-negative)
         0 = neutral
    """

    _MODEL_NAME = "ProsusAI/finbert"  # HuggingFace FinBERT

    def __init__(self) -> None:
        self._nlp: Any = None
        self._init_model()

    # ------------------------------------------------------------------
    # Initialise
    # ------------------------------------------------------------------
    def _init_model(self) -> None:
        if not _TRANSFORMERS_AVAILABLE:
            return
        try:
            # Load in a non-blocking manner; use CPU to avoid GPU OOM in container
            self._nlp = pipeline(
                "text-classification",
                model=self._MODEL_NAME,
                tokenizer=self._MODEL_NAME,
                device=-1,  # CPU
                top_k=None,  # return all scores
            )
            logger.info("FinBERT sentiment model loaded (%s)", self._MODEL_NAME)
        except Exception as exc:
            logger.warning("Could not load FinBERT (%s) – falling back to heuristic", exc)
            self._nlp = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def analyse(self) -> dict[str, Any]:
        """
        Fetch and score the latest FED and ECB headlines.

        Returns
        -------
        {
            "FED": {"score": float, "bias": str, "headlines_analysed": int},
            "ECB": {"score": float, "bias": str, "headlines_analysed": int},
            "composite": {"USD_bias": str, "EUR_bias": str},
            "timestamp": str,
        }
        """
        results: dict[str, Any] = {}
        tasks = {inst: self._analyse_institution(inst, urls) for inst, urls in NEWS_SOURCES.items()}

        for institution, coro in tasks.items():
            try:
                results[institution] = await coro
            except Exception as exc:
                logger.error("Sentiment analysis failed for %s: %s", institution, exc)
                results[institution] = {"score": 0.0, "bias": "neutral", "headlines_analysed": 0, "error": str(exc)}

        # Composite interpretation
        fed_score = results.get("FED", {}).get("score", 0.0)
        ecb_score = results.get("ECB", {}).get("score", 0.0)
        results["composite"] = {
            "USD_bias": self._score_to_bias(fed_score),
            "EUR_bias": self._score_to_bias(ecb_score),
            # Positive → EURUSD bullish if ECB more hawkish than FED
            "EURUSD_signal": self._score_to_bias(ecb_score - fed_score),
        }
        results["timestamp"] = datetime.now(tz=timezone.utc).isoformat()
        return results

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    async def _analyse_institution(self, institution: str, urls: list[str]) -> dict[str, Any]:
        """Fetch headlines and compute an average sentiment score."""
        headlines = await self._fetch_headlines(urls)
        if not headlines:
            return {"score": 0.0, "bias": "neutral", "headlines_analysed": 0}

        if self._nlp is not None:
            scores = self._score_with_finbert(headlines)
        else:
            scores = [self._keyword_score(h) for h in headlines]

        avg_score = sum(scores) / len(scores) if scores else 0.0
        return {
            "score": round(avg_score, 4),
            "bias": self._score_to_bias(avg_score),
            "headlines_analysed": len(headlines),
        }

    async def _fetch_headlines(self, urls: list[str]) -> list[str]:
        """Download RSS feeds and extract <title> text."""
        headlines: list[str] = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for url in urls:
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    # Minimal XML title extraction (no lxml dependency required)
                    import re
                    titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", resp.text)
                    if not titles:
                        titles = re.findall(r"<title>(.*?)</title>", resp.text)
                    # Skip the first title (feed name) and take up to 10
                    headlines.extend(titles[1:11])
                except Exception as exc:
                    logger.warning("Failed to fetch %s: %s", url, exc)
        return headlines

    def _score_with_finbert(self, headlines: list[str]) -> list[float]:
        """
        Run FinBERT on each headline.
        Maps: positive → +1, neutral → 0, negative → -1
        Weighted by the label's confidence score.
        """
        scores = []
        label_map = {"positive": 1.0, "neutral": 0.0, "negative": -1.0}

        for headline in headlines:
            try:
                # pipeline returns list of dicts [{"label": ..., "score": ...}, ...]
                preds = self._nlp(headline[:512])  # truncate to model max
                # Flatten if nested
                if preds and isinstance(preds[0], list):
                    preds = preds[0]
                weighted = sum(label_map.get(p["label"].lower(), 0.0) * p["score"] for p in preds)
                scores.append(weighted)
            except Exception as exc:
                logger.debug("FinBERT inference error: %s", exc)
                scores.append(0.0)
        return scores

    @staticmethod
    def _keyword_score(text: str) -> float:
        """Simple keyword-based heuristic – used when FinBERT is unavailable."""
        lower = text.lower()
        hawkish_hits = sum(1 for kw in _HAWKISH_KEYWORDS if kw in lower)
        dovish_hits = sum(1 for kw in _DOVISH_KEYWORDS if kw in lower)
        total = hawkish_hits + dovish_hits
        if total == 0:
            return 0.0
        return (hawkish_hits - dovish_hits) / total

    @staticmethod
    def _score_to_bias(score: float) -> str:
        if score > 0.15:
            return "hawkish"
        if score < -0.15:
            return "dovish"
        return "neutral"
