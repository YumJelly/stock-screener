/**
 * Chip (籌碼) analysis API endpoints.
 */
import apiClient from './client';

const BASE_PATH = '/v1/chip';

/**
 * Upload a broker-branch (分點) CSV for synchronous chip analysis.
 * @param {File} file - The CSV file (TPEX/TWSE, UTF-8 or Big5).
 * @param {Object} [opts] - Optional overrides.
 * @param {string} [opts.market] - 'TWSE' | 'TPEX' (auto-detected if omitted).
 * @returns {Promise<Object>} Analysis result.
 */
export const analyzeChipCsv = async (file, opts = {}) => {
  const form = new FormData();
  form.append('file', file);
  if (opts.market) form.append('market', opts.market);
  if (opts.open_price != null) form.append('open_price', opts.open_price);
  if (opts.high_price != null) form.append('high_price', opts.high_price);
  if (opts.low_price != null) form.append('low_price', opts.low_price);
  if (opts.close_price != null) form.append('close_price', opts.close_price);
  if (opts.prev_close != null) form.append('prev_close', opts.prev_close);

  const response = await apiClient.post(`${BASE_PATH}/analyze`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
};

/**
 * Auto-fetch broker-branch data then analyze (TWSE OCR / TPEX Playwright).
 * @param {string} symbol - Stock code (e.g. "2330" or "5483").
 * @param {string} [market] - 'TWSE' | 'TPEX' (auto-detected server-side if omitted).
 * @returns {Promise<Object>} Analysis result.
 */
export const analyzeChipAuto = async (symbol, market) => {
  const params = market ? { market } : {};
  const response = await apiClient.post(
    `${BASE_PATH}/analyze-auto/${encodeURIComponent(symbol)}`,
    null,
    { params },
  );
  return response.data;
};

/**
 * Debug: fetch TPEX (上櫃) broker-branch rows via Playwright (no LLM, no DB write).
 * @param {string} symbol - TPEX stock code (e.g. "5483").
 * @returns {Promise<{symbol, market, success, count, records, error}>}
 */
export const getTPEXBrokerDebug = async (symbol) => {
  const response = await apiClient.get(
    `${BASE_PATH}/tpex-debug/${encodeURIComponent(symbol)}`,
  );
  return response.data;
};

/**
 * Get the historical chip score curve for a stock.
 * @param {string} stockId - Stock code (e.g. "2330").
 * @param {number} [limit=120]
 * @returns {Promise<{stock_id: string, points: Array}>}
 */
export const getChipHistory = async (stockId, limit = 120) => {
  const response = await apiClient.get(
    `${BASE_PATH}/history/${encodeURIComponent(stockId)}`,
    { params: { limit } },
  );
  return response.data;
};

/**
 * Get single-day chip analysis detail.
 * @param {string} stockId
 * @param {string} tradeDate - YYYY-MM-DD
 * @returns {Promise<Object>}
 */
export const getChipResult = async (stockId, tradeDate) => {
  const response = await apiClient.get(
    `${BASE_PATH}/result/${encodeURIComponent(stockId)}/${encodeURIComponent(tradeDate)}`,
  );
  return response.data;
};

/**
 * Build the URL for the broker-branch (分點) T-chart PNG.
 * Returns an absolute/relative URL suitable for an <img src>.
 * @param {string} stockId - Stock code (e.g. "2330"); market suffix is stripped server-side.
 * @param {'daily'|'cumulative'} [kind='daily']
 * @param {Object} [opts]
 * @param {string} [opts.date] - YYYY-MM-DD (daily only; latest if omitted).
 * @param {boolean} [opts.bust] - Append a cache-busting timestamp.
 * @returns {string}
 */
export const getChipChartUrl = (stockId, kind = 'daily', opts = {}) => {
  const base = (apiClient.defaults.baseURL || '').replace(/\/$/, '');
  const code = String(stockId || '').trim().toUpperCase().replace(/\.(TW|TWO)$/i, '');
  const params = new URLSearchParams({ kind });
  if (opts.date) params.set('date', opts.date);
  if (opts.bust) params.set('t', String(Date.now()));
  return `${base}${BASE_PATH}/chart/${encodeURIComponent(code)}.png?${params.toString()}`;
};

