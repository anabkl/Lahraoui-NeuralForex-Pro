# Lahraoui-NeuralForex-Pro

Academic microservices project for EUR/USD prediction, risk calculation, backtesting, and monitoring.

This project is intentionally safe by default: market data runs in demo mode, sentiment runs in demo mode, and the Java executor only logs simulated orders. It does not place real-money trades.

## Project Overview

Lahraoui-NeuralForex-Pro combines four small services:

- `brain-python`: FastAPI service that exposes EUR/USD ticks, history, sentiment, and prediction endpoints.
- `executor-java`: Spring Boot service that checks the Brain health endpoint, reads predictions, calculates risk, and logs simulated orders.
- `backtest-engine-php`: PHP CLI backtester for historical or synthetic EUR/USD candles.
- `monitor-ui`: Nginx-hosted dashboard using Vanilla JS and Chart.js.
- `postgres`: PostgreSQL database initialized with tables for future trade, prediction, sentiment, and heartbeat logs.

## Architecture

```text
Browser
  |
  v
monitor-ui (Nginx, port 3000)
  |-- /api/* -------> brain-python (FastAPI, port 8000)
  |                    |-- demo/live EUR/USD ticks
  |                    |-- demo/live sentiment
  |                    `-- AI/stub prediction endpoint
  |
  `-- /executor/* --> executor-java (Spring Boot, port 8080)
                       |-- heartbeat: brain-python /health
                       |-- risk manager
                       `-- simulation-only order logging

backtest-engine-php (one-shot CLI)
  `-- reads CSV from ./data or generates synthetic demo candles

postgres (port 5432)
  `-- schema from sql/init.sql
```

## macOS Setup

1. Install Docker Desktop for Mac and start it.
2. Open a terminal in the repository folder.
3. Optional: copy `.env.example` to `.env` and change ports or credentials.

```bash
cd "/Users/info/Desktop/Projet 1/Lahraoui-NeuralForex-Pro"
cp .env.example .env
docker compose up --build
```

Open the dashboard:

```text
http://localhost:3000
```

If port `3000`, `8000`, `8080`, or `5432` is already busy, edit `.env`:

```env
MONITOR_HOST_PORT=3001
BRAIN_HOST_PORT=8001
EXECUTOR_HOST_PORT=8081
POSTGRES_HOST_PORT=5433
```

## Docker Commands

```bash
# Build and start the full stack
docker compose up --build

# Start in the background
docker compose up --build -d

# See service status
docker compose ps

# Follow logs
docker compose logs -f brain-python executor-java monitor-ui

# Run only the PHP backtest
docker compose run --rm backtest-engine-php

# Stop and remove containers
docker compose down

# Stop and also remove named volumes
docker compose down -v
```

## Verification

After starting the stack in the background:

```bash
python3 scripts/smoke_test.py
```

Useful manual checks:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/predict
curl http://localhost:8080/status
curl http://localhost:3000/nginx-health
```

## Endpoints

Brain service:

- `GET /health`: Brain health and active demo/live modes.
- `GET /ticks/latest`: latest EUR/USD bid/ask tick.
- `GET /ticks/history?bars=200`: recent OHLC candles with RSI, MACD, and OFI.
- `GET /predict`: prediction payload with `BUY`, `HOLD`, or `SELL`.
- `GET /sentiment`: FED/ECB sentiment summary.
- `GET /docs`: FastAPI Swagger UI.

Executor service:

- `GET /health`: executor liveness.
- `GET /status`: execution mode and Brain heartbeat state.

Monitor UI:

- `GET /`: dashboard.
- `GET /nginx-health`: Nginx health check.
- `/api/*`: proxy to Brain.
- `/executor/*`: proxy to Executor.

## Environment Variables

See `.env.example` for the full list. The most important ones are:

- `MARKET_DATA_MODE=demo|twelvedata`
- `TWELVE_DATA_API_KEY=...`
- `SENTIMENT_MODE=demo|live`
- `EXECUTION_MODE=SIMULATION`
- `ACCOUNT_BALANCE`, `RISK_PERCENT`, `STOP_LOSS_PIPS`, `REWARD_RATIO`
- `BRAIN_HOST_PORT`, `EXECUTOR_HOST_PORT`, `MONITOR_HOST_PORT`, `POSTGRES_HOST_PORT`
- `BACKTEST_DATA_FILE`, `BACKTEST_SYNTHETIC_BARS`

## Backtesting Data

By default, Docker looks for:

```text
./data/eur_usd_1min_7days15-04_to_21-4.csv
```

If the file is not present, the PHP service generates a small synthetic dataset so the project still runs locally and in CI. To use a larger historical file, place it under `./data` and set:

```env
BACKTEST_DATA_FILE=/app/data/your-file.csv
```

Expected CSV columns:

```text
timestamp,open,high,low,close,volume
```

The `volume` column is optional.

## Troubleshooting

Docker cannot bind a port:

- Change the matching `*_HOST_PORT` value in `.env`.
- Run `docker compose down` to stop older containers from this project.

Brain is healthy but predictions are always `HOLD`:

- This is expected in demo mode or when TensorFlow weights are not installed.
- The API stays stable and returns a safe stub prediction until a trained model is added.

Dashboard shows executor as waiting:

- Give the Java service a few seconds to finish startup and heartbeat the Brain.
- Check `docker compose logs -f executor-java`.

Live Twelve Data calls fail:

- Keep `MARKET_DATA_MODE=demo` for offline work.
- For live data, set `MARKET_DATA_MODE=twelvedata` and provide `TWELVE_DATA_API_KEY`.

Backtest uses synthetic data:

- The configured CSV was not found inside the container.
- Check `BACKTEST_DATA_FILE` and confirm the file exists under `./data`.

## Security And Safety Notes

- No API keys are committed. Use `.env` for local secrets.
- `.env` is ignored by Git.
- Real broker execution is not implemented. `EXECUTION_MODE=SIMULATION` is the supported mode.
- Do not connect this project to a funded trading account without a separate broker gateway, strict risk controls, audit logging, and legal/compliance review.

## TODO For Real MT5/XM Integration

- Build a separate broker adapter service or MT5 Expert Advisor bridge.
- Add broker authentication through secrets management, not plain `.env` in production.
- Persist simulated and live orders to PostgreSQL with idempotency keys.
- Add account/equity synchronization and max daily loss limits.
- Add slippage, spread, market-hours, and rejected-order handling.
- Add integration tests against a demo account only.
- Add human approval controls before any live order path is enabled.
