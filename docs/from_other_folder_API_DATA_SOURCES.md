# Stock Analysis System — API & 資料來源整理

> 此文件供 AI 助手（Claude）將本系統資料擷取邏輯融合至其他專案使用。
> 整理日期：2026-06-14

---

## 一、外部 API 來源總覽

| 來源 | Base URL | 說明 |
|------|----------|------|
| 鉅亨網 WebSocket API | `https://ws.api.cnyes.com` | 即時報價、K線、ESG |
| 鉅亨網 MarketInfo API | `https://marketinfo.api.cnyes.com` | 財務比率、EPS、月營收、券商評等 |
| 鉅亨網 Strategy API | `https://cosvc.internalapi.cnyes.com` | 策略趨勢報告 |
| 鉅亨網 Web (爬蟲) | `https://www.cnyes.com` | 券商升評爬取 |
| Yahoo Finance v8 API | `https://query2.finance.yahoo.com` | 美股即時報價 |
| Yahoo 台股排行 API | `https://tw.stock.yahoo.com` | 台股排名、成交量 |
| Yahoo Finance Web | `https://finance.yahoo.com` | 股票 ID 查詢 |

---

## 二、各 API 端點明細

### 2.1 鉅亨網 — 即時報價

**端點**：`GET https://ws.api.cnyes.com/ws/api/v1/quote/quotes/{symbol}?column=KEY,M,AI`

**symbol 格式**：
- 台股上市股票：`TWS:{股票代碼}:STOCK`（例：`TWS:2330:STOCK`）
- 台股期貨：`TWS:{代碼}:FUTURES`
- 台股指數：`TWS:{代碼}:INDEX`

**回傳欄位（key 為數字）**：
| Key | 說明 |
|-----|------|
| `6` | 現價（收盤價） |
| `11` | 漲跌金額 |
| `75` | 52 週最高價 |
| `76` | 52 週最低價 |
| `200009` | 股票中文名稱 |

**程式位置**：
- `/home/ailab_server/stock-analysis-system/app/services/report/stock_report.py` → `_fetch_realtime_quote()`
- `/home/ailab_server/stock-analysis-system/app/services/analysis/target_diff.py` → `_fetch_realtime_quote()`
- `/home/ailab_server/stock-analysis-system/app/services/realtime/watchlist.py`
- `/home/ailab_server/stock-analysis-system/app/services/stock_screener.py` → `get_stock_detail()`

---

### 2.2 鉅亨網 — K 線歷史資料（OHLCV）

**端點**：`GET https://ws.api.cnyes.com/ws/api/v1/charting/history`

**Query 參數**：
| 參數 | 說明 | 範例 |
|------|------|------|
| `resolution` | 時間粒度 | `1`（1分鐘）、`D`（日）、`M`（月） |
| `symbol` | 股票代號 | `TWS:2330:STOCK` |
| `from` | 起始 Unix timestamp（毫秒） | `1700000000000` |
| `to` | 結束 Unix timestamp（毫秒） | `1600000000000` |

**回傳資料結構**：
```json
{
  "data": {
    "t": [timestamp, ...],
    "o": [open, ...],
    "h": [high, ...],
    "l": [low, ...],
    "c": [close, ...],
    "v": [volume, ...]
  }
}
```

**用途**：
- 取得當日 OHLCV（resolution=1）
- 取得52週高低價（resolution=D，時間範圍365天）
- 取得月線資料（resolution=M，時間範圍4年）

**程式位置**：
- `/home/ailab_server/stock-analysis-system/app/services/realtime/cnyes_realtime.py` → `get_eod_from_1m()`
- `/home/ailab_server/stock-analysis-system/app/services/report/stock_report.py` → `_fetch_eod_from_1m()`, `_fetch_52week_range()`
- `/home/ailab_server/stock-analysis-system/legacy/StockPriceCNYesRT.py`

---

### 2.3 鉅亨網 — 財務比率（季度）

**端點**：`GET https://marketinfo.api.cnyes.com/mi/api/v1/statement/TWS:{股票代碼}:STOCK/ratio/quarter`

**回傳資料結構**：
```json
{
  "statusCode": 200,
  "data": {
    "range": ["2024Q4", "2024Q3", ...],
    "datas": [
      {
        "name": "毛利率",
        "key": "grossMargin",
        "datasets": [{"percent": 53.2}, ...]
      }
    ]
  }
}
```

