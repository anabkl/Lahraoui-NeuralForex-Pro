package com.neuralforex.executor;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Represents a trading signal received from the Python Brain service.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public class TradingSignal {

    /** Directional signal: "BUY", "SELL", or "HOLD". */
    @JsonProperty("signal")
    private String signal;

    /** Model confidence in the range [0, 1]. */
    @JsonProperty("confidence")
    private double confidence;

    /** Current ask price (used for entry / SL / TP calculation). */
    @JsonProperty("ask")
    private double ask;

    /** Current bid price. */
    @JsonProperty("bid")
    private double bid;

    // ----- Constructors -----

    public TradingSignal() {}

    public TradingSignal(String signal, double confidence, double ask, double bid) {
        this.signal = signal;
        this.confidence = confidence;
        this.ask = ask;
        this.bid = bid;
    }

    // ----- Getters / Setters -----

    public String getSignal() {
        return signal;
    }

    public void setSignal(String signal) {
        this.signal = signal;
    }

    public double getConfidence() {
        return confidence;
    }

    public void setConfidence(double confidence) {
        this.confidence = confidence;
    }

    public double getAsk() {
        return ask;
    }

    public void setAsk(double ask) {
        this.ask = ask;
    }

    public double getBid() {
        return bid;
    }

    public void setBid(double bid) {
        this.bid = bid;
    }

    @Override
    public String toString() {
        return String.format("TradingSignal{signal='%s', confidence=%.4f, ask=%.5f, bid=%.5f}",
                signal, confidence, ask, bid);
    }
}
