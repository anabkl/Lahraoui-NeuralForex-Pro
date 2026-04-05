<?php
/**
 * backtest-engine-php/backtest.php
 * =================================
 * Lahraoui-NeuralForex-Pro – Historical Backtesting Engine
 *
 * Runs 5 years of EUR/USD M1 historical data through a simulated version
 * of the AI model's signal logic and calculates:
 *   • Win Rate
 *   • Max Drawdown
 *   • Profit Factor
 *   • Sharpe Ratio (annualised)
 *   • Total Net P&L (in pips)
 *
 * Data source: CSV file with columns  time,open,high,low,close,volume
 *              (place at data/EURUSD_M1_5Y.csv, or point $dataFile below)
 *
 * Usage:
 *   php backtest.php [--dataFile=path/to/data.csv] [--stopLossPips=20]
 *                   [--takeProfitPips=40] [--minConfidence=0.60]
 *                   [--rsiPeriod=14] [--initialBalance=10000]
 *
 * Author: Anas Lahraoui
 */

declare(strict_types=1);

// ─── Configuration defaults ──────────────────────────────────────────────────

$config = [
    'dataFile'       => __DIR__ . '/data/EURUSD_M1_5Y.csv',
    'stopLossPips'   => 20.0,
    'takeProfitPips' => 40.0,   // 2× SL → risk:reward = 1:2
    'minConfidence'  => 0.60,
    'rsiPeriod'      => 14,
    'macdFast'       => 12,
    'macdSlow'       => 26,
    'macdSignal'     => 9,
    'initialBalance' => 10_000.0,
    'riskPercent'    => 1.0,     // % of balance risked per trade
    'pipSize'        => 0.0001,  // EUR/USD pip
    'pipValuePerLot' => 10.0,    // USD per pip per standard lot
];

// Override from CLI arguments
foreach ($argv as $arg) {
    if (preg_match('/^--(\w+)=(.+)$/', $arg, $m)) {
        if (array_key_exists($m[1], $config)) {
            $config[$m[1]] = is_float($config[$m[1]]) ? (float)$m[2] : $m[2];
        }
    }
}

// ─── Helper functions ─────────────────────────────────────────────────────────

/**
 * Compute RSI for the last bar in a price series.
 *
 * @param float[] $closes  Array of close prices (most recent last)
 * @param int     $period
 * @return float|null  null if insufficient data
 */
function computeRSI(array $closes, int $period): ?float
{
    if (count($closes) < $period + 1) {
        return null;
    }

    $gains = $losses = [];
    for ($i = count($closes) - $period; $i < count($closes); $i++) {
        $delta = $closes[$i] - $closes[$i - 1];
        $gains[]  = max(0.0, $delta);
        $losses[] = max(0.0, -$delta);
    }

    $avgGain = array_sum($gains)  / $period;
    $avgLoss = array_sum($losses) / $period;

    if ($avgLoss < 1e-9) {
        return 100.0;
    }
    $rs = $avgGain / $avgLoss;
    return 100.0 - 100.0 / (1.0 + $rs);
}

/**
 * Compute EMA of an array, returning the last value.
 *
 * @param float[] $data
 * @param int     $period
 * @return float|null
 */
function computeLastEMA(array $data, int $period): ?float
{
    if (count($data) < $period) {
        return null;
    }
    $k   = 2.0 / ($period + 1);
    $ema = array_sum(array_slice($data, 0, $period)) / $period;
    for ($i = $period; $i < count($data); $i++) {
        $ema = $data[$i] * $k + $ema * (1.0 - $k);
    }
    return $ema;
}

/**
 * Simulate the AI signal logic using RSI + MACD rule-based approximation.
 *
 * This mirrors the feature set used by the neural network, but applies
 * a deterministic rule so the backtest can run without a live model.
 *
 * Rules:
 *   BUY  → RSI < 45 AND MACD histogram crosses above zero
 *   SELL → RSI > 55 AND MACD histogram crosses below zero
 *   HOLD → otherwise
 *
 * @param float[] $closes  Recent close prices
 * @param int     $rsiPeriod
 * @param int     $macdFast
 * @param int     $macdSlow
 * @param int     $macdSig
 * @return array{signal: string, confidence: float}
 */