**常見 key 值**：
| key | 說明 | 數值欄位 |
|-----|------|----------|
| `grossMargin` | 毛利率 | `percent` |
| `netProfitMargin` | 淨利率 | `percent` |
| `ROE` | 股東權益報酬率 | `percent` |
| `ROA` | 資產報酬率 | `percent` |
| `eps` | 每股盈餘 | `amount` |

**程式位置**：
- `/home/ailab_server/stock-analysis-system/app/services/report/ratio_report.py` → `_fetch_ratio_data()`
- `/home/ailab_server/stock-analysis-system/app/services/report/stock_report.py` → `_fetch_market_info()`
- `/home/ailab_server/stock-analysis-system/app/services/stock_screener.py` → `get_stock_detail()`

---

### 2.4 鉅亨網 — 預估 EPS（分析師共識）

**端點**：`GET https://marketinfo.api.cnyes.com/mi/api/v1/financialIndicator/estimateProfit/TWS:{股票代碼}:STOCK?type=eps`

**回傳資料**：分析師預估年度 EPS 列表，含年份、預估家數、上調/下調次數、預估中位數等。

**程式位置**：
- `/home/ailab_server/stock-analysis-system/app/services/report/stock_report.py` → `_fetch_est_eps()`
- `/home/ailab_server/stock-analysis-system/legacy/StockPriceCNYesRT.py`

---

### 2.5 鉅亨網 — EPS 季度歷史

**端點**：`GET https://marketinfo.api.cnyes.com/mi/api/v1/financialIndicator/eps/TWS:{股票代碼}:STOCK?resolution=Q&acc=false&year=5&to={Unix_timestamp}`

**參數說明**：
- `resolution=Q`：季度
- `acc=false`：非累積
- `year=5`：取近5年
- `to`：截至時間（Unix timestamp）

**程式位置**：`/home/ailab_server/stock-analysis-system/legacy/StockPriceCNYesRT.py`

---

### 2.6 鉅亨網 — 月營收

**端點**：`GET https://marketinfo.api.cnyes.com/mi/api/v1/financialIndicator/revenue/TWS:{股票代碼}:STOCK?year=2&to={Unix_timestamp}`

**回傳資料結構**：
```json
{
  "data": [
    {
      "time": [timestamp, ...],
      "revenue": [數值, ...]
    }
  ]
}
```

**程式位置**：`/home/ailab_server/stock-analysis-system/legacy/CNYESChart.py` → `CNYesRevenue()`

---

### 2.7 鉅亨網 — ESG 個股評級

**端點**：`GET https://ws.api.cnyes.com/ws/api/v1/esg/state/TWS:{股票代碼}:STOCK`

**回傳**：
```json
{
  "data": {
    "esgGrade": "AAA"
  }
}
```
（評級可能為 AAA / AA / A / BBB 或 null）

**程式位置**：
- `/home/ailab_server/stock-analysis-system/legacy/StockPriceCNYesRT.py` → `CNYesEvaluation()`
- 使用於 `/home/ailab_server/stock-analysis-system/app/services/analysis/esg_analysis.py`

---

### 2.8 鉅亨網 — ESG 排名列表

**端點**：`GET https://ws.api.cnyes.com/ws/api/v1/esg/rank/ESG?quote=1&limit=150`

**回傳**：ESG 評級前 150 支股票列表，含股票代碼、ESG 分數、即時報價資訊。

**程式位置**：`/home/ailab_server/stock-analysis-system/app/services/analysis/esg_analysis.py` → `_fetch_esg_rankings()`

---

### 2.9 鉅亨網 — 策略趨勢報告

**端點**：`GET https://cosvc.internalapi.cnyes.com/cosvc/api/v1/MoneyTide/relatedStrategyInTwstock?stockId={股票代碼}`

**回傳**：
```json
{
  "trend_code": 2,
  "items": [{"strg_property": 2}]
}
```
**趨勢代碼說明**：1-2 = 強勢（紅↑）、3 = 中性（黃●）、4-5 = 弱勢（綠↓）

**程式位置**：`/home/ailab_server/stock-analysis-system/app/services/report/stock_report.py` → `_fetch_strategy_trend()`

---

### 2.10 鉅亨網 — 產業排名

