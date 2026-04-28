"""
brain-python/app/data_feed.py
==============================
Market data service for EUR/USD.

The service defaults to demo mode so the academic project can run without a
paid market-data key or internet access. Set MARKET_DATA_MODE=twelvedata and
TWELVE_DATA_API_KEY in .env when you want to test the live feed.
"""

import asyncio
import logging
import math
import os
import requests
import time
from datetime import datetime, timezone
from typing import Any
import pandas as pd

try:
    import ta
except ImportError:
    ta = None

logger = logging.getLogger(__name__)

class DataFeedService:
    def __init__(self) -> None:
        self._connected = False
        self.SYMBOL = os.getenv("SYMBOL", "EURUSD")
        self._external_symbol = os.getenv("TWELVE_DATA_SYMBOL", "EUR/USD")
        self._mode = os.getenv("MARKET_DATA_MODE", "demo").strip().lower()
        self._twelve_api_key = os.getenv("TWELVE_DATA_API_KEY", "").strip()
        self._last_tick_time = 0
        self._cached_tick = None
        self._last_history_time = 0
        self._cached_history = None

    async def connect(self) -> None:
        if self._mode == "twelvedata" and not self._twelve_api_key:
            logger.warning("MARKET_DATA_MODE=twelvedata but TWELVE_DATA_API_KEY is missing; using demo data")
            self._mode = "demo"
        self._connected = True
        logger.info("DataFeed connected in %s mode", self._mode)

    async def disconnect(self) -> None:
        self._connected = False

    async def get_latest_tick(self) -> dict[str, Any]:
        if not self._connected:
            raise RuntimeError("DataFeed not connected")
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_latest_tick)

    async def get_history(self, bars: int = 60) -> dict[str, Any]:
        if not self._connected:
            raise RuntimeError("DataFeed not connected")
        bars = max(1, min(int(bars), 1000))
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(None, lambda: self._fetch_history(bars))

        # Compute indicators before trimming so RSI/MACD have enough warm-up bars.
        df = self._compute_indicators(df)
        df.dropna(inplace=True)
        df = df.tail(bars).reset_index(drop=True)
        df["time"] = pd.to_datetime(df["time"]).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        return {
            "symbol": self.SYMBOL,
            "mode": self._mode,
            "bars": len(df),
            "columns": df.columns.tolist(),
            "data": df.to_dict(orient="records"),
        }

    def _fetch_latest_tick(self) -> dict[str, Any]:
        current_time = time.time()
        # Cache briefly to keep the dashboard smooth and avoid wasting API calls.
        if self._cached_tick and (current_time - self._last_tick_time < 15):
            return self._cached_tick

        if self._mode != "twelvedata":
            return self._demo_tick(current_time)

        url = (
            "https://api.twelvedata.com/price"
            f"?symbol={self._external_symbol}&apikey={self._twelve_api_key}"
        )
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if "price" not in data:
                raise RuntimeError(f"TwelveData error: {data}")

            price = float(data["price"])
            spread = 0.00010
            self._cached_tick = {
                "symbol": self.SYMBOL,
                "bid": round(price, 5),
                "ask": round(price + spread, 5),
                "time": datetime.now(tz=timezone.utc).isoformat(),
                "mode": self._mode,
            }
            self._last_tick_time = current_time
            return self._cached_tick
        except Exception as exc:
            logger.warning("Twelve Data tick failed (%s); falling back to demo tick", exc)
            if self._cached_tick:
                return self._cached_tick
            return self._demo_tick(current_time)

    def _fetch_history(self, bars: int) -> pd.DataFrame:
        current_time = time.time()
        if self._cached_history is not None and (current_time - self._last_history_time < 60):
            return self._cached_history.copy()

        # Fetch/generate extra rows so RSI and MACD can warm up before inference.
        req_bars = min(bars + 50, 5000)

        if self._mode != "twelvedata":
            df = self._demo_history(req_bars)
            self._cached_history = df
            self._last_history_time = current_time
            return df.copy()

        url = (
            "https://api.twelvedata.com/time_series"
            f"?symbol={self._external_symbol}&interval=1min"
            f"&outputsize={req_bars}&apikey={self._twelve_api_key}"
        )
        
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            
            if "values" not in data:
                raise RuntimeError(f"TwelveData error: {data}")
            
            df = pd.DataFrame(data["values"])
            df.rename(columns={"datetime": "time"}, inplace=True)
            df["Open"] = df["open"].astype(float)
            df["High"] = df["high"].astype(float)
            df["Low"] = df["low"].astype(float)
            df["Close"] = df["close"].astype(float)
            df["Volume"] = 1.0
            
            df["time"] = pd.to_datetime(df["time"])
            df = df.iloc[::-1].reset_index(drop=True)
            
            self._cached_history = df
            self._last_history_time = current_time
            return df.copy()
        except Exception as exc:
            logger.warning("Twelve Data history failed (%s); falling back to demo history", exc)
            if self._cached_history is not None:
                return self._cached_history.copy()
            return self._demo_history(req_bars)

    def _demo_tick(self, current_time: float) -> dict[str, Any]:
        """Return a deterministic, safe EUR/USD demo tick."""
        price = self._demo_price(current_time / 60)
        spread = 0.00010
        self._cached_tick = {
            "symbol": self.SYMBOL,
            "bid": round(price, 5),
            "ask": round(price + spread, 5),
            "time": datetime.now(tz=timezone.utc).isoformat(),
            "mode": "demo",
        }
        self._last_tick_time = current_time
        return self._cached_tick

    def _demo_history(self, bars: int) -> pd.DataFrame:
        """Generate repeatable OHLC bars for local demos and tests."""
        now = int(time.time() // 60) * 60
        rows = []
        for i in range(bars):
            minute = now - (bars - i - 1) * 60
            open_price = self._demo_price((minute - 60) / 60)
            close_price = self._demo_price(minute / 60)
            wiggle = 0.00005 + abs(math.sin(minute / 900)) * 0.00008
            high = max(open_price, close_price) + wiggle
            low = min(open_price, close_price) - wiggle
            rows.append({
                "time": datetime.fromtimestamp(minute, tz=timezone.utc),
                "Open": round(open_price, 5),
                "High": round(high, 5),
                "Low": round(low, 5),
                "Close": round(close_price, 5),
                "Volume": 1.0,
            })
        return pd.DataFrame(rows)

    @staticmethod
    def _demo_price(minute_index: float) -> float:
        trend = math.sin(minute_index / 80) * 0.0012
        cycle = math.sin(minute_index / 9) * 0.00035
        return 1.0850 + trend + cycle

    def _compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["Close"]
        if ta is not None:
            df["RSI"] = ta.momentum.RSIIndicator(close=close, window=14).rsi()
            macd_ind = ta.trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
            df["MACD"] = macd_ind.macd()
            df["MACD_signal"] = macd_ind.macd_signal()
            df["MACD_hist"] = macd_ind.macd_diff()
        else:
            df["RSI"] = self._rsi(close, 14)
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            df["MACD"] = ema12 - ema26
            df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
            df["MACD_hist"] = df["MACD"] - df["MACD_signal"]
            
        epsilon = 1e-9
        df["OFI"] = (df["Close"] - df["Open"]) / (df["High"] - df["Low"] + epsilon)
        df["OFI"] = df["OFI"].clip(-1, 1)
        return df

    @staticmethod
    def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
        rs = avg_gain / (avg_loss + 1e-9)
        return 100 - (100 / (1 + rs))