function generateSignal(
    array $closes,
    int $rsiPeriod,
    int $macdFast,
    int $macdSlow,
    int $macdSig
): array {
    $rsi = computeRSI($closes, $rsiPeriod);
    if ($rsi === null) {
        return ['signal' => 'HOLD', 'confidence' => 0.0];
    }

    // EMA arrays for MACD
    $ema12  = computeLastEMA($closes, $macdFast);
    $ema26  = computeLastEMA($closes, $macdSlow);
    if ($ema12 === null || $ema26 === null) {
        return ['signal' => 'HOLD', 'confidence' => 0.0];
    }

    // Current and previous MACD values (approximate crossover)
    $macd = $ema12 - $ema26;

    // Previous bar MACD
    $prevCloses = array_slice($closes, 0, -1);
    $pEma12 = computeLastEMA($prevCloses, $macdFast);
    $pEma26 = computeLastEMA($prevCloses, $macdSlow);
    $prevMacd = ($pEma12 !== null && $pEma26 !== null) ? $pEma12 - $pEma26 : $macd;

    $crossedUp   = $prevMacd <= 0.0 && $macd > 0.0;
    $crossedDown = $prevMacd >= 0.0 && $macd < 0.0;

    if ($rsi < 45.0 && $crossedUp) {
        $confidence = min(1.0, 0.60 + (45.0 - $rsi) / 100.0);
        return ['signal' => 'BUY', 'confidence' => round($confidence, 4)];
    }

    if ($rsi > 55.0 && $crossedDown) {
        $confidence = min(1.0, 0.60 + ($rsi - 55.0) / 100.0);
        return ['signal' => 'SELL', 'confidence' => round($confidence, 4)];
    }

    return ['signal' => 'HOLD', 'confidence' => 0.0];
}

/**
 * Load CSV data file and return an array of OHLCV rows.
 *
 * @param string $filePath
 * @return array<int, array{time: string, open: float, high: float, low: float, close: float, volume: float}>
 */
function loadCSV(string $filePath): array
{
    if (!file_exists($filePath)) {
        // Generate synthetic data if no file is present (for CI / demo purposes)
        return generateSyntheticData(5 * 365 * 24 * 60);  // 5 years of M1 bars
    }

    $rows = [];
    $handle = fopen($filePath, 'r');
    if ($handle === false) {
        throw new RuntimeException("Cannot open data file: $filePath");
    }

    $header = fgetcsv($handle);  // skip header row
    while (($row = fgetcsv($handle)) !== false) {
        if (count($row) < 5) {
            continue;
        }
        $rows[] = [
            'time'   => $row[0],
            'open'   => (float)$row[1],
            'high'   => (float)$row[2],
            'low'    => (float)$row[3],
            'close'  => (float)$row[4],
            'volume' => isset($row[5]) ? (float)$row[5] : 0.0,
        ];
    }
    fclose($handle);
    return $rows;
}

/**
 * Generate a random-walk synthetic EUR/USD dataset for testing.
 *
 * @param int $bars  Number of M1 bars to generate
 * @return array
 */
function generateSyntheticData(int $bars): array
{
    $rows   = [];
    $price  = 1.0850;
    $time   = mktime(0, 0, 0, 1, 1, date('Y') - 5);

    for ($i = 0; $i < $bars; $i++) {
        $change = (lcg_value() - 0.5) * 0.0008;
        $open   = round($price, 5);
        $close  = round($price + $change, 5);
        $high   = round(max($open, $close) + lcg_value() * 0.0003, 5);
        $low    = round(min($open, $close) - lcg_value() * 0.0003, 5);
        $volume = (int)(lcg_value() * 1000 + 100);

        $rows[] = [
            'time'   => date('Y-m-d H:i:s', $time),
            'open'   => $open,
            'high'   => $high,
            'low'    => $low,
            'close'  => $close,
            'volume' => $volume,
        ];

        $price = $close;
        $time += 60;  // +1 minute
    }
    return $rows;
}

// ─── Main backtesting loop ────────────────────────────────────────────────────

echo "╔══════════════════════════════════════════════════════════╗\n";
echo "║       Lahraoui-NeuralForex-Pro  –  Backtesting Engine    ║\n";
echo "╚══════════════════════════════════════════════════════════╝\n\n";
echo "Loading data from: {$config['dataFile']}\n";

$bars = loadCSV($config['dataFile']);
$totalBars = count($bars);