**端點**：`GET https://ws.api.cnyes.com/ws/api/v4/universal/quote?type={ranking_type}&param=code={group_id};order={order}`

**ranking_type 可選值**：
| 值 | 說明 |
|----|------|
| `INDUSTRIAL_STATEMENT_GROSS_MARGIN.RANK` | 毛利率排名 |
| `INDUSTRIAL_STATEMENT_NET_PROFIT_MARGIN.RANK` | 淨利率排名 |
| `INDUSTRIAL_STATEMENT_NET_PROFIT_YOY.RANK` | 淨利 YOY 排名 |
| `INDUSTRIAL_PRICE_CHANGE.RANK` | 價格變動排名 |
| `INDUSTRIAL_PERFORMANCE_1D.RANK` | 1日表現排名 |
| `INDUSTRIAL_PERFORMANCE_1W.RANK` | 1週表現排名 |
| `INDUSTRIAL_PERFORMANCE_1M.RANK` | 1月表現排名 |
| `INDUSTRIAL_PERFORMANCE_YTD.RANK` | 年初至今表現排名 |

**程式位置**：`/home/ailab_server/stock-analysis-system/app/services/group/group_ranking.py` → `get_group_ranking()`

---

### 2.11 鉅亨網 — 券商評等歷史（API 方式）

**端點**：`GET https://marketinfo.api.cnyes.com/mi/api/v1/TWS:{股票代碼}:STOCK/foreignRate?from={ts}&to={ts}`

**回傳資料結構**：
```json
{
  "statusCode": 200,
  "data": {
    "rates": [
      {
        "formatDate": "2024/01/15",
        "broker": "元大",
        "rateKind": "買進",
        "newRate": "買進",
        "formatTargetPrice": "650"
      }
    ]
  }
}
```

**程式位置**：`/home/ailab_server/stock-analysis-system/legacy/BrokerPTAUpdateAPI.py` → `get_stock_ratings_from_api()`

---

### 2.12 鉅亨網 — 券商升評（網頁爬蟲）

**URL**：`GET https://www.cnyes.com/archive/twstock/board/ratediff.aspx?gt=qfii&gp=rate`

**擷取方式**：HTML 爬蟲，解析 `<TR><TD>` 結構
**擷取欄位**：日期、股票代碼、股票名稱、券商、評級類型、新評級、目標價

**程式位置**：`/home/ailab_server/stock-analysis-system/legacy/BrokerPTAUpdate.py` → `NearByagentRate()`

---

### 2.13 Yahoo Finance — 美股即時報價

**端點**：`GET https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d`

**symbol 格式**：標準 Yahoo 股票代碼（如 `AAPL`, `TSMC`）

**回傳資料**：
```json
{
  "chart": {
    "result": [{
      "meta": {
        "regularMarketPrice": 185.5,
        "regularMarketVolume": 50000000
      }
    }]
  }
}
```

**程式位置**：`/home/ailab_server/stock-analysis-system/app/services/realtime/yahoo_realtime.py`

---

### 2.14 Yahoo 台股 — 排名與成交量

**端點**：`GET https://tw.stock.yahoo.com/_td-stock/api/resource/StockServices.rank;exchange={market};limit={n};offset=0;period=1D;sortBy={sort}`

**參數說明**：
| 參數 | 可選值 | 說明 |
|------|--------|------|
| `exchange` | `TAI`（上市）、`TWO`（上櫃）、`ALL`（全市場） | 市場 |
| `limit` | 整數（如 100） | 取前 N 筆 |
| `sortBy` | `-turnoverK`（成交量）、`-dayHighLowDiff`（日高低差） | 排序方式 |

**回傳資料結構**（list 陣列元素）：
```json
{
  "symbol": "2330.TW",
  "name": "台積電",
  "price": "920",
  "changePercent": "+2.5%",
  "turnoverK": 12500000,
  "dayHigh": "925",
  "dayLow": "910",
  "previousClose": "898"
}
```

**程式位置**：
- `/home/ailab_server/stock-analysis-system/app/services/analysis/top_stocks.py` → `_fetch_top_stocks()`（成交量 Treemap）
- `/home/ailab_server/stock-analysis-system/app/services/analysis/yahoo_analysis.py` → `_fetch_market_stocks()`（AOI 指標）

---

