/**
 * monitor-ui/js/dashboard.js
 * ===========================
 * Lahraoui-NeuralForex-Pro – Real-Time Dashboard
 *
 * Polls the Python Brain service REST API and updates:
 *   • Live price chart (actual bid vs. AI mid-price prediction)
 *   • FED / ECB sentiment bar chart
 *   • BUY / HOLD / SELL confidence doughnut chart
 *   • Stat cards (bid, ask, signal, confidence, sentiment biases)
 *   • Live trade log table
 *
 * Configuration is at the top of the file.
 */

'use strict';

// ─── Configuration ────────────────────────────────────────────────────────────
const CONFIG = {
  brainUrl:          window.BRAIN_URL || '/api',
  executorUrl:       window.EXECUTOR_URL || '/executor',
  tickInterval:      2_000,   // ms – how often to fetch latest tick
  predInterval:      10_000,  // ms – how often to fetch prediction
  executorInterval:  10_000,  // ms – how often to fetch executor status
  sentimentInterval: 60_000,  // ms – how often to fetch sentiment
  maxPricePoints:    120,     // bars visible on the price chart
};

// ─── State ────────────────────────────────────────────────────────────────────
const state = {
  priceLabels:     [],
  actualPrices:    [],
  predPrices:      [],
  sentimentFed:    0,
  sentimentEcb:    0,
  probBuy:         0.333,
  probHold:        0.334,
  probSell:        0.333,
  sessionPnl:      0,
  currentSignal:   'HOLD',
  currentConf:     0,
  tradeLog:        [],
};

// ─── DOM references ───────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const elBid          = $('bid');
const elAsk          = $('ask');
const elSignal       = $('ai-signal');
const elConf         = $('confidence');
const elFedSentiment = $('fed-sentiment');
const elEcbSentiment = $('ecb-sentiment');
const elEurUsdBias   = $('eurusd-bias');
const elExecutor     = $('executor-status');
const elSessionPnl   = $('session-pnl');
const elStatusDot    = $('status-dot');
const elStatusText   = $('status-text');
const elClock        = $('clock');
const elLogBody      = $('log-body');

// ─── Clock ────────────────────────────────────────────────────────────────────
function updateClock() {
  elClock.textContent = new Date().toLocaleTimeString('en-GB', { hour12: false });
}
setInterval(updateClock, 1000);
updateClock();

// ─── Chart initialisation ─────────────────────────────────────────────────────

// 1. Price chart
const priceChart = new Chart($('price-chart').getContext('2d'), {
  type: 'line',
  data: {
    labels: state.priceLabels,
    datasets: [
      {
        label: 'Actual Price',
        data: state.actualPrices,
        borderColor: '#00d4aa',
        backgroundColor: 'rgba(0,212,170,0.06)',
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.3,
        fill: true,
      },
      {
        label: 'AI Prediction',
        data: state.predPrices,
        borderColor: '#ffd166',
        backgroundColor: 'transparent',
        borderWidth: 1.5,
        borderDash: [4, 4],
        pointRadius: 0,
        tension: 0.3,
      },
    ],
  },
  options: {
    responsive: true,
    animation: false,
    interaction: { mode: 'index', intersect: false },
    plugins: { legend: { labels: { color: '#6b7fa3', font: { size: 11 } } } },
    scales: {
      x: { ticks: { color: '#6b7fa3', maxTicksLimit: 8 }, grid: { color: '#1e2535' } },
      y: {
        ticks: { color: '#6b7fa3', callback: v => v.toFixed(5) },
        grid: { color: '#1e2535' },
      },
    },
  },
});

// 2. Sentiment chart
const sentimentChart = new Chart($('sentiment-chart').getContext('2d'), {
  type: 'bar',
  data: {
    labels: ['FED (USD)', 'ECB (EUR)'],
    datasets: [{
      label: 'Hawkish (+) / Dovish (−)',
      data: [state.sentimentFed, state.sentimentEcb],
      backgroundColor: ['rgba(0,212,170,0.5)', 'rgba(255,107,107,0.5)'],
      borderColor:     ['#00d4aa', '#ff6b6b'],
      borderWidth: 1.5,
      borderRadius: 4,
    }],
  },
  options: {
    responsive: true,
    animation: { duration: 400 },
    plugins: { legend: { display: false } },
    scales: {
      x: { ticks: { color: '#6b7fa3' }, grid: { color: '#1e2535' } },
      y: {
        min: -1, max: 1,
        ticks: { color: '#6b7fa3' },
        grid: { color: '#1e2535' },
      },
    },
  },
});

