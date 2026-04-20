#!/usr/bin/env python3
"""
brain-python/train_model.py
============================
Standalone training script for the NeuralForexPro LSTM+Attention model.

Data strategy
-------------
* Primary  : 1-hour bars for ``EURUSD=X`` covering the last 730 days (~17 500 bars).
* Fallback : 1-minute bars for the last 7 days if hourly data is unavailable.

Both datasets are enriched with the same technical indicators used by the live
DataFeedService (RSI-14, MACD 12/26/9, OFI) so the trained weights are fully
compatible with the production inference pipeline.

Label generation
----------------
A bar is labelled:
  BUY  (+1) if the close 1 bar ahead is more than ``THRESHOLD`` pips above current close.
  SELL (-1) if the close 1 bar ahead is more than ``THRESHOLD`` pips below current close.
  HOLD  (0) otherwise.

Labels are one-hot encoded for categorical_crossentropy training.

Usage
-----
    # From the brain-python directory (or repo root):
    python brain-python/train_model.py

    # Override output path:
    MODEL_WEIGHTS_PATH=/my/path/model.weights.h5 python brain-python/train_model.py

The script writes the best-epoch weights to ``app/weights/model.weights.h5``
(or the path in the ``MODEL_WEIGHTS_PATH`` environment variable), so the API
will load them automatically on the next startup.
"""

import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------------------
# Make sure the project's app package is importable when running from repo root
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from app.model import NeuralForexModel, DEFAULT_WEIGHTS_PATH, FEATURE_COLS  # noqa: E402

try:
    import ta  # technical-analysis library
except ImportError:  # pragma: no cover
    ta = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TICKER = "EURUSD=X"
SEQUENCE_LENGTH = 60        # must match NeuralForexModel default
THRESHOLD_PIPS = 0.00010    # 1 pip threshold for BUY/SELL label
VALIDATION_SPLIT = 0.15     # fraction of samples held out for validation
EPOCHS = 50
BATCH_SIZE = 64

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data download
# ---------------------------------------------------------------------------

def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten a multi-level column index produced by yfinance single-ticker downloads."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def download_hourly(max_days: int = 730) -> pd.DataFrame:
    """Download up to *max_days* days of 1-hour OHLCV bars for EURUSD=X."""
    logger.info("Downloading hourly data for %s (period=%dd) …", TICKER, max_days)
    raw = yf.download(
        TICKER,
        period=f"{max_days}d",
        interval="1h",
        auto_adjust=True,
        progress=False,
    )
    raw = _flatten_columns(raw)
    logger.info("Hourly download: %d rows", len(raw))
    return raw


def download_minutely(max_days: int = 7) -> pd.DataFrame:
    """Download up to *max_days* days of 1-minute OHLCV bars for EURUSD=X (yfinance cap: 7 days)."""
    days = min(max_days, 7)
    logger.info("Downloading 1-minute data for %s (period=%dd) …", TICKER, days)
    raw = yf.download(
        TICKER,
        period=f"{days}d",
        interval="1m",
        auto_adjust=True,
        progress=False,
    )
    raw = _flatten_columns(raw)
    logger.info("1-minute download: %d rows", len(raw))
    return raw


import pandas as pd

def get_ohlcv():
    logger.info("Reading 5-years local data from historical_data.csv ...")
    try:
        # قراءة الملف الضخم
        df = pd.read_csv("/app/historical_data.csv")
        
        # تحويل صيغة Dukascopy باش يفهمها الموديل
        if 'timestamp' in df.columns:
            df['Datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('Datetime', inplace=True)
        else:
            df.rename(columns={df.columns[0]: 'Datetime'}, inplace=True)
            df['Datetime'] = pd.to_datetime(df['Datetime'])
            df.set_index('Datetime', inplace=True)
        
        # توحيد أسماء الأعمدة
        df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}, inplace=True)
        
        logger.info(f"SUCCESS: Loaded {len(df)} rows from local CSV!")
        
        # الحل ديال مشكل الـ Volume
        if 'Volume' not in df.columns:
            df['Volume'] = 1  # نعطيو حجم افتراضي حيت Dukascopy مافيهاش Volume
        else:
            df = df[df['Volume'] > 0] 
	
	# غادي ناخدو غير آخر 300 ألف شمعة باش الرام (RAM) ديال الماك ماتعمرش
        df = df.tail(400000)
                    
        return df
    except Exception as e:
        logger.error(f"Failed to read CSV: {e}")
        raise RuntimeError("Could not load local data.")


