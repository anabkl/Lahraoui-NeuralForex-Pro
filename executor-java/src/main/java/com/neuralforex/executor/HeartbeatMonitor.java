package com.neuralforex.executor;

import com.fasterxml.jackson.databind.ObjectMapper;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.time.Instant;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/**
 * HeartbeatMonitor – periodically pings the Python Brain service
 * and pauses order execution when the brain becomes unreachable.
 *
 * <p>Schedule: every {@code heartbeat.interval_ms} milliseconds (default 5 s).
 * After {@code heartbeat.max_failures} consecutive failures (default 3)
 * the {@link #isBrainHealthy()} flag is set to {@code false} and all
 * order-execution logic should check this flag before placing trades.
 */
@Component
public class HeartbeatMonitor {

    private static final Logger log = LoggerFactory.getLogger(HeartbeatMonitor.class);

    @Value("${brain.service.url:http://brain-python:8000}")
    private String brainServiceUrl;

    @Value("${heartbeat.max_failures:3}")
    private int maxConsecutiveFailures;

    @Value("${heartbeat.timeout_seconds:3}")
    private int timeoutSeconds;

    private final OkHttpClient httpClient;
    private final ObjectMapper objectMapper;

    /** Whether the brain service is currently reachable. */
    private final AtomicBoolean brainHealthy = new AtomicBoolean(true);

    /** Count of consecutive failed heartbeat calls. */
    private final AtomicInteger consecutiveFailures = new AtomicInteger(0);

    /** Epoch-millis timestamp of the last successful heartbeat. */
    private final AtomicLong lastSuccessMs = new AtomicLong(0L);

    public HeartbeatMonitor() {
        this.httpClient = new OkHttpClient.Builder()
                .connectTimeout(3, TimeUnit.SECONDS)
                .readTimeout(3, TimeUnit.SECONDS)
                .build();
        this.objectMapper = new ObjectMapper();
    }

    // -------------------------------------------------------------------------
    // Scheduled heartbeat
    // -------------------------------------------------------------------------

    /**
     * Fires every 5 seconds (configurable via {@code heartbeat.interval_ms}).
     * Sends a GET /health request to the Brain service and updates health state.
     */
    @Scheduled(fixedDelayString = "${heartbeat.interval_ms:5000}")
    public void ping() {
        String url = brainServiceUrl + "/health";
        Request request = new Request.Builder()
                .url(url)
                .get()
                .build();

        try (Response response = httpClient.newCall(request).execute()) {
            if (response.isSuccessful()) {
                onHeartbeatSuccess();
            } else {
                onHeartbeatFailure(
                        new IOException("Brain returned HTTP " + response.code()));
            }
        } catch (IOException e) {
            onHeartbeatFailure(e);
        }
    }

    // -------------------------------------------------------------------------
    // State transitions
    // -------------------------------------------------------------------------

    private void onHeartbeatSuccess() {
        lastSuccessMs.set(System.currentTimeMillis());
        consecutiveFailures.set(0);

        if (!brainHealthy.getAndSet(true)) {
            // Recovered from unhealthy state
            log.info("Brain service RECOVERED at {}", Instant.now());
        } else {
            log.debug("Heartbeat OK – brain service healthy");
        }
    }

    private void onHeartbeatFailure(Exception cause) {
        int failures = consecutiveFailures.incrementAndGet();
        log.warn("Heartbeat FAILED (attempt {}/{}): {}", failures, maxConsecutiveFailures, cause.getMessage());

        if (failures >= maxConsecutiveFailures) {
            if (brainHealthy.getAndSet(false)) {
                log.error(
                        "Brain service UNHEALTHY after {} consecutive failures. "
                                + "Order execution is PAUSED until recovery.",
                        failures);
            }
        }
    }

    // -------------------------------------------------------------------------
    // Public accessors
    // -------------------------------------------------------------------------

    /**
     * Returns {@code true} if the brain service is reachable.
     * Order execution should be blocked when this returns {@code false}.
     */
    public boolean isBrainHealthy() {
        return brainHealthy.get();
    }

    /**
     * Epoch-millisecond timestamp of the last successful heartbeat.
     * Returns {@code 0} if no successful ping has occurred yet.
     */
    public long getLastSuccessMs() {
        return lastSuccessMs.get();
    }

    /** Number of consecutive failures since last recovery. */
    public int getConsecutiveFailures() {
        return consecutiveFailures.get();
    }
}
