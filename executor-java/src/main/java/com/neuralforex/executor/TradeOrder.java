package com.neuralforex.executor;

/**
 * Immutable value object representing a fully parameterised trade order
 * ready to be submitted to the broker API.
 */
public final class TradeOrder {

    private final String direction;    // "BUY" or "SELL"
    private final double entryPrice;
    private final double lotSize;
    private final double stopLoss;
    private final double takeProfit;

    public TradeOrder(String direction, double entryPrice,
                      double lotSize, double stopLoss, double takeProfit) {
        this.direction  = direction;
        this.entryPrice = entryPrice;
        this.lotSize    = lotSize;
        this.stopLoss   = stopLoss;
        this.takeProfit = takeProfit;
    }

    public String getDirection()  { return direction;  }
    public double getEntryPrice() { return entryPrice; }
    public double getLotSize()    { return lotSize;    }
    public double getStopLoss()   { return stopLoss;   }
    public double getTakeProfit() { return takeProfit; }

    @Override
    public String toString() {
        return String.format(
                "TradeOrder{dir=%s, entry=%.5f, lots=%.2f, SL=%.5f, TP=%.5f}",
                direction, entryPrice, lotSize, stopLoss, takeProfit);
    }
}
