/**
 * ChipAnalysisPage
 *
 * 台股籌碼判讀：上傳分點 CSV（TPEX/TWSE、UTF-8/Big5）或對 TWSE 自動抓取，
 * 顯示當日判讀分數/機率，以及歷史分數曲線與單日明細。
 *
 * Route: /chip
 */
import { useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Divider,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import {
  analyzeChipAuto,
  analyzeChipCsv,
  getChipHistory,
} from '../api/chip';

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

function scoreColor(score) {
  if (score >= 1) return 'success';
  if (score <= -1) return 'error';
  return 'default';
}

function ResultCard({ result }) {
  const probs = result?.probabilities || {};
  const top = Object.entries(probs)
    .sort((a, b) => b[1] - a[1])
    .filter(([, p]) => p >= 0.05)
    .slice(0, 4);

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
          <Typography variant="h6">
            {result.stock_id} · {result.trade_date}
          </Typography>
          <Chip label={result.market} size="small" />
          <Chip
            label={`總分 ${Number(result.score).toFixed(2)}`}
            color={scoreColor(result.score)}
            size="small"
          />
        </Stack>
        {result.summary && (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            {result.summary}
          </Typography>
        )}
        <Divider sx={{ mb: 1.5 }} />
        <Stack spacing={0.5}>
          {top.map(([cls, p]) => (
            <Box key={cls} sx={{ display: 'flex', justifyContent: 'space-between' }}>
              <Typography variant="body2">{CLASS_NAMES[cls] || cls}</Typography>
              <Typography variant="body2" color="text.secondary">
                {(p * 100).toFixed(0)}%
              </Typography>
            </Box>
          ))}
        </Stack>
      </CardContent>
    </Card>
  );
}

function ScoreCurve({ points }) {
  const data = useMemo(
    () => (points || []).map((p) => ({ date: p.trade_date, score: p.score })),
    [points],
  );
  if (!data.length) {
    return (
      <Typography variant="body2" color="text.secondary">
        尚無歷史資料。
      </Typography>
    );
  }
  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: -16 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="date" tick={{ fontSize: 11 }} />
        <YAxis domain={[-2, 2]} ticks={[-2, -1, 0, 1, 2]} tick={{ fontSize: 11 }} />
        <Tooltip />
        <ReferenceLine y={0} stroke="#888" />
        <Line
          type="monotone"
          dataKey="score"
          stroke="#1976d2"
          strokeWidth={2}
          dot={{ r: 2 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

export default function ChipAnalysisPage() {
  const queryClient = useQueryClient();
  const [file, setFile] = useState(null);
  const [autoSymbol, setAutoSymbol] = useState('');
  const [historySymbol, setHistorySymbol] = useState('');
  const [activeSymbol, setActiveSymbol] = useState('');
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

  const historyQuery = useQuery({
    queryKey: ['chipHistory', activeSymbol],
    queryFn: () => getChipHistory(activeSymbol),
    enabled: Boolean(activeSymbol),
  });

  const onSuccess = (data) => {
    setError('');
    setResult(data);
    setActiveSymbol(data.stock_id);
    queryClient.invalidateQueries({ queryKey: ['chipHistory', data.stock_id] });
  };
  const onError = (err) => {
    const detail = err?.response?.data?.detail;
    setError(typeof detail === 'string' ? detail : detail?.message || '判讀失敗');
  };

  const uploadMutation = useMutation({
    mutationFn: () => analyzeChipCsv(file),
    onSuccess,
    onError,
  });

  const autoMutation = useMutation({
    mutationFn: () => analyzeChipAuto(autoSymbol.trim()),
    onSuccess,
    onError,
  });

  const busy = uploadMutation.isPending || autoMutation.isPending;

  return (
    <Box sx={{ p: 2, maxWidth: 900, mx: 'auto' }}>
      <Typography variant="h5" sx={{ mb: 2 }}>
        籌碼判讀
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      <Card variant="outlined" sx={{ mb: 2 }}>
        <CardContent>
          <Typography variant="subtitle1" sx={{ mb: 1 }}>
            上傳分點 CSV（TPEX / TWSE，UTF-8 或 Big5）
          </Typography>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
            <Button
              component="label"
              variant="outlined"
              startIcon={<UploadFileIcon />}
            >
              選擇檔案
              <input
                type="file"
                accept=".csv"
                hidden
                onChange={(e) => setFile(e.target.files?.[0] || null)}
              />
            </Button>
            <Typography variant="body2" color="text.secondary">
              {file ? file.name : '尚未選擇檔案'}
            </Typography>
            <Button
              variant="contained"
              disabled={!file || busy}
              onClick={() => uploadMutation.mutate()}
            >
              {uploadMutation.isPending ? <CircularProgress size={20} /> : '判讀'}
            </Button>
          </Stack>

          <Divider sx={{ my: 2 }} />

          <Typography variant="subtitle1" sx={{ mb: 1 }}>
            TWSE 自動抓取（OCR）
          </Typography>
          <Stack direction="row" spacing={1} alignItems="center">
            <TextField
              size="small"
              label="上市股票代號"
              placeholder="2330"
              value={autoSymbol}
              onChange={(e) => setAutoSymbol(e.target.value)}
            />
            <Button
              variant="contained"
              disabled={!autoSymbol.trim() || busy}
              onClick={() => autoMutation.mutate()}
            >
              {autoMutation.isPending ? <CircularProgress size={20} /> : '自動判讀'}
            </Button>
          </Stack>
          <Typography variant="caption" color="text.secondary">
            上櫃（TPEX）因官網反機器人驗證，請改用 CSV 上傳。
          </Typography>
        </CardContent>
      </Card>

      {result && (
        <Box sx={{ mb: 2 }}>
          <ResultCard result={result} />
        </Box>
      )}

      <Card variant="outlined">
        <CardContent>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 2 }}>
            <Typography variant="subtitle1" sx={{ flexGrow: 1 }}>
              歷史分數曲線
            </Typography>
            <TextField
              size="small"
              label="股票代號"
              value={historySymbol}
              onChange={(e) => setHistorySymbol(e.target.value)}
            />
            <Button
              variant="outlined"
              onClick={() => setActiveSymbol(historySymbol.trim().toUpperCase())}
              disabled={!historySymbol.trim()}
            >
              查詢
            </Button>
          </Stack>
          {historyQuery.isFetching ? (
            <CircularProgress size={24} />
          ) : (
            <ScoreCurve points={historyQuery.data?.points} />
          )}
        </CardContent>
      </Card>
    </Box>
  );
}
