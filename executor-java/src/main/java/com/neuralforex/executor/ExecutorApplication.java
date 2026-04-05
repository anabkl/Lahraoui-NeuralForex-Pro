package com.neuralforex.executor;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * Lahraoui-NeuralForex-Pro – Executor Service
 *
 * <p>Entry-point for the Spring Boot application that handles:
 * <ul>
 *   <li>Order execution (BUY/SELL/CLOSE via broker API)</li>
 *   <li>Risk management (lot-sizing, stop-loss, take-profit)</li>
 *   <li>Heartbeat monitoring of the Python Brain service</li>
 *   <li>Trade logging to PostgreSQL</li>
 * </ul>
 */
@SpringBootApplication
@EnableScheduling
public class ExecutorApplication {

    public static void main(String[] args) {
        SpringApplication.run(ExecutorApplication.class, args);
    }
}