// 3. Confidence doughnut
const confidenceChart = new Chart($('confidence-chart').getContext('2d'), {
  type: 'doughnut',
  data: {
    labels: ['BUY', 'HOLD', 'SELL'],
    datasets: [{
      data: [state.probBuy, state.probHold, state.probSell],
      backgroundColor: ['rgba(34,197,94,0.8)', 'rgba(255,209,102,0.8)', 'rgba(239,68,68,0.8)'],
      borderColor:     ['#22c55e', '#ffd166', '#ef4444'],
      borderWidth: 1.5,
    }],
  },
  options: {
    responsive: true,
    animation: { duration: 400 },
    plugins: {
      legend: { labels: { color: '#6b7fa3', font: { size: 11 } } },
    },
    cutout: '65%',
  },
});

// ─── API helpers ──────────────────────────────────────────────────────────────

function timeoutSignal(ms) {
  return 'timeout' in AbortSignal ? AbortSignal.timeout(ms) : undefined;
}

async function apiFetch(path, baseUrl = CONFIG.brainUrl) {
  const resp = await fetch(`${baseUrl}${path}`, { signal: timeoutSignal(5000) });
  if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${path}`);
  return resp.json();
}

function setConnectionStatus(healthy) {
  elStatusDot.className = healthy ? 'healthy' : '';
  elStatusText.textContent = healthy ? 'Connected' : 'Disconnected';
}

// ─── Tick poll ────────────────────────────────────────────────────────────────

async function fetchTick() {
  try {
    const tick = await apiFetch('/ticks/latest');
    const time = new Date().toLocaleTimeString('en-GB', { hour12: false });
    const mid  = ((tick.bid || 0) + (tick.ask || 0)) / 2;

    elBid.textContent = (tick.bid || 0).toFixed(5);
    elAsk.textContent = (tick.ask || 0).toFixed(5);

    // Append to price chart
    state.priceLabels.push(time);
    state.actualPrices.push(mid);

    // Keep window size bounded
    if (state.priceLabels.length > CONFIG.maxPricePoints) {
      state.priceLabels.shift();
      state.actualPrices.shift();
      state.predPrices.shift();
    }

    priceChart.update('none');
    setConnectionStatus(true);
  } catch (err) {
    console.warn('[Tick] fetch failed:', err.message);
    setConnectionStatus(false);
  }
}

// ─── Prediction poll ──────────────────────────────────────────────────────────

async function fetchPrediction() {
  try {
    const pred = await apiFetch('/predict');

    state.currentSignal = pred.signal || 'HOLD';
    state.currentConf   = pred.confidence || 0;
    state.probBuy       = pred.probabilities?.BUY  ?? 0.333;
    state.probHold      = pred.probabilities?.HOLD ?? 0.334;
    state.probSell      = pred.probabilities?.SELL ?? 0.333;

    // Update signal card
    elSignal.textContent  = state.currentSignal;
    elSignal.className    = 'card-value ' + signalClass(state.currentSignal);
    elConf.textContent    = (state.currentConf * 100).toFixed(1) + '%';
    elConf.className      = 'card-value ' + (state.currentConf >= 0.6 ? 'positive' : 'neutral');

    // Add a synthetic prediction point on price chart (current actual ± 1 pip directional bias)
    const lastActual = state.actualPrices[state.actualPrices.length - 1];
    if (lastActual != null) {
      const direction = state.currentSignal === 'BUY' ? 1 : state.currentSignal === 'SELL' ? -1 : 0;
      const predPrice = lastActual + direction * 0.0001 * state.currentConf;
      // Pad prediction array to match actual
      while (state.predPrices.length < state.actualPrices.length - 1) {
        state.predPrices.push(null);
      }
      state.predPrices.push(parseFloat(predPrice.toFixed(5)));
      priceChart.update('none');
    }

    // Update confidence doughnut
    confidenceChart.data.datasets[0].data = [state.probBuy, state.probHold, state.probSell];
    confidenceChart.update();

    // Add to trade log if signal is actionable
    if (state.currentSignal !== 'HOLD' && state.currentConf >= 0.60) {
      addLogEntry({
        time:   new Date().toLocaleTimeString('en-GB', { hour12: false }),
        signal: state.currentSignal,
        entry:  (state.actualPrices[state.actualPrices.length - 1] || 0).toFixed(5),
        lot:    '0.10',
        sl:     '—',
        tp:     '—',
        pnl:    '—',
        status: 'OPEN',
      });
    }
  } catch (err) {
    console.warn('[Prediction] fetch failed:', err.message);
  }
}

// ─── Sentiment poll ───────────────────────────────────────────────────────────

async function fetchSentiment() {
  try {
    const sent = await apiFetch('/sentiment');

    state.sentimentFed = sent.FED?.score ?? 0;
    state.sentimentEcb = sent.ECB?.score ?? 0;

    elFedSentiment.textContent = biasLabel(sent.FED?.bias);
    elFedSentiment.className   = 'card-value ' + biasClass(sent.FED?.bias);

    elEcbSentiment.textContent = biasLabel(sent.ECB?.bias);
    elEcbSentiment.className   = 'card-value ' + biasClass(sent.ECB?.bias);

    elEurUsdBias.textContent = biasLabel(sent.composite?.EURUSD_signal);
    elEurUsdBias.className   = 'card-value ' + biasClass(sent.composite?.EURUSD_signal);

    sentimentChart.data.datasets[0].data = [state.sentimentFed, state.sentimentEcb];
    sentimentChart.update();
  } catch (err) {
    console.warn('[Sentiment] fetch failed:', err.message);
  }
}

// ─── Executor status poll ───────────────────────────────────────────────────

async function fetchExecutorStatus() {
  try {
    const status = await apiFetch('/status', CONFIG.executorUrl);
    const healthy = Boolean(status.brainHealthy);
    elExecutor.textContent = healthy ? status.executionMode || 'SIMULATION' : 'Waiting';
    elExecutor.className = 'card-value ' + (healthy ? 'positive' : 'neutral');
  } catch (err) {
    console.warn('[Executor] status fetch failed:', err.message);
    elExecutor.textContent = 'Offline';
    elExecutor.className = 'card-value negative';
  }
}

// ─── Trade log ────────────────────────────────────────────────────────────────

const MAX_LOG_ROWS = 50;

function addLogEntry(entry) {
  state.tradeLog.unshift(entry);
  if (state.tradeLog.length > MAX_LOG_ROWS) state.tradeLog.pop();
  renderLog();
}

function renderLog() {
  elLogBody.innerHTML = state.tradeLog.map(row => `
    <tr>
      <td>${row.time}</td>
      <td class="log-${row.signal.toLowerCase()}">${row.signal}</td>
      <td>${row.entry}</td>
      <td>${row.lot}</td>
      <td>${row.sl}</td>
      <td>${row.tp}</td>
      <td class="${pnlClass(row.pnl)}">${row.pnl}</td>
      <td>${row.status}</td>
    </tr>`).join('');
}

// ─── Utility functions ────────────────────────────────────────────────────────

function signalClass(signal) {
  if (signal === 'BUY')  return 'positive';
  if (signal === 'SELL') return 'negative';
  return 'neutral';
}

function biasClass(bias) {
  if (bias === 'hawkish') return 'positive';
  if (bias === 'dovish')  return 'negative';
  return 'neutral';
}

function biasLabel(bias) {
  if (!bias) return '—';
  return bias.charAt(0).toUpperCase() + bias.slice(1);
}

function pnlClass(pnl) {
  if (pnl === '—' || pnl === undefined) return '';
  const v = parseFloat(pnl);
  return isNaN(v) ? '' : v >= 0 ? 'log-pnl-pos' : 'log-pnl-neg';
}

// ─── Polling loop ─────────────────────────────────────────────────────────────

fetchTick();
fetchPrediction();
fetchSentiment();
fetchExecutorStatus();

setInterval(fetchTick,       CONFIG.tickInterval);
setInterval(fetchPrediction, CONFIG.predInterval);
setInterval(fetchSentiment,  CONFIG.sentimentInterval);
setInterval(fetchExecutorStatus, CONFIG.executorInterval);
