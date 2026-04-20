package com.neuralforex.executor;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * RiskManager – calculates position size, stop-loss, and take-profit levels.
 *
 * <p>Risk model
 * <pre>
 *   Lot size  = (account_balance × risk_pct) / (stop_loss_pips × pip_value)
 *   Stop Loss = entry_price ∓ (stop_loss_pips × pip_size)
 *   Take Profit = entry_price ± (stop_loss_pips × rr_ratio × pip_size)
 * </pre>
 *
 * <p>All monetary values are in account currency (default USD).
 * EUR/USD pip size = 0.0001 (4th decimal place).
 */
@Service
public class RiskManager {

    private static final Logger log = LoggerFactory.getLogger(RiskManager.class);

    /** Standard EUR/USD pip size. */
    private static final double PIP_SIZE = 0.0001;

    /** Pip value per standard lot (100 000 units) for EUR/USD in a USD account. */
    private static final double PIP_VALUE_PER_LOT = 10.0;

    /** Minimum allowed lot size on most brokers. */
    private static final double MIN_LOT = 0.01;

    /** Maximum allowed lot size (hard cap to prevent runaway risk). */
    private static final double MAX_LOT = 10.0;

    @Value("${risk.account_balance:10000.0}")
    private double accountBalance;

    @Value("${risk.risk_percent:1.0}")
    private double riskPercent;   // percentage of balance risked per trade

    @Value("${risk.stop_loss_pips:20.0}")
    private double stopLossPips;

    @Value("${risk.reward_ratio:2.0}")
    private double rewardRatio;   // risk:reward (e.g. 2 = take-profit at 2× SL distance)

    // -------------------------------------------------------------------------
    // Public API
    // -------------------------------------------------------------------------

    /**
     * Calculate the risk parameters for a new trade.
     *
     * @param signal  The {@link TradingSignal} produced by the Brain service.
     * @return        A populated {@link TradeOrder} ready for execution.
     * @throws IllegalArgumentException if the signal is HOLD or parameters invalid.
     */
    public TradeOrder calculateOrder(TradingSignal signal) {
        if ("HOLD".equalsIgnoreCase(signal.getSignal())) {
            throw new IllegalArgumentException("Cannot create order for HOLD signal");
        }

        boolean isBuy = "BUY".equalsIgnoreCase(signal.getSignal());
        double entryPrice = isBuy ? signal.getAsk() : signal.getBid();

        double lotSize = calculateLotSize();
        double stopLossPrice = calculateStopLoss(entryPrice, isBuy);
        double takeProfitPrice = calculateTakeProfit(entryPrice, isBuy);

        TradeOrder order = new TradeOrder(
                signal.getSignal(),
                entryPrice,
                lotSize,
                stopLossPrice,
                takeProfitPrice
        );

        log.info("Risk calculated – {}", order);
        return order;
    }

    // -------------------------------------------------------------------------
    // Risk calculations
    // -------------------------------------------------------------------------

    /**
     * Lot size = (balance × risk%) / (SL_pips × pip_value_per_lot).
     * Clamped to [MIN_LOT, MAX_LOT] and rounded to 2 decimal places.
     */
    double calculateLotSize() {
        double riskAmount = accountBalance * (riskPercent / 100.0);
        double rawLot = riskAmount / (stopLossPips * PIP_VALUE_PER_LOT);
        double lots = Math.round(rawLot * 100.0) / 100.0;   // 2 d.p.
        lots = Math.max(MIN_LOT, Math.min(MAX_LOT, lots));
        log.debug("Lot size: rawLot={} → clamped={}", rawLot, lots);
        return lots;
    }

    /**
     * Stop-loss placed {@code stopLossPips} pips against the trade direction.
     */
    double calculateStopLoss(double entryPrice, boolean isBuy) {
        double sl = isBuy
                ? entryPrice - stopLossPips * PIP_SIZE
                : entryPrice + stopLossPips * PIP_SIZE;
        return round5(sl);
    }

    /**
     * Take-profit placed at {@code stopLossPips × rewardRatio} pips in the trade direction.
     */
    double calculateTakeProfit(double entryPrice, boolean isBuy) {
        double tpDistance = stopLossPips * rewardRatio * PIP_SIZE;
        double tp = isBuy ? entryPrice + tpDistance : entryPrice - tpDistance;
        return round5(tp);
    }

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    private static double round5(double value) {
        return Math.round(value * 100_000.0) / 100_000.0;
    }

    // Setters for testing / dynamic reconfiguration
    public void setAccountBalance(double accountBalance) {
        this.accountBalance = accountBalance;
    }

    public void setRiskPercent(double riskPercent) {
        this.riskPercent = riskPercent;
    }

    public void setStopLossPips(double stopLossPips) {
        this.stopLossPips = stopLossPips;
    }

    public void setRewardRatio(double rewardRatio) {
        this.rewardRatio = rewardRatio;
    }
}
