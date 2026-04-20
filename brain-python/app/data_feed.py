"""
brain-python/app/data_feed.py
==============================
Twelve Data-based data feed for EUR/USD.
Real market data for live trading.
"""

import asyncio
import logging
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

# --- TWELVE DATA CONFIGURATION ---
TWELVE_API_KEY = "f6f193227ca440f4a9c03a25ab9522fa"
SYMBOL = "EUR/USD"

class DataFeedService:
    def __init__(self) -> None:
        self._connected = False
        self.SYMBOL = "EURUSD"
        self._last_tick_time = 0
        self._cached_tick = None
        self._last_history_time = 0
        self._cached_history = None

    async def connect(self) -> None:
        self._connected = True
        logger.info("DataFeed: connected via Twelve Data")

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
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(None, lambda: self._fetch_history(bars))
        
        # 1. نحسبو المؤشرات على الداتا كاملة (فيها الزيادة)
        df = self._compute_indicators(df)
        # 2. نحيدو السطورة اللي فيهم NaN
        df.dropna(inplace=True)
        # 3. عاد ناخدو غير 60 شمعة اللخرة نقية ومقادة للـ AI
        df = df.tail(bars).reset_index(drop=True)
        
        return {
            "symbol": self.SYMBOL,
            "bars": len(df),
            "columns": df.columns.tolist(),
            "data": df.to_dict(orient="records"),
        }

    def _fetch_latest_tick(self) -> dict[str, Any]:
        current_time = time.time()
        # Cache 15s to save Twelve Data credits
        if self._cached_tick and (current_time - self._last_tick_time < 15):
            return self._cached_tick

        url = f"https://api.twelvedata.com/price?symbol={SYMBOL}&apikey={TWELVE_API_KEY}"
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
            }
            self._last_tick_time = current_time
            return self._cached_tick
        except Exception as exc:
            logger.error(f"TwelveData Tick Error: {exc}")
            if self._cached_tick:
                return self._cached_tick
            raise

    def _fetch_history(self, bars: int) -> pd.DataFrame:
        current_time = time.time()
        if self._cached_history is not None and (current_time - self._last_history_time < 60):
            return self._cached_history.copy()

        # كنجيبو الداتا بزايد (bars + 50) باش المؤشرات يلقاو فين يتسخنو (Warmup)
        req_bars = min(bars + 50, 5000)
        url = f"https://api.twelvedata.com/time_series?symbol={SYMBOL}&interval=1min&outputsize={req_bars}&apikey={TWELVE_API_KEY}"
        
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
            logger.error(f"TwelveData History Error: {exc}")
            if self._cached_history is not None:
                return self._cached_history.copy()
            raise

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