## 三、本地資料檔案（JSON / TXT）

| 檔案路徑 | 格式 | 說明 |
|----------|------|------|
| `/home/ailab_server/stock-analysis-system/data/STOCK.json` | TinyDB JSON | 股票基本資料：Symbol, Name, Grade(ESG評級), PTADate, PTA[] |
| `/home/ailab_server/stock-analysis-system/data/BrokerPTA.json` | TinyDB JSON | 券商目標價評等：formatDate, Symbol, broker, rateKind, newRate, formatTargetPrice |
| `/home/ailab_server/stock-analysis-system/data/StockTargetDiff.JSON` | JSON Array | 目標價差異分析原始資料 |
| `/home/ailab_server/stock-analysis-system/data/GroupID2Name.json` | JSON Object | 產業代碼 → 產業名稱對應表 |
| `/home/ailab_server/stock-analysis-system/data/GroupName2ID.json` | JSON Object | 產業名稱 → 產業代碼對應表 |
| `/home/ailab_server/stock-analysis-system/data/StockWatchList.txt` | CSV（逗號分隔） | 觀察清單：`股票代碼,最低提醒價,最高提醒價,...` |

---

## 四、Flask 路由與功能對應

### 股票查詢 (`/home/ailab_server/stock-analysis-system/app/routes/stock.py`)

| 路由 | 方法 | 說明 | 對應 Service |
|------|------|------|--------------|
| `/` | GET/POST | 首頁查詢表單 | — |
| `/stock/<stock_id>` | GET | 股票綜合報告 | `StockReportService` |
| `/GLOBAL/<stock_id>` | GET | 完整圖表報告 | `/home/ailab_server/stock-analysis-system/legacy/CNYESChart.py` → `BuildCHART()` |
| `/RATIO/<stock_id>` | GET | 財務比率報表 | `RatioReportService` |
| `/CHART/<stock_id>` | GET | 營業統計圖 | `/home/ailab_server/stock-analysis-system/legacy/CNYESChart.py` |

### 即時報價 (`/home/ailab_server/stock-analysis-system/app/routes/realtime.py`)

| 路由 | 說明 | 資料來源 |
|------|------|----------|
| `/TWS/STOCK/<stock_id>` | 台股上市即時報價 | CNYes charting/history (1分鐘線) |
| `/TWS/FUTURES/<stock_id>` | 台股期貨報價 | CNYes |
| `/TWS/INDEX/<stock_id>` | 台股指數報價 | CNYes |
| `/USS/STOCK/<stock_id>` | 美股即時報價 | Yahoo Finance v8 |

### 分析報告 (`/home/ailab_server/stock-analysis-system/app/routes/analysis.py`)

| 路由 | 說明 | 資料來源 |
|------|------|----------|
| `/BCS/` | 藍籌股 ESG 分析 | CNYes ESG rank API |
| `/COM/` | 券商升評比較 | CNYes ESG rank API |
| `/PRO/` | 績優股承諾 | CNYes ESG rank API |
| `/TPD/` | 目標價差異排名 | 本地 `StockTargetDiff.JSON` + CNYes 即時報價 |
| `/AOI/` | Yahoo 分析師意見指標 | Yahoo 台股排名 API |
| `/TVLTAI/` | 台股 Top100 成交量 Treemap | Yahoo `StockServices.rank` (TAI) |
| `/TVLALL/` | 全市場 Top100 Treemap | Yahoo `StockServices.rank` (ALL) |

### 產業分組 (`/home/ailab_server/stock-analysis-system/app/routes/group.py`)

| 路由 | 說明 | 資料來源 |
|------|------|----------|
| `/List/` | 產業列表 | 本地 `GroupID2Name.json` |
| `/GMPR/<group_id>` | 毛利率排名 | CNYes v4 universal/quote |
| `/NPMR/<group_id>` | 淨利率排名 | CNYes v4 universal/quote |
| `/IPYTD/<group_id>` | YTD 表現排名 | CNYes v4 universal/quote |
| `/IPRank?group=&range=&order=` | 自訂產業排名 | CNYes v4 universal/quote |

### 每日推薦 (`/home/ailab_server/stock-analysis-system/app/routes/recommendation.py`)

| 路由 | 說明 | 資料來源 |
|------|------|----------|
| `/recommend/daily` | 每日選股推薦 | CNYes 即時報價 + 財務比率 (組合篩選) |

