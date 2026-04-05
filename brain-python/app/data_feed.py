"""
brain-python/app/data_feed.py
==============================
yfinance-based data feed for EUR/USD.

Fetches real market data via Yahoo Finance (ticker ``EURUSD=X``) so the
service works cross-platform on macOS, Linux, and inside Docker.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import yfinance as yf

try:
    import ta  # technical-analysis library
except ImportError:  # pragma: no cover
    ta = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

TICKER = "EURUSD=X"


class DataFeedService:
    """
    Provides EUR/USD market data enriched with technical indicators
    and order-flow proxy features.

    Indicators computed
    -------------------
    * RSI  (14-period)
    * MACD (12/26/9)
    * Order-Flow proxy: tick-volume imbalance (buy_vol – sell_vol / total)
    """

    SYMBOL = "EURUSD"

    def __init__(self) -> None:
        self._connected = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        """Mark the feed as ready (no persistent connection needed for yfinance)."""
        self._connected = True
        logger.info("DataFeed: connected via yfinance (ticker %s)", TICKER)

    async def disconnect(self) -> None:
        """No-op – yfinance uses stateless HTTP requests."""
        self._connected = False
        logger.info("DataFeed: disconnected")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def get_latest_tick(self) -> dict[str, Any]:
        """Return the most recent EUR/USD bid/ask tick."""
        if not self._connected:
            raise RuntimeError("DataFeed not connected")

        loop = asyncio.get_event_loop()
        tick_data = await loop.run_in_executor(None, self._fetch_latest_tick)
        return tick_data

    async def get_history(self, bars: int = 200) -> dict[str, Any]:
        """
        Return the last *bars* M1 candles for EUR/USD, enriched with:
        RSI, MACD signal, MACD histogram, and an order-flow imbalance proxy.
        """
        if not self._connected:
            raise RuntimeError("DataFeed not connected")

        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(None, lambda: self._fetch_history(bars))

        df = self._compute_indicators(df)
        # Drop rows with NaN introduced by indicator warmup
        df.dropna(inplace=True)

        return {
            "symbol": self.SYMBOL,
            "bars": len(df),
            "columns": df.columns.tolist(),
            "data": df.to_dict(orient="records"),
        }

    # ------------------------------------------------------------------
    # yfinance fetch helpers
    # ------------------------------------------------------------------
    def _fetch_latest_tick(self) -> dict[str, Any]:
        """Fetch the most recent quote and return bid/ask approximation.

        Yahoo Finance does not expose a real FX spread, so a synthetic
        spread of 1 pip (0.00010) is added to derive ask from bid.
        """
        ticker = yf.Ticker(TICKER)
        try:
            price: float = float(ticker.fast_info.last_price)
        except (AttributeError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Could not retrieve latest price for {TICKER}: {exc}"
            ) from exc
        # Use a synthetic 1-pip spread (typical for EUR/USD)
        spread = 0.00010
        bid = round(price, 5)
        ask = round(price + spread, 5)
        return {
            "symbol": self.SYMBOL,
            "bid": bid,
            "ask": ask,
            "time": datetime.now(tz=timezone.utc).isoformat(),
        }

    def _fetch_history(self, bars: int) -> pd.DataFrame:
        """Download the last *bars* 1-minute candles from Yahoo Finance."""
        # yfinance caps 1m data at 7 days; fetch enough days to cover *bars* bars.
        # FX markets trade ~23 h/day on weekdays; assume ~1380 tradeable minutes
        # per day and add a 3-day buffer for weekends / low-liquidity gaps.
        tradeable_minutes_per_day = 1380
        days_needed = max(2, (bars // tradeable_minutes_per_day) + 3)
        period = f"{min(days_needed, 7)}d"

        raw: pd.DataFrame = yf.download(
            TICKER,
            period=period,
            interval="1m",
            auto_adjust=True,
            progress=False,
        )

        if raw.empty:
            raise RuntimeError(f"yfinance returned no data for {TICKER}")

        # Flatten multi-level columns produced when downloading a single ticker
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        raw = raw[["Open", "High", "Low", "Close", "Volume"]].copy()

        # Ensure UTC-aware DatetimeIndex and expose it as a 'time' column
        if raw.index.tz is None:
            raw.index = raw.index.tz_localize("UTC")
        else:
            raw.index = raw.index.tz_convert("UTC")

        raw.index.name = "time"
        raw = raw.reset_index()

        # Return the most recent *bars* rows
        return raw.tail(bars).reset_index(drop=True)

    # ------------------------------------------------------------------
    # Technical indicator computation
    # ------------------------------------------------------------------
    def _compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add RSI, MACD, and an order-flow imbalance column to *df*.

        Order-flow proxy
        ----------------
        A simple tick-volume-based imbalance:
            OFI = (close - open) / (high - low + ε)  ∈ [-1, 1]
        Positive → net buying pressure; negative → net selling.
        """
        close = df["Close"]

        if ta is not None:
            # --- RSI (14) -------------------------------------------------
            df["RSI"] = ta.momentum.RSIIndicator(close=close, window=14).rsi()

            # --- MACD (12/26/9) -------------------------------------------
            macd_ind = ta.trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
            df["MACD"] = macd_ind.macd()
            df["MACD_signal"] = macd_ind.macd_signal()
            df["MACD_hist"] = macd_ind.macd_diff()
        else:
            # Fallback: manual EWM-based implementations
            df["RSI"] = self._rsi(close, 14)
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            df["MACD"] = ema12 - ema26
            df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
            df["MACD_hist"] = df["MACD"] - df["MACD_signal"]

        # --- Order-Flow Imbalance (OFI) -----------------------------------
        epsilon = 1e-9
        df["OFI"] = (df["Close"] - df["Open"]) / (df["High"] - df["Low"] + epsilon)
        df["OFI"] = df["OFI"].clip(-1, 1)

        return df

    @staticmethod
    def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
        """Wilder-smoothed RSI – used when the *ta* library is absent."""
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
        rs = avg_gain / (avg_loss + 1e-9)
        return 100 - (100 / (1 + rs))

