"""
brain-python/app/data_feed.py
==============================
MetaTrader 5 data feed wrapper.

On Windows with a live MT5 terminal this module connects directly.
On Linux/Docker (CI or containerised environment) it falls back to a
lightweight simulation mode so the rest of the service remains testable.
"""

import asyncio
import logging
import os
import random
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Try importing MetaTrader5; it is only available on Windows.
try:
    import MetaTrader5 as mt5  # type: ignore[import]

    _MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore[assignment]
    _MT5_AVAILABLE = False
    logger.warning("MetaTrader5 not available – using simulation mode")

try:
    import ta  # technical-analysis library
except ImportError:  # pragma: no cover
    ta = None  # type: ignore[assignment]


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
    TIMEFRAME_M1 = 1  # MT5 TIMEFRAME_M1 constant value

    def __init__(self) -> None:
        self._simulation = not _MT5_AVAILABLE
        self._sim_price: float = 1.0850  # synthetic starting price
        self._connected = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        """Initialise the MetaTrader 5 connection (or simulation mode)."""
        if self._simulation:
            logger.info("DataFeed: simulation mode active (no MT5 terminal)")
            self._connected = True
            return

        loop = asyncio.get_event_loop()
        ok = await loop.run_in_executor(None, mt5.initialize)
        if not ok:
            err = mt5.last_error()
            logger.error("MT5 init failed: %s", err)
            raise ConnectionError(f"MetaTrader5 init failed: {err}")

        logger.info("MT5 connected – account: %s", mt5.account_info())
        self._connected = True

    async def disconnect(self) -> None:
        """Cleanly shut down the MT5 connection."""
        if not self._simulation and _MT5_AVAILABLE:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, mt5.shutdown)
            logger.info("MT5 disconnected")
        self._connected = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def get_latest_tick(self) -> dict[str, Any]:
        """Return the most recent EUR/USD bid/ask tick."""
        if not self._connected:
            raise RuntimeError("DataFeed not connected")

        if self._simulation:
            return self._simulate_tick()

        loop = asyncio.get_event_loop()
        tick = await loop.run_in_executor(None, mt5.symbol_info_tick, self.SYMBOL)
        if tick is None:
            raise RuntimeError(f"No tick data for {self.SYMBOL}")

        return {
            "symbol": self.SYMBOL,
            "bid": tick.bid,
            "ask": tick.ask,
            "time": datetime.fromtimestamp(tick.time, tz=timezone.utc).isoformat(),
        }

    async def get_history(self, bars: int = 200) -> dict[str, Any]:
        """
        Return the last *bars* M1 candles for EUR/USD, enriched with:
        RSI, MACD signal, MACD histogram, and an order-flow imbalance proxy.
        """
        if not self._connected:
            raise RuntimeError("DataFeed not connected")

        if self._simulation:
            df = self._simulate_ohlcv(bars)
        else:
            df = await self._fetch_mt5_history(bars)

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
    # MT5 fetch (real)
    # ------------------------------------------------------------------
    async def _fetch_mt5_history(self, bars: int) -> pd.DataFrame:
        import MetaTrader5 as mt5  # re-import inside to keep type checker happy

        mt5_tf = mt5.TIMEFRAME_M1
        loop = asyncio.get_event_loop()
        rates = await loop.run_in_executor(
            None,
            lambda: mt5.copy_rates_from_pos(self.SYMBOL, mt5_tf, 0, bars),
        )
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"MT5 returned no history for {self.SYMBOL}")

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.rename(
            columns={
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "tick_volume": "Volume",
                "real_volume": "RealVolume",
            },
            inplace=True,
        )
        return df[["time", "Open", "High", "Low", "Close", "Volume"]]

    # ------------------------------------------------------------------
    # Simulation helpers
    # ------------------------------------------------------------------
    def _simulate_tick(self) -> dict[str, Any]:
        """Produce a plausible synthetic EUR/USD tick."""
        spread = round(random.uniform(0.00010, 0.00020), 5)
        self._sim_price += random.gauss(0, 0.00030)
        self._sim_price = max(1.0500, min(1.1500, self._sim_price))
        bid = round(self._sim_price, 5)
        ask = round(bid + spread, 5)
        return {
            "symbol": self.SYMBOL,
            "bid": bid,
            "ask": ask,
            "time": datetime.now(tz=timezone.utc).isoformat(),
            "simulated": True,
        }

    def _simulate_ohlcv(self, bars: int) -> pd.DataFrame:
        """Generate synthetic M1 OHLCV data using a random-walk model."""
        rng = np.random.default_rng(seed=42)
        times = pd.date_range(end=datetime.now(tz=timezone.utc), periods=bars, freq="1min")
        close = np.cumprod(1 + rng.normal(0, 0.0003, bars)) * 1.0850
        high = close + np.abs(rng.normal(0, 0.0005, bars))
        low = close - np.abs(rng.normal(0, 0.0005, bars))
        open_ = np.roll(close, 1)
        open_[0] = close[0]
        volume = rng.integers(100, 2000, bars).astype(float)

        return pd.DataFrame(
            {
                "time": times,
                "Open": open_,
                "High": high,
                "Low": low,
                "Close": close,
                "Volume": volume,
            }
        )

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
