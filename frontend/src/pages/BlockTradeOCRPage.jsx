/**
 * BlockTradeOCRPage
 *
 * Debug page for verifying broker-branch (分點) fetching for both markets:
 *   - 上市 TWSE: bsr.twse.com.tw via CAPTCHA OCR
 *   - 上櫃 TPEX: tpex.org.tw via Playwright (Cloudflare Turnstile)
 * Also runs the chip judgment (AI 解讀) inline for the same symbol.
 *
 * Route: /tw-ocr-debug
 */
import { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Collapse,
  Divider,
  IconButton,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import InsightsIcon from '@mui/icons-material/Insights';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';

import { getTWBlockTradesOCRDebug } from '../api/twData';
import { analyzeChipAuto, getChipChartUrl, getTPEXBrokerDebug } from '../api/chip';

const CLASS_NAMES = {
  1: '低檔殺盤',
  2: '高檔出貨',
  3: '平盤交戰',
  4: '低檔吃貨',
  5: '高檔追進',
  6: '高買低賣',
  7: '高賣低買',
  8: '低買高賣',
};

// ── helper ────────────────────────────────────────────────────────────────────

function formatVolume(v) {
  if (v == null) return '-';
  return Number(v).toLocaleString();
}

function formatMoney(v) {
  if (v == null) return '-';
  return `$${Number(v).toLocaleString()}`;
}

// ── sub-components ─────────────────────────────────────────────────────────────

function AttemptRow({ attempt }) {
  const [open, setOpen] = useState(false);
  const resultColor = {
    success: 'success',
    no_data: 'info',
    captcha_wrong: 'error',
    ocr_failed: 'warning',
    parse_empty: 'warning',
    exception: 'error',
  }[attempt.result] ?? 'default';

  return (
    <>
      <TableRow>
        <TableCell align="center">{attempt.attempt}</TableCell>
        <TableCell sx={{ fontFamily: 'monospace', fontWeight: 700 }}>
          {attempt.ocr_raw ?? '—'}
        </TableCell>
        <TableCell align="center">
          {attempt.result ? (
            <Chip label={attempt.result} color={resultColor} size="small" />
          ) : '—'}
        </TableCell>
        <TableCell sx={{ fontSize: '0.75rem', color: 'text.secondary' }}>
          {attempt.error ?? ''}
        </TableCell>
        <TableCell align="center">
          {attempt.html_snippet && (
            <IconButton size="small" onClick={() => setOpen(!open)}>
              {open ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
            </IconButton>
          )}
        </TableCell>
      </TableRow>
      {attempt.html_snippet && (
        <TableRow>
          <TableCell colSpan={5} sx={{ p: 0 }}>
            <Collapse in={open}>
              <Box sx={{ p: 1.5, bgcolor: 'action.hover' }}>
                <Typography variant="caption" sx={{ fontWeight: 700, display: 'block', mb: 0.5 }}>
                  Raw HTML snippet (first 3000 chars)
                </Typography>
                <Box
                  component="pre"
                  sx={{
                    fontSize: '0.7rem',
                    overflow: 'auto',
                    maxHeight: 300,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-all',
                    m: 0,
                  }}
                >
                  {attempt.html_snippet}
                </Box>
              </Box>
            </Collapse>
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

function BrokerTable({ brokerRows }) {
  if (!brokerRows || brokerRows.length === 0) {
    return <Typography variant="body2" color="text.secondary">（無明細）</Typography>;
  }
  return (
    <TableContainer component={Paper} variant="outlined" sx={{ mt: 1 }}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>#</TableCell>
            <TableCell>券商代碼</TableCell>
            <TableCell>券商名稱</TableCell>
            <TableCell align="right">價格</TableCell>
            <TableCell align="right">買量（張）</TableCell>
            <TableCell align="right">賣量（張）</TableCell>
            <TableCell align="center">交易類型</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {brokerRows.map((r) => (
            <TableRow key={r.seq} hover>
              <TableCell>{r.seq}</TableCell>
              <TableCell>{r.broker_code}</TableCell>
              <TableCell>{r.broker_name}</TableCell>
              <TableCell align="right">{r.price}</TableCell>
              <TableCell align="right">{formatVolume(r.buy_volume)}</TableCell>
              <TableCell align="right">{formatVolume(r.sell_volume)}</TableCell>
              <TableCell align="center">
                <Chip label={r.trade_type} size="small" variant="outlined" />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

function StockRecordCard({ record }) {
  return (
    <Card variant="outlined" sx={{ mb: 2 }}>
      <CardContent>
        <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 1 }}>
          <Typography variant="h6" sx={{ fontWeight: 700 }}>
            {record.name}
          </Typography>
          <Chip label={record.symbol} size="small" />
          <Typography variant="body2" color="text.secondary">
            {record.date}
          </Typography>
        </Stack>

        <Stack direction="row" spacing={3} sx={{ mb: 2, flexWrap: 'wrap', rowGap: 1 }}>
          <Box>
            <Typography variant="caption" color="text.secondary">最高 / 最低</Typography>
            <Typography variant="body2">{record.high_price} / {record.low_price}</Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">交易筆數</Typography>
            <Typography variant="body2">{record.trade_count}</Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">總金額</Typography>
            <Typography variant="body2">{formatMoney(record.total_value)}</Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">總張數</Typography>
            <Typography variant="body2">{formatVolume(record.total_volume)}</Typography>
          </Box>
        </Stack>

        <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
          券商明細（{record.broker_rows?.length ?? 0} 筆）
        </Typography>
        <BrokerTable brokerRows={record.broker_rows} />
      </CardContent>
    </Card>
  );
}

// ── judgment (AI 解讀) ─────────────────────────────────────────────────────────

function JudgmentCard({ judgment }) {
  if (!judgment) return null;
  const probs = judgment.llm?.probabilities ?? judgment.probabilities ?? {};
  const top = Object.entries(probs)
    .map(([k, v]) => [k, Number(v)])
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .filter(([, v]) => v >= 0.05);
  const summary = judgment.llm?.summary ?? judgment.summary ?? '';
  const score = judgment.score ?? 0;
  const scoreColor = score > 0.3 ? 'success.main' : score < -0.3 ? 'error.main' : 'text.primary';

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
        <InsightsIcon color="primary" />
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
          AI 籌碼判讀
        </Typography>
        <Chip label={judgment.market} size="small" variant="outlined" />
        {judgment.trade_date && (
          <Typography variant="body2" color="text.secondary">
            {judgment.trade_date}
          </Typography>
        )}
      </Stack>

      <Typography variant="h4" sx={{ fontWeight: 700, color: scoreColor, mb: 0.5 }}>
        {score >= 0 ? `+${score.toFixed(2)}` : score.toFixed(2)}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        當日總分（+2 極多 ~ -2 極空）
      </Typography>

      <Stack direction="row" spacing={1} sx={{ mt: 1.5, mb: 1, flexWrap: 'wrap', rowGap: 1 }}>
        {top.map(([k, v]) => (
          <Chip
            key={k}
            label={`${CLASS_NAMES[k] ?? k} ${(v * 100).toFixed(0)}%`}
            color="primary"
            variant="outlined"
            size="small"
          />
        ))}
      </Stack>

      {summary && (
        <Typography variant="body2" sx={{ mt: 1 }}>
          {summary}
        </Typography>
      )}
    </Paper>
  );
}

// ── main page ──────────────────────────────────────────────────────────────────

function BrokerChartCard({ stockId }) {
  const [kind, setKind] = useState('daily');
  const [imgError, setImgError] = useState(false);

  const code = String(stockId || '').trim();
  if (!code) return null;

  const url = getChipChartUrl(code, kind, { bust: true });

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
        <InsightsIcon color="primary" />
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
          前 20 大主力分點 T 型圖
        </Typography>
        <Box sx={{ flexGrow: 1 }} />
        <ToggleButtonGroup
          value={kind}
          exclusive
          size="small"
          onChange={(_, v) => {
            if (v) {
              setKind(v);
              setImgError(false);
            }
          }}
        >
          <ToggleButton value="daily">單日</ToggleButton>
          <ToggleButton value="cumulative">期間累計</ToggleButton>
        </ToggleButtonGroup>
      </Stack>
      {imgError ? (
        <Typography variant="body2" color="text.secondary">
          尚無{kind === 'cumulative' ? '累計' : '單日'}分點資料可繪圖（請先「AI 判讀」或上傳 CSV）。
        </Typography>
      ) : (
        <Box
          component="img"
          src={url}
          alt={`${code} 分點 T 型圖`}
          onError={() => setImgError(true)}
          sx={{ width: '100%', height: 'auto', display: 'block', borderRadius: 1 }}
        />
      )}
    </Paper>
  );
}

export default function BlockTradeOCRPage() {
  const [market, setMarket] = useState('TWSE');
  const [symbol, setSymbol] = useState('');
  const [maxAttempts, setMaxAttempts] = useState(8);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const [judging, setJudging] = useState(false);
  const [judgment, setJudgment] = useState(null);
  const [judgeError, setJudgeError] = useState(null);

  const isTPEX = market === 'TPEX';

  function extractError(err, fallback) {
    const detail = err?.response?.data?.detail;
    return typeof detail === 'object'
      ? detail?.message ?? JSON.stringify(detail)
      : detail ?? err.message ?? fallback;
  }

  async function handleQuery(e) {
    e.preventDefault();
    setLoading(true);
    setResult(null);
    setError(null);

    try {
      const data = isTPEX
        ? await getTPEXBrokerDebug(symbol.trim())
        : await getTWBlockTradesOCRDebug(symbol.trim(), maxAttempts);
      setResult(data);
      if (isTPEX && data && data.success === false) {
        setError(data.error ?? '上櫃抓取失敗');
      }
    } catch (err) {
      setError(extractError(err, '查詢失敗'));
    } finally {
      setLoading(false);
    }
  }

  async function handleJudge() {
    if (!symbol.trim()) {
      setJudgeError('請先輸入股票代號');
      return;
    }
    setJudging(true);
    setJudgment(null);
    setJudgeError(null);
    try {
      const data = await analyzeChipAuto(symbol.trim(), market);
      setJudgment(data);
    } catch (err) {
      setJudgeError(extractError(err, 'AI 判讀失敗'));
    } finally {
      setJudging(false);
    }
  }

  return (
    <Box sx={{ maxWidth: 900, mx: 'auto', p: 3 }}>
      {/* ── Title ── */}
      <Typography variant="h5" sx={{ fontWeight: 700, mb: 0.5 }}>
        上市 / 上櫃 分點 Debug
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        驗證分點抓取是否正確：上市走 bsr.twse.com.tw（CAPTCHA OCR），
        上櫃走 tpex.org.tw（Playwright 通過 Cloudflare Turnstile）。
        可再按「AI 判讀」在同頁看到籌碼判讀結果。
      </Typography>

      {/* ── Market toggle ── */}
      <ToggleButtonGroup
        value={market}
        exclusive
        size="small"
        onChange={(_, v) => {
          if (v) {
            setMarket(v);
            setResult(null);
            setError(null);
            setJudgment(null);
            setJudgeError(null);
          }
        }}
        sx={{ mb: 2 }}
      >
        <ToggleButton value="TWSE">上市（TWSE）</ToggleButton>
        <ToggleButton value="TPEX">上櫃（TPEX）</ToggleButton>
      </ToggleButtonGroup>

      {/* ── Search bar ── */}
      <Paper
        component="form"
        onSubmit={handleQuery}
        sx={{ p: 2, mb: 3, display: 'flex', gap: 2, alignItems: 'center', flexWrap: 'wrap' }}
        variant="outlined"
      >
        <TextField
          label={isTPEX ? '股票代號' : '股票代號（選填）'}
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          placeholder={isTPEX ? '例如 5483' : '留空查今日全部'}
          size="small"
          sx={{ width: 180 }}
          inputProps={{ style: { fontFamily: 'monospace' } }}
        />
        {!isTPEX && (
          <TextField
            label="最多嘗試次數"
            type="number"
            value={maxAttempts}
            onChange={(e) => setMaxAttempts(Math.max(1, Math.min(20, Number(e.target.value) || 8)))}
            size="small"
            sx={{ width: 110 }}
            inputProps={{ min: 1, max: 20 }}
          />
        )}
        <Button
          type="submit"
          variant="contained"
          startIcon={loading ? <CircularProgress size={16} color="inherit" /> : <SearchIcon />}
          disabled={loading}
        >
          {loading ? '查詢中…' : '查詢分點'}
        </Button>
        <Button
          type="button"
          variant="outlined"
          onClick={handleJudge}
          startIcon={judging ? <CircularProgress size={16} color="inherit" /> : <InsightsIcon />}
          disabled={judging || !symbol.trim()}
        >
          {judging ? '判讀中…' : 'AI 判讀'}
        </Button>
        <Typography variant="caption" color="text.secondary">
          {isTPEX
            ? '即時連線 tpex.org.tw（Playwright，不走快取）'
            : '即時連線 BSR（不走快取）'}
        </Typography>
      </Paper>

      {/* ── AI 判讀 ── */}
      {judgeError && (
        <Alert severity="error" sx={{ mb: 3 }}>
          AI 判讀：{judgeError}
        </Alert>
      )}
      {judgment && (
        <Box sx={{ mb: 3 }}>
          <JudgmentCard judgment={judgment} />
        </Box>
      )}
      {judgment && (
        <Box sx={{ mb: 3 }}>
          <BrokerChartCard stockId={symbol.trim() || judgment.stock_id} />
        </Box>
      )}

      {/* ── Error ── */}
      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}

      {/* ── Results ── */}
      {result && (
        <Stack spacing={3}>

          {/* 抓取總結 */}
          <Paper variant="outlined" sx={{ p: 2 }}>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
              {(result.ocr_success ?? result.success)
                ? <CheckCircleOutlineIcon color="success" />
                : <ErrorOutlineIcon color="error" />}
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                {isTPEX
                  ? `抓取${result.success ? '成功' : '失敗'}`
                  : `OCR ${result.ocr_success ? '成功' : '失敗'}`}
              </Typography>
              <Chip
                label={`${result.records?.length ?? 0} 筆結果`}
                size="small"
                color={result.records?.length > 0 ? 'success' : 'default'}
              />
            </Stack>
            {result.error && (
              <Typography variant="body2" color="error">
                錯誤：{result.error}
              </Typography>
            )}
          </Paper>

          {/* CAPTCHA 圖片（僅上市） */}
          {result.captcha_image_b64 && (
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                CAPTCHA 圖片（最後一次嘗試）
              </Typography>
              <Box
                component="img"
                src={`data:image/png;base64,${result.captcha_image_b64}`}
                alt="CAPTCHA"
                sx={{
                  border: '1px solid',
                  borderColor: 'divider',
                  borderRadius: 1,
                  imageRendering: 'pixelated',
                  height: 60,
                  display: 'block',
                }}
              />
            </Paper>
          )}

          {/* OCR 嘗試明細（僅上市） */}
          {result.attempts?.length > 0 && (
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                OCR 嘗試紀錄（共 {result.attempts.length} 次）
              </Typography>
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell align="center" sx={{ width: 60 }}>嘗試</TableCell>
                      <TableCell>OCR 辨識文字</TableCell>
                      <TableCell align="center">結果</TableCell>
                      <TableCell>錯誤說明</TableCell>
                      <TableCell align="center" sx={{ width: 48 }}>HTML</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {result.attempts.map((a) => (
                      <AttemptRow key={a.attempt} attempt={a} />
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Paper>
          )}

          {/* CSV raw（僅上市） */}
          {result.csv_raw && (
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                CSV 原始內容（前 6000 字）
                {result.csv_url && (
                  <Box component="span" sx={{ ml: 1, fontSize: '0.75rem', color: 'text.secondary' }}>
                    來源：{result.csv_url}
                  </Box>
                )}
              </Typography>
              <Box
                component="pre"
                sx={{
                  fontSize: '0.72rem',
                  overflow: 'auto',
                  maxHeight: 300,
                  whiteSpace: 'pre',
                  m: 0,
                  bgcolor: 'action.hover',
                  p: 1,
                  borderRadius: 1,
                }}
              >
                {result.csv_raw}
              </Box>
            </Paper>
          )}

          {/* 解析出的表格 */}
          <Divider />
          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
            解析結果（{result.records?.length ?? 0} 筆）
          </Typography>

          {result.records?.length === 0 ? (
            <Alert severity="info">
              {isTPEX
                ? '查無該股分點（可能非當日、代號錯誤或非上櫃）。'
                : '今日該股無鉅額交易，或 OCR 失敗未能取得資料。'}
            </Alert>
          ) : (
            result.records.map((rec, i) => (
              <StockRecordCard key={i} record={rec} />
            ))
          )}

        </Stack>
      )}
    </Box>
  );
}