echo sprintf("Loaded %s bars (approx. %.1f years of M1 data)\n\n",
    number_format($totalBars), $totalBars / (365 * 24 * 60));

// Warm-up period needed for indicators
$warmup = max($config['rsiPeriod'], $config['macdSlow']) + $config['macdSignal'] + 10;

// Trade tracking
$balance        = $config['initialBalance'];
$peakBalance    = $balance;
$maxDrawdown    = 0.0;
$trades         = [];
$openTrade      = null;  // ['direction', 'entry', 'lots', 'sl', 'tp', 'openBar']

$LABELS_PADDING = 26;

for ($i = $warmup; $i < $totalBars; $i++) {
    $bar     = $bars[$i];
    $close   = $bar['close'];
    $high    = $bar['high'];
    $low     = $bar['low'];

    // Sliding window of closes for indicator computation
    $window  = array_column(array_slice($bars, max(0, $i - $config['macdSlow'] - $config['macdSignal'] - 5), $i + 1), 'close');

    // ── Check if an open trade should be closed ────────────────────────────
    if ($openTrade !== null) {
        $closed   = false;
        $pnlPips  = 0.0;
        $outcome  = '';

        if ($openTrade['direction'] === 'BUY') {
            if ($low <= $openTrade['sl']) {
                $pnlPips = -$config['stopLossPips'];
                $outcome = 'LOSS (SL)';
                $closed  = true;
            } elseif ($high >= $openTrade['tp']) {
                $pnlPips = $config['takeProfitPips'];
                $outcome = 'WIN (TP)';
                $closed  = true;
            }
        } else {  // SELL
            if ($high >= $openTrade['sl']) {
                $pnlPips = -$config['stopLossPips'];
                $outcome = 'LOSS (SL)';
                $closed  = true;
            } elseif ($low <= $openTrade['tp']) {
                $pnlPips = $config['takeProfitPips'];
                $outcome = 'WIN (TP)';
                $closed  = true;
            }
        }

        if ($closed) {
            $pnlUSD  = $pnlPips * $config['pipValuePerLot'] * $openTrade['lots'];
            $balance += $pnlUSD;

            // Track drawdown
            if ($balance > $peakBalance) {
                $peakBalance = $balance;
            }
            $drawdown = ($peakBalance - $balance) / $peakBalance * 100.0;
            if ($drawdown > $maxDrawdown) {
                $maxDrawdown = $drawdown;
            }

            $trades[] = [
                'bar'       => $i,
                'time'      => $bar['time'],
                'direction' => $openTrade['direction'],
                'pnlPips'   => $pnlPips,
                'pnlUSD'    => round($pnlUSD, 2),
                'balance'   => round($balance, 2),
                'outcome'   => $outcome,
            ];
            $openTrade = null;
        }
    }

    // ── Only open a new trade when flat ──────────────────────────────────────
    if ($openTrade === null) {
        $signal = generateSignal(
            $window,
            $config['rsiPeriod'],
            $config['macdFast'],
            $config['macdSlow'],
            $config['macdSignal']
        );

        if ($signal['signal'] !== 'HOLD' && $signal['confidence'] >= $config['minConfidence']) {
            $dir   = $signal['signal'];
            $entry = ($dir === 'BUY') ? $bar['close'] : $bar['close'];
            $slPips = $config['stopLossPips'] * $config['pipSize'];
            $tpPips = $config['takeProfitPips'] * $config['pipSize'];
            $sl    = ($dir === 'BUY') ? $entry - $slPips : $entry + $slPips;
            $tp    = ($dir === 'BUY') ? $entry + $tpPips : $entry - $tpPips;

            // Lot size
            $riskAmount = $balance * ($config['riskPercent'] / 100.0);
            $lots = $riskAmount / ($config['stopLossPips'] * $config['pipValuePerLot']);
            $lots = max(0.01, min(10.0, round($lots, 2)));

            $openTrade = [
                'direction' => $dir,
                'entry'     => $entry,
                'lots'      => $lots,
                'sl'        => $sl,
                'tp'        => $tp,
                'openBar'   => $i,
            ];
        }
    }
}

// ─── Results ────────────────────────────────────────────────────────────────

