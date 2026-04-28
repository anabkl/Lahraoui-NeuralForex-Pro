package com.neuralforex.executor;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * Small operational endpoints for Docker checks and the dashboard.
 */
@RestController
public class ExecutorStatusController {

    private final HeartbeatMonitor heartbeatMonitor;

    @Value("${execution.mode:SIMULATION}")
    private String executionMode;

    public ExecutorStatusController(HeartbeatMonitor heartbeatMonitor) {
        this.heartbeatMonitor = heartbeatMonitor;
    }

    @GetMapping("/health")
    public Map<String, Object> health() {
        return Map.of(
                "status", "ok",
                "service", "executor-java"
        );
    }

    @GetMapping("/status")
    public Map<String, Object> status() {
        return Map.of(
                "service", "executor-java",
                "executionMode", executionMode,
                "brainHealthy", heartbeatMonitor.isBrainHealthy(),
                "brainConsecutiveFailures", heartbeatMonitor.getConsecutiveFailures(),
                "brainLastSuccessMs", heartbeatMonitor.getLastSuccessMs()
        );
    }
}