### 工具 (`/home/ailab_server/stock-analysis-system/app/routes/tools.py`)

| 路由 | 說明 |
|------|------|
| `/ATP/` | 手動新增/更新券商目標價 |
| `/MOMO/<keyword>` | Momo 購物關鍵字查詢 |
| `/health` | 服務健康檢查 |

---

## 五、選股引擎邏輯 (`/home/ailab_server/stock-analysis-system/app/services/stock_screener.py`)

### 價值投資型篩選條件
- ROE > 6%
- 毛利率 > 15%
- 淨利率 > 5%
- EPS > 0（有獲利）
- 本益比 < 30 且 > 0
- 殖利率 > 1.5%（估算：EPS × 50% / 股價）
- 價格位置 < 60%（相對52週高低點）

### 成長動能型篩選條件（`screen_growth_stocks()`）
- 毛利率 > 30%
- 淨利率 > 10%
- 本益比合理（可調整）
- 價格接近52週高點

### 評分公式（價值型）
```
score = ROE × 5 + 毛利率 × 1 + 淨利率 × 2 + 殖利率 × 8
      + (30 - 本益比) × 2 + (60 - 價格位置%) × 1.5
```

---

## 六、快取機制

- 快取目錄：`/home/ailab_server/stock-analysis-system/cache/html/`
- 命名規則：`CNYES.{類型}.{股票代碼}.{月日MMDD}.html`
  - 例：`CNYES.GLOBAL.2330.0614.html`
  - 例：`CNYES.RATIO.2330.0614.html`
  - 例：`CNYES.CHART.2330.0614.html`
  - 例：`CNYESTarget.0614.html`
  - 例：`daily_recommendation_20260614.html`
- 快取有效期：當天（依日期命名，不同日期自動重新產生）

---

## 七、通用 HTTP Headers

所有外部 API 請求均使用以下 User-Agent（模擬瀏覽器）：
```
Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/111.25 (KHTML, like Gecko) Chrome/99.0.2345.81 Safari/123.36
```

---

## 八、相關程式檔案路徑索引

```
/home/ailab_server/stock-analysis-system/
├── app/
│   ├── routes/
│   │   ├── stock.py          # 股票報告路由
│   │   ├── realtime.py       # 即時報價路由
│   │   ├── analysis.py       # 分析報告路由
│   │   ├── group.py          # 產業排名路由
│   │   ├── recommendation.py # 每日推薦路由
│   │   └── tools.py          # 工具路由
│   └── services/
│       ├── realtime/
│       │   ├── cnyes_realtime.py    # CNYes 即時報價
│       │   ├── yahoo_realtime.py    # Yahoo 美股即時報價
│       │   └── watchlist.py         # 觀察清單
│       ├── report/
│       │   ├── stock_report.py      # 股票綜合報表（整合多 API）
│       │   └── ratio_report.py      # 財務比率報表
│       ├── analysis/
│       │   ├── esg_analysis.py      # ESG 分析
│       │   ├── target_diff.py       # 目標價差異
│       │   ├── top_stocks.py        # Yahoo 成交量 Treemap
│       │   └── yahoo_analysis.py    # Yahoo AOI 指標
│       ├── group/
│       │   ├── group_list.py        # 產業列表
│       │   └── group_ranking.py     # 產業排名
│       ├── stock_screener.py        # 選股引擎（呼叫 CNYes 報價+比率）
│       └── daily_recommendation.py  # 每日推薦報告生成
├── legacy/
│   ├── CNYESChart.py         # 圖表（月營收 + Yahoo EPS）
│   ├── StockPriceCNYesRT.py  # 多種 CNYes API 整合（原始版）
│   ├── BrokerPTAUpdate.py    # 券商評等爬蟲
│   └── BrokerPTAUpdateAPI.py # 券商評等 API 方式
├── data/
│   ├── STOCK.json            # TinyDB 股票資料庫
│   ├── BrokerPTA.json        # TinyDB 券商評等資料庫
│   ├── StockTargetDiff.JSON  # 目標價差異資料
│   ├── GroupID2Name.json     # 產業代碼對應
│   └── StockWatchList.txt    # 觀察清單
└── config/
    └── settings.py           # API Base URL 設定
```