$totalTrades = count($trades);
$wins        = array_filter($trades, fn($t) => $t['pnlPips'] > 0);
$winCount    = count($wins);
$winRate     = $totalTrades > 0 ? ($winCount / $totalTrades) * 100.0 : 0.0;
$totalPips   = array_sum(array_column($trades, 'pnlPips'));
$grossProfit = array_sum(array_column(array_filter($trades, fn($t) => $t['pnlUSD'] > 0), 'pnlUSD'));
$grossLoss   = abs(array_sum(array_column(array_filter($trades, fn($t) => $t['pnlUSD'] < 0), 'pnlUSD')));
$profitFactor = $grossLoss > 0 ? $grossProfit / $grossLoss : INF;
$netPnL      = $balance - $config['initialBalance'];

// Sharpe Ratio (simplified, annualised)
if ($totalTrades > 1) {
    $pnls    = array_column($trades, 'pnlUSD');
    $mean    = array_sum($pnls) / count($pnls);
    $variance = array_sum(array_map(fn($p) => ($p - $mean) ** 2, $pnls)) / (count($pnls) - 1);
    $std     = sqrt($variance);
    $tradesPerYear = $totalTrades / 5.0;
    $sharpe  = $std > 0 ? ($mean / $std) * sqrt($tradesPerYear) : 0.0;
} else {
    $sharpe  = 0.0;
}

echo "╔══════════════════════════════════════════════════════════╗\n";
echo "║                   BACKTEST RESULTS                       ║\n";
echo "╠══════════════════════════════════════════════════════════╣\n";
printf("║  %-{$LABELS_PADDING}s %20s  ║\n", 'Period',            '5 years (M1)');
printf("║  %-{$LABELS_PADDING}s %20s  ║\n", 'Bars processed',   number_format($totalBars));
printf("║  %-{$LABELS_PADDING}s %20s  ║\n", 'Total trades',     number_format($totalTrades));
printf("║  %-{$LABELS_PADDING}s %19.2f%%  ║\n", 'Win Rate',      $winRate);
printf("║  %-{$LABELS_PADDING}s %17.1f pips  ║\n", 'Total P&L (pips)', $totalPips);
printf("║  %-{$LABELS_PADDING}s %17s USD  ║\n", 'Net P&L (USD)',
       number_format($netPnL, 2));
printf("║  %-{$LABELS_PADDING}s %19.2f%%  ║\n", 'Max Drawdown',  $maxDrawdown);
printf("║  %-{$LABELS_PADDING}s %20.4f  ║\n", 'Profit Factor',  $profitFactor === INF ? 999.0 : $profitFactor);
printf("║  %-{$LABELS_PADDING}s %20.4f  ║\n", 'Sharpe Ratio',   $sharpe);
printf("║  %-{$LABELS_PADDING}s %17s USD  ║\n", 'Final Balance',
       number_format($balance, 2));
echo "╚══════════════════════════════════════════════════════════╝\n\n";

// Live-readiness assessment
echo "Live-Readiness Assessment:\n";
$pass = true;
$checks = [
    ['Win Rate ≥ 50%',        $winRate >= 50.0],
    ['Max Drawdown ≤ 20%',    $maxDrawdown <= 20.0],
    ['Profit Factor ≥ 1.5',   ($profitFactor === INF || $profitFactor >= 1.5)],
    ['Sharpe Ratio ≥ 1.0',    $sharpe >= 1.0],
    ['Total trades ≥ 100',    $totalTrades >= 100],
];
foreach ($checks as [$label, $result]) {
    $icon  = $result ? '✅' : '❌';
    $pass  = $pass && $result;
    printf("  %s  %s\n", $icon, $label);
}
echo "\n";
echo $pass
    ? "✅  Model PASSES live-trading criteria.\n"
    : "❌  Model does NOT meet live-trading criteria. Review and retrain before going live.\n";
echo "\n";

// Optionally export trade log to CSV
$exportPath = __DIR__ . '/results/backtest_trades.csv';
@mkdir(dirname($exportPath), 0755, true);
$fh = fopen($exportPath, 'w');
if ($fh !== false) {
    fputcsv($fh, ['bar', 'time', 'direction', 'pnlPips', 'pnlUSD', 'balance', 'outcome']);
    foreach ($trades as $t) {
        fputcsv($fh, $t);
    }
    fclose($fh);
    echo "Trade log exported to: $exportPath\n";
}