# ---------------------------------------------------------------------------
# Technical indicators  (mirrors DataFeedService._compute_indicators)
# ---------------------------------------------------------------------------

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add RSI, MACD, and OFI columns – identical to DataFeedService._compute_indicators."""
    close = df["Close"]

    if ta is not None:
        df["RSI"] = ta.momentum.RSIIndicator(close=close, window=14).rsi()
        macd_ind = ta.trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
        df["MACD"] = macd_ind.macd()
        df["MACD_signal"] = macd_ind.macd_signal()
        df["MACD_hist"] = macd_ind.macd_diff()
    else:
        # Manual EWM fallback (same as DataFeedService)
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
        df["RSI"] = 100 - (100 / (1 + avg_gain / (avg_loss + 1e-9)))
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        df["MACD"] = ema12 - ema26
        df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
        df["MACD_hist"] = df["MACD"] - df["MACD_signal"]

    epsilon = 1e-9
    df["OFI"] = (df["Close"] - df["Open"]) / (df["High"] - df["Low"] + epsilon)
    df["OFI"] = df["OFI"].clip(-1, 1)

    df.dropna(inplace=True)
    return df


# ---------------------------------------------------------------------------
# Label generation
# ---------------------------------------------------------------------------

def make_labels(close: pd.Series, threshold: float = THRESHOLD_PIPS) -> np.ndarray:
    """
    Generate integer class labels (0=BUY, 1=HOLD, 2=SELL) from future close returns.

    A one-bar-ahead comparison is used to keep look-ahead limited to the
    minimum possible window.
    """
    future_close = close.shift(-1)
    delta = future_close - close

    labels = np.full(len(close), 1, dtype=np.int32)  # default: HOLD
    labels[delta > threshold] = 0   # BUY
    labels[delta < -threshold] = 2  # SELL

    return labels


# ---------------------------------------------------------------------------
# Sequence builder
# ---------------------------------------------------------------------------

def build_sequences(
    df: pd.DataFrame,
    labels: np.ndarray,
    seq_len: int = SEQUENCE_LENGTH,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Slide a window of *seq_len* rows over *df[FEATURE_COLS]* to produce
    arrays X of shape ``(N, seq_len, n_features)`` and one-hot y of shape ``(N, 3)``.

    The last sample in a window is assigned the label of its final row.
    The very last row is dropped because its label requires a future bar
    that does not exist (after the ``shift(-1)``).
    """
    features = df[FEATURE_COLS].values.astype(np.float32)

    # Min-max normalise per feature across the full dataset
    f_min = features.min(axis=0)
    f_max = features.max(axis=0)
    features = (features - f_min) / (f_max - f_min + 1e-9)

    xs, ys = [], []
    # Stop one bar before end: last row has NaN label (shift(-1))
    valid_end = len(features) - 1
    for i in range(seq_len, valid_end):
        xs.append(features[i - seq_len: i])
        # The window covers rows [i-seq_len, i-1]; its label is for the last row (i-1)
        ys.append(labels[i - 1])

    X = np.stack(xs, axis=0)       # (N, seq_len, n_features)
    y_int = np.array(ys, dtype=np.int32)

    # One-hot encode
    y_onehot = np.zeros((len(y_int), 3), dtype=np.float32)
    y_onehot[np.arange(len(y_int)), y_int] = 1.0

    return X, y_onehot


# ---------------------------------------------------------------------------
# Train / validate split
# ---------------------------------------------------------------------------

def train_val_split(
    X: np.ndarray, y: np.ndarray, val_frac: float = VALIDATION_SPLIT
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Chronological (non-shuffled) split to avoid data leakage."""
    n_val = max(1, int(len(X) * val_frac))
    n_train = len(X) - n_val
    return X[:n_train], y[:n_train], X[n_train:], y[n_train:]


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("=== NeuralForexPro Training Script ===")

    # ---- 1. Download -------------------------------------------------------
    df = get_ohlcv()

    # ---- 2. Indicators -----------------------------------------------------
    df = compute_indicators(df)
    logger.info("Dataset after indicator warmup: %d rows, columns: %s", len(df), df.columns.tolist())

    if len(df) < SEQUENCE_LENGTH + 10:
        raise RuntimeError(
            f"Not enough data after indicator warmup: {len(df)} rows "
            f"(need > {SEQUENCE_LENGTH + 10})"
        )

    # ---- 3. Labels ---------------------------------------------------------
    labels = make_labels(df["Close"])
    label_counts = {c: int((labels == i).sum()) for i, c in enumerate(["BUY", "HOLD", "SELL"])}
    logger.info("Label distribution: %s", label_counts)

    # ---- 4. Sequences ------------------------------------------------------
    X, y = build_sequences(df, labels, seq_len=SEQUENCE_LENGTH)
    logger.info("Sequences built: X=%s, y=%s", X.shape, y.shape)

    # ---- 5. Split ----------------------------------------------------------
    X_train, y_train, X_val, y_val = train_val_split(X, y)
    logger.info(
        "Train: %d samples | Val: %d samples", len(X_train), len(X_val)
    )

    # ---- 6. Build model ----------------------------------------------------
    model = NeuralForexModel(sequence_length=SEQUENCE_LENGTH)
    model.load_or_build()

    # ---- 7. Train ----------------------------------------------------------
    logger.info(
        "Training for up to %d epochs, batch_size=%d …", EPOCHS, BATCH_SIZE
    )
    model.train(
        X_train=X_train,
        y_train=y_train,
        X_val=X_val,
        y_val=y_val,
        epochs=EPOCHS,
        batch_size=BATCH_SIZE,
    )

    # ---- 8. Save weights ---------------------------------------------------
    weights_path = Path(os.getenv("MODEL_WEIGHTS_PATH", str(DEFAULT_WEIGHTS_PATH)))
    model.save_weights(weights_path)
    logger.info("✓ Weights saved to %s", weights_path)
    logger.info("=== Training complete – restart brain-python to load the new weights ===")


if __name__ == "__main__":
    main()
