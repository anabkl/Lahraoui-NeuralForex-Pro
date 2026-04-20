"""
brain-python/app/model.py
==========================
Deep-Learning model skeleton for EUR/USD price-direction prediction.

Architecture
------------
A hybrid LSTM + Multi-Head Attention (Transformer-lite) model that ingests
a sliding window of feature vectors, each containing:

  [Close, RSI, MACD, MACD_signal, MACD_hist, OFI]

The model outputs a 3-class softmax (BUY / HOLD / SELL) plus a scalar
confidence score.

Usage
-----
>>> m = NeuralForexModel()
>>> m.load_or_build()          # load weights if they exist, else build fresh
>>> prediction = m.predict(history_dict)
"""

import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Attempt to import TensorFlow; skip gracefully if not installed.
try:
    import tensorflow as tf
    from tensorflow import keras

    _TF_AVAILABLE = True
except ImportError:  # pragma: no cover
    tf = None  # type: ignore[assignment]
    keras = None  # type: ignore[assignment]
    _TF_AVAILABLE = False
    logger.warning("TensorFlow not available – model will run in stub mode")

# Labels for the 3-class output
LABELS = ["BUY", "HOLD", "SELL"]

# Feature columns expected from DataFeedService
FEATURE_COLS = ["Close", "RSI", "MACD", "MACD_signal", "MACD_hist", "OFI"]

# Default model weights path
DEFAULT_WEIGHTS_PATH = Path(os.getenv("MODEL_WEIGHTS_PATH", "/app/weights/model.weights.h5"))


