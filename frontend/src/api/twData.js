/**
 * Taiwan-specific stock data API endpoints (CNYes)
 */
import apiClient from './client';

const BASE_PATH = '/v1/tw';

/**
 * Get broker rating records for a TW stock symbol
 * @param {string} symbol - Stock ticker (e.g. "2330.TW")
 * @returns {Promise<Array>} List of broker rating records
 */
export const getTwBrokerRatings = async (symbol) => {
  const response = await apiClient.get(`${BASE_PATH}/stocks/${encodeURIComponent(symbol)}/broker-ratings`);
  return response.data;
};

/**
 * Trigger a fresh fetch of broker ratings from CNYes
 * @param {string} symbol - Stock ticker (e.g. "2330.TW")
 * @returns {Promise<Object>} Result of the refresh
 */
export const refreshTwBrokerRatings = async (symbol) => {
  const response = await apiClient.post(`${BASE_PATH}/stocks/${encodeURIComponent(symbol)}/broker-ratings/refresh`);
  return response.data;
};

/**
 * Fetch today's block trade summary from TWSE (no CAPTCHA).
 * Returns: { source, data: [{ symbol, name, total_volume, total_value, trades: [...] }] }
 * @param {string|null} date - YYYYMMDD, or null for today
 */
export const getTWBlockTrades = async (date = null) => {
  const params = date ? { date } : {};
  const response = await apiClient.get(`${BASE_PATH}/block-trades`, { params });
  return response.data;
};

/**
 * Fetch broker-level block trade detail for one symbol via BSR scraping.
 * Returns: { source, symbol, records: [{ ..., broker_rows: [...] }] }
 * May return HTTP 503 if CAPTCHA OCR is not available server-side.
 * @param {string} symbol - Stock code (e.g. "2308")
 */
export const getTWBlockTradesDetail = async (symbol) => {
  const response = await apiClient.get(`${BASE_PATH}/block-trades/${encodeURIComponent(symbol)}`);
  return response.data;
};

/**
 * Debug: fetch CAPTCHA image (base64) + OCR attempt log + broker table.
 * Never cached – hits bsr.twse.com.tw live every call.
 * @param {string} [symbol] - Stock code (e.g. "2308"), or omit to fetch ALL today's block trades
 * @returns {Promise<{symbol, ocr_success, captcha_image_b64, attempts, error, records}>}
 */
export const getTWBlockTradesOCRDebug = async (symbol = '', maxAttempts = 8) => {
  const params = {};
  if (symbol) params.symbol = symbol;
  if (maxAttempts !== 8) params.max_attempts = maxAttempts;
  const response = await apiClient.get(`${BASE_PATH}/block-trades-debug`, { params });
  return response.data;
};
