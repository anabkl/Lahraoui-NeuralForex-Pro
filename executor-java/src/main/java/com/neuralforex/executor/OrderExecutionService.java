package com.neuralforex.executor;

import com.fasterxml.jackson.databind.ObjectMapper;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.time.Instant;
import java.util.concurrent.TimeUnit;

/**
 * OrderExecutionService – polls the Brain service for AI signals and,
 * when conditions are met, computes risk parameters and submits orders.
 *
 * <p>In a production deployment this service would forward the
 * {@link TradeOrder} to a broker API (e.g. FIX protocol, MT5 EA socket,
 * or a REST bridge). The broker integration layer is stubbed here for
 * portability.
 */
@Service
public class OrderExecutionService {

    private static final Logger log = LoggerFactory.getLogger(OrderExecutionService.class);

    /** Minimum model confidence required before placing a trade. */
    private static final double MIN_CONFIDENCE = 0.60;

    @Value("${brain.service.url:http://brain-python:8000}")
    private String brainServiceUrl;

    private final RiskManager riskManager;
    private final HeartbeatMonitor heartbeatMonitor;
    private final OkHttpClient httpClient;
    private final ObjectMapper objectMapper;

    @Autowired
    public OrderExecutionService(RiskManager riskManager, HeartbeatMonitor heartbeatMonitor) {
        this.riskManager       = riskManager;
        this.heartbeatMonitor  = heartbeatMonitor;
        this.httpClient = new OkHttpClient.Builder()
                .connectTimeout(5, TimeUnit.SECONDS)
                .readTimeout(5, TimeUnit.SECONDS)
                .build();
        this.objectMapper = new ObjectMapper();
    }

    // -------------------------------------------------------------------------
    // Scheduled trading loop
    // -------------------------------------------------------------------------

    /**
     * Runs every minute. Fetches the latest AI prediction and executes a
     * trade if the signal is actionable and the brain service is healthy.
     */
    @Scheduled(fixedDelayString = "${trading.poll_interval_ms:60000}")
    public void tradingLoop() {
        if (!heartbeatMonitor.isBrainHealthy()) {
            log.warn("Trading loop skipped – Brain service is UNHEALTHY");
            return;
        }

        try {
            TradingSignal signal = fetchSignalFromBrain();
            log.info("Received signal: {}", signal);

            if ("HOLD".equalsIgnoreCase(signal.getSignal())) {
                log.info("Signal is HOLD – no trade placed");
                return;
            }

            if (signal.getConfidence() < MIN_CONFIDENCE) {
                log.info("Confidence {} below threshold {} – skipping trade",
                        String.format("%.4f", signal.getConfidence()),
                        String.format("%.2f", MIN_CONFIDENCE));
                return;
            }

            TradeOrder order = riskManager.calculateOrder(signal);
            submitOrder(order);

        } catch (Exception e) {
            log.error("Trading loop error: {}", e.getMessage(), e);
        }
    }

    // -------------------------------------------------------------------------
    // Brain-service communication
    // -------------------------------------------------------------------------

    TradingSignal fetchSignalFromBrain() throws IOException {
        // Fetch prediction
        String predictUrl = brainServiceUrl + "/predict";
        Request predictReq = new Request.Builder().url(predictUrl).get().build();

        TradingSignal signal;
        try (Response response = httpClient.newCall(predictReq).execute()) {
            if (!response.isSuccessful()) {
                throw new IOException("Brain /predict returned HTTP " + response.code());
            }
            String body = response.body() != null ? response.body().string() : "{}";
            signal = objectMapper.readValue(body, TradingSignal.class);
        }

        // Enrich with current tick prices
        String tickUrl = brainServiceUrl + "/ticks/latest";
        Request tickReq = new Request.Builder().url(tickUrl).get().build();
        try (Response tickResp = httpClient.newCall(tickReq).execute()) {
            if (tickResp.isSuccessful() && tickResp.body() != null) {
                var node = objectMapper.readTree(tickResp.body().string());
                signal.setAsk(node.path("ask").asDouble(signal.getAsk()));
                signal.setBid(node.path("bid").asDouble(signal.getBid()));
            }
        }

        return signal;
    }

    // -------------------------------------------------------------------------
    // Order submission (broker integration stub)
    // -------------------------------------------------------------------------

    /**
     * Submit the order to the broker.
     *
     * <p><b>Stub implementation</b> – logs the order.
     * In production: replace with your broker's API call (FIX/REST/MT5).
     */
    void submitOrder(TradeOrder order) {
        log.info("SUBMITTING ORDER at {} → {}", Instant.now(), order);
        // TODO: integrate with broker REST / FIX / MT5 EA socket
        // brokerClient.placeOrder(order);
    }
}
