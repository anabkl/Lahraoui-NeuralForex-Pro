package com.neuralforex.executor;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for RiskManager lot-size and SL/TP calculations.
 */
class RiskManagerTest {

    private RiskManager riskManager;

    @BeforeEach
    void setUp() {
        riskManager = new RiskManager();
        riskManager.setAccountBalance(10_000.0);
        riskManager.setRiskPercent(1.0);
        riskManager.setStopLossPips(20.0);
        riskManager.setRewardRatio(2.0);
    }

    // --- Lot size ---

    @Test
    void testLotSize_standardParams() {
        // risk = 10000 * 0.01 = 100; lots = 100 / (20 * 10) = 0.50
        assertEquals(0.50, riskManager.calculateLotSize(), 0.001);
    }

    @Test
    void testLotSize_clampedToMin() {
        riskManager.setAccountBalance(100.0);
        riskManager.setRiskPercent(0.01);
        // raw = 100 * 0.0001 / (20 * 10) = 0.00005 → clamped to MIN_LOT 0.01
        assertEquals(0.01, riskManager.calculateLotSize(), 0.001);
    }

    @Test
    void testLotSize_clampedToMax() {
        riskManager.setAccountBalance(100_000_000.0);
        // raw lot would be enormous → clamped to 10.0
        assertEquals(10.0, riskManager.calculateLotSize(), 0.001);
    }

    // --- Stop-loss ---

    @Test
    void testStopLoss_buy() {
        double entry = 1.08500;
        double sl = riskManager.calculateStopLoss(entry, true);
        // SL = 1.08500 - 20 * 0.0001 = 1.08300
        assertEquals(1.08300, sl, 1e-5);
    }

    @Test
    void testStopLoss_sell() {
        double entry = 1.08500;
        double sl = riskManager.calculateStopLoss(entry, false);
        // SL = 1.08500 + 20 * 0.0001 = 1.08700
        assertEquals(1.08700, sl, 1e-5);
    }

    // --- Take-profit ---

    @Test
    void testTakeProfit_buy() {
        double entry = 1.08500;
        double tp = riskManager.calculateTakeProfit(entry, true);
        // TP = 1.08500 + 20 * 2 * 0.0001 = 1.08900
        assertEquals(1.08900, tp, 1e-5);
    }

    @Test
    void testTakeProfit_sell() {
        double entry = 1.08500;
        double tp = riskManager.calculateTakeProfit(entry, false);
        // TP = 1.08500 - 20 * 2 * 0.0001 = 1.08100
        assertEquals(1.08100, tp, 1e-5);
    }

    // --- calculateOrder ---

    @Test
    void testCalculateOrder_buySignal() {
        TradingSignal signal = new TradingSignal("BUY", 0.75, 1.08510, 1.08500);
        TradeOrder order = riskManager.calculateOrder(signal);

        assertEquals("BUY", order.getDirection());
        assertEquals(1.08510, order.getEntryPrice(), 1e-5);
        assertTrue(order.getLotSize() > 0);
        assertTrue(order.getStopLoss() < order.getEntryPrice());
        assertTrue(order.getTakeProfit() > order.getEntryPrice());
    }

    @Test
    void testCalculateOrder_holdSignalThrows() {
        TradingSignal signal = new TradingSignal("HOLD", 0.0, 1.085, 1.084);
        assertThrows(IllegalArgumentException.class, () -> riskManager.calculateOrder(signal));
    }
}