class NeuralForexModel:
    """
    LSTM + Multi-Head Attention model for EUR/USD direction prediction.

    Parameters
    ----------
    sequence_length : int
        Number of time-steps (bars) fed into the model per inference.
    n_features : int
        Number of input features per time-step.
    lstm_units : int
        Hidden size of the LSTM layers.
    num_heads : int
        Number of attention heads in the Transformer block.
    """

    def __init__(
        self,
        sequence_length: int = 60,
        n_features: int = len(FEATURE_COLS),
        lstm_units: int = 128,
        num_heads: int = 4,
    ) -> None:
        self.sequence_length = sequence_length
        self.n_features = n_features
        self.lstm_units = lstm_units
        self.num_heads = num_heads
        self._model: Any = None  # keras.Model | None

        # Min-max scaler state (fit during training or loaded from file)
        self._feature_min: np.ndarray | None = None
        self._feature_max: np.ndarray | None = None

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------
    def _build_model(self) -> Any:
        """
        Construct the LSTM + Multi-Head Attention model graph.

        Network layout
        --------------
        Input  → LSTM(128, return_sequences=True)
               → LSTM(64)
               → Reshape for attention
               → MultiHeadAttention(4 heads)
               → LayerNorm + Dropout
               → Dense(64, relu) + Dense(32, relu)
               → Dense(3, softmax)  [BUY / HOLD / SELL]
        """
        if not _TF_AVAILABLE:
            logger.warning("TensorFlow absent – returning stub model")
            return None

        inp = keras.Input(shape=(self.sequence_length, self.n_features), name="ohlcv_features")

        # ----- LSTM encoder -----------------------------------------------
        x = keras.layers.LSTM(self.lstm_units, return_sequences=True, name="lstm_1")(inp)
        x = keras.layers.Dropout(0.2, name="dropout_1")(x)
        x = keras.layers.LSTM(self.lstm_units // 2, return_sequences=True, name="lstm_2")(x)

        # ----- Multi-Head Self-Attention (Transformer block) ---------------
        attn_out, _ = keras.layers.MultiHeadAttention(
            num_heads=self.num_heads,
            key_dim=self.lstm_units // (self.num_heads * 2),
            name="mha",
        )(x, x, return_attention_scores=True)
        x = keras.layers.Add(name="residual")([x, attn_out])
        x = keras.layers.LayerNormalization(name="layer_norm")(x)

        # ----- Classification head ----------------------------------------
        x = keras.layers.GlobalAveragePooling1D(name="gap")(x)
        x = keras.layers.Dense(64, activation="relu", name="dense_1")(x)
        x = keras.layers.Dropout(0.3, name="dropout_2")(x)
        x = keras.layers.Dense(32, activation="relu", name="dense_2")(x)
        out = keras.layers.Dense(3, activation="softmax", name="output")(x)

        model = keras.Model(inputs=inp, outputs=out, name="NeuralForexPro")
        model.compile(
            optimizer=keras.optimizers.Adam(learning_rate=3e-4),
            loss="categorical_crossentropy",
            metrics=["accuracy"],
        )
        logger.info("Model built:\n%s", model.summary())
        return model

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def load_or_build(self) -> None:
        """Load pre-trained weights if available, otherwise initialise a fresh model."""
        self._model = self._build_model()

        if self._model is None:
            logger.info("Model stub active (TensorFlow not installed)")
            return

        if DEFAULT_WEIGHTS_PATH.exists():
            try:
                self._model.load_weights(str(DEFAULT_WEIGHTS_PATH))
                logger.info("Loaded pre-trained weights from %s", DEFAULT_WEIGHTS_PATH)
            except Exception as exc:
                logger.warning("Could not load weights (%s) – using random init", exc)
        else:
            logger.info("No pre-trained weights found – model uses random initialisation")
            logger.info("Train with: model.train(X, y) before going live")

    def save_weights(self, path: str | Path | None = None) -> None:
        """Persist model weights to disk."""
        if self._model is None:
            return
        target = Path(path or DEFAULT_WEIGHTS_PATH)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._model.save_weights(str(target))
        logger.info("Weights saved to %s", target)

    # ------------------------------------------------------------------
    # Preprocessing
    # ------------------------------------------------------------------
    def _preprocess(self, history: dict[str, Any]) -> np.ndarray:
        """
        Convert the DataFeedService response dict into a normalised
        (1, sequence_length, n_features) numpy array.
        """
        import pandas as pd  # local import to keep startup fast

        records = history.get("data", [])
        if len(records) < self.sequence_length:
            raise ValueError(
                f"Need at least {self.sequence_length} bars for inference, "
                f"got {len(records)}"
            )

        df = pd.DataFrame(records)

        # Ensure all expected columns are present
        missing = [c for c in FEATURE_COLS if c not in df.columns]
        if missing:
            raise ValueError(f"Missing feature columns: {missing}")

        arr = df[FEATURE_COLS].values.astype(np.float32)

        # Take the last sequence_length rows
        arr = arr[-self.sequence_length :]

        # Min-max normalisation per feature
        if self._feature_min is None:
            self._feature_min = arr.min(axis=0)
            self._feature_max = arr.max(axis=0)

        rng = self._feature_max - self._feature_min + 1e-9
        arr = (arr - self._feature_min) / rng

        return arr[np.newaxis, ...]  # shape: (1, seq_len, n_features)

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------
    def predict(self, history: dict[str, Any]) -> dict[str, Any]:
        """
        Run inference and return a structured prediction dictionary.

        Returns
        -------
        {
            "signal"     : "BUY" | "HOLD" | "SELL",
            "confidence" : float (0–1),
            "probabilities": {"BUY": float, "HOLD": float, "SELL": float},
            "model_version": str,
        }
        """
        if self._model is None or not _TF_AVAILABLE:
            return self._stub_prediction()

        try:
            x = self._preprocess(history)
            probs = self._model(x, training=False).numpy()[0]  # shape (3,)
        except Exception as exc:
            logger.error("Inference failed: %s", exc)
            return self._stub_prediction(error=str(exc))

        idx = int(np.argmax(probs))
        return {
            "signal": LABELS[idx],
            "confidence": float(probs[idx]),
            "probabilities": {label: float(p) for label, p in zip(LABELS, probs)},
            "model_version": "lstm-transformer-v1",
        }

    @staticmethod
    def _stub_prediction(error: str | None = None) -> dict[str, Any]:
        """Return a neutral stub prediction when TF is unavailable."""
        result: dict[str, Any] = {
            "signal": "HOLD",
            "confidence": 0.0,
            "probabilities": {"BUY": 0.333, "HOLD": 0.334, "SELL": 0.333},
            "model_version": "stub",
        }
        if error:
            result["error"] = error
        return result

    # ------------------------------------------------------------------
    # Training entry-point (skeleton – integrate with your data pipeline)
    # ------------------------------------------------------------------
    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        epochs: int = 50,
        batch_size: int = 64,
    ) -> Any:
        """
        Train the model.

        Parameters
        ----------
        X_train / X_val : ndarray of shape (N, sequence_length, n_features)
        y_train / y_val : one-hot encoded labels of shape (N, 3)
        """
        if self._model is None:
            raise RuntimeError("Build the model first with load_or_build()")

        callbacks = [
            keras.callbacks.EarlyStopping(patience=10, restore_best_weights=True),
            keras.callbacks.ReduceLROnPlateau(patience=5, factor=0.5),
            keras.callbacks.ModelCheckpoint(
                str(DEFAULT_WEIGHTS_PATH),
                save_best_only=True,
                save_weights_only=True,
            ),
        ]

        history = self._model.fit(
            X_train,
            y_train,
            validation_data=(X_val, y_val),
            epochs=epochs,
            batch_size=batch_size,
            callbacks=callbacks,
        )
        logger.info("Training complete – best val_accuracy: %.4f", max(history.history["val_accuracy"]))
        return history
