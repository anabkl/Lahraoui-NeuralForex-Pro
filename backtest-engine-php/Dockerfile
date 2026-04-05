# backtest-engine-php/Dockerfile
FROM php:8.3-cli-alpine

LABEL maintainer="Anas Lahraoui <lahraoui.forex@example.com>"
LABEL description="NeuralForex-Pro Backtest Engine – PHP historical data backtester"

WORKDIR /app

# Create data and results directories
RUN mkdir -p /app/data /app/results

COPY backtest.php .

# Default command: run the backtest and print results
CMD ["php", "backtest.php"]
