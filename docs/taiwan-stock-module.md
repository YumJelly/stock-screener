# 台股模組說明

## 一、資料來源

| 資料類型 | 來源 | 說明 |
|---------|------|------|
| **上市股票清單 (TWSE)** | `https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=2` | Big5/cp950 編碼 HTML，約 2,000 支股票 |
| **上櫃股票清單 (TPEX)** | `https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=4` | Big5/cp950 編碼 HTML，約 500 支股票 |
| **歷史行情 OHLCV** | `yfinance` 套件 | 自動識別 `.TW` / `.TWO` 後綴，快取 5 年資料至 Redis |
| **靜態種子資料** | `data/taiwan-deep.csv` | 離線備份清單，含中英文名稱、產業、市場 |
| **月營收** | `marketinfo.api.cnyes.com` | 上市/上櫃公司每月揭露，yfinance 無此資料 |
| **ESG 評級** | `ws.api.cnyes.com` | CNYes ESG 評等（AAA/AA/A/BBB 等） |
| **券商評等** | `marketinfo.api.cnyes.com` | 券商升評/降評記錄（foreignRate API） |

> **注意：** 台股**不支援** Finviz 或 Alpha Vantage，yfinance 為主要行情來源。月營收/ESG/券商評等由 CNYes API 補充。

---

## 二、程式流程

```
┌──────────────────────────────────────────────────────────┐
│ 1. 股票清單更新                                          │
│    OfficialMarketUniverseSourceService.fetch_tw_snapshot()│
│    ├─ 下載 TWSE HTML (cp950)                             │
│    ├─ 下載 TPEX HTML (cp950)                             │
│    ├─ 驗證兩個來源的更新日期必須一致                     │
│    └─ 解析 HTML table → OfficialMarketUniverseSnapshot   │
└──────────────────────────────────────────────────────────┘
         ↓
┌──────────────────────────────────────────────────────────┐
│ 2. 代碼正規化 (Canonicalization)                         │
│    TWUniverseIngestionAdapter.canonicalize_rows()         │
│    ├─ "2330" / "TWSE:2330" / "2330.TW" → 統一為 2330.TW │
│    ├─ "3008" / "TPEX:3008" / "3008.TWO" → 統一為 3008.TWO│
│    ├─ 去重合併 + 來源 lineage 記錄                       │
│    └─ 拒絕不合格資料                                     │
└──────────────────────────────────────────────────────────┘
         ↓
┌──────────────────────────────────────────────────────────┐
│ 3. 寫入資料庫                                            │
│    UniverseIngestionPipeline.ingest_snapshot_rows()       │
│    ├─ Upsert stock_universe 表                           │
│    │   market=TW, currency=TWD, timezone=Asia/Taipei     │
│    │   exchange=TWSE 或 TPEX                             │
│    └─ 觸發 taxonomy 產業分類補充                         │
└──────────────────────────────────────────────────────────┘
         ↓
┌──────────────────────────────────────────────────────────┐
│ 4. 行情資料快取 (Redis)                                  │
│    BulkDataFetcher → yfinance.download()                 │
│    ├─ 批次下載 ["2330.TW", "3008.TWO", ...]             │
│    ├─ 速率限制：1 req/sec                                │
│    ├─ 快取至 Redis DB 2，TTL 7 天                        │
│    └─ 寫入 stock_prices 表                               │
└──────────────────────────────────────────────────────────┘
         ↓
┌──────────────────────────────────────────────────────────┐
│ 4b. TW 附加資料 (CNYes API)                              │
│    BulkDataFetcher._extract_cnyes_tw_data()              │
│    ├─ CNYesTWService.fetch_monthly_revenue()             │
│    │   → tw_revenue_monthly_* 寫入 stock_fundamentals   │
│    └─ CNYesTWService.fetch_esg_rating()                  │
│        → tw_esg_grade 寫入 stock_fundamentals            │
│    券商評等另有獨立端點手動觸發（見 API 端點章節）        │
└──────────────────────────────────────────────────────────┘
         ↓
┌──────────────────────────────────────────────────────────┐
│ 5. 選股篩選 (Screeners)                                  │
│    ScanOrchestrator 協調所有篩選器：                     │
│    ├─ Minervini Template (RS Rating, Stage 2)            │
│    ├─ CANSLIM (EPS 成長, RS, 法人持股)                   │
│    ├─ IPO Scanner                                        │
│    ├─ Volume Breakthrough                                │
│    └─ Custom Screener                                    │
└──────────────────────────────────────────────────────────┘
```

---

## 三、代碼格式

| 市場 | yfinance 格式 | 說明 |
|------|-------------|------|
| 台灣證交所 (TWSE) | `2330.TW` | 上市股票 |
| 台灣櫃買中心 (TPEX) | `3008.TWO` | 上櫃股票 |

### 支援的輸入格式

**上市 (TWSE)：**
- `2330` — 純代碼
- `2330.TW` — 含後綴
- `TWSE:2330` — 含交易所前綴
- `XTAI:2330` — XTAI 別名

**上櫃 (TPEX)：**
- `3008` — 純代碼
- `3008.TWO` — 含後綴
- `TPEX:3008` — 含交易所前綴
- `TWO:3008` — TWO 別名

---

## 四、核心檔案

| 檔案 | 功能 |
|------|------|
| `backend/app/services/tw_universe_ingestion_adapter.py` | 代碼正規化、去重、來源驗證 |
| `backend/app/services/official_market_universe_source_service.py` | 爬取 TWSE/TPEX 官方 HTML |
| `backend/app/services/stock_universe_service.py` | `ingest_tw_from_csv()` 服務層 |
| `backend/app/tasks/universe_tasks.py` | Celery 背景任務 `ingest_tw_universe_csv` |
| `backend/app/api/v1/universe.py` | REST API `POST /v1/universe/import-tw-csv` |
| `backend/app/domain/markets/catalog.py` | 市場定義：timezone=Asia/Taipei, currency=TWD |
| `backend/app/services/provider_routing_policy.py` | TW 市場只路由到 yfinance |
| `data/taiwan-deep.csv` | 靜態股票清單種子檔 |
| `backend/app/services/cnyes_tw_service.py` | CNYes API：月營收、ESG、券商評等（symbol 轉換 + rate limit） |
| `backend/app/api/v1/tw_data.py` | REST API：券商評等查詢與手動刷新 |
| `backend/alembic/versions/20260614_0021_add_cnyes_tw_data.py` | DB migration：新增 TW 欄位 + `tw_broker_ratings` 表 |

---

## 五、API 端點

### `POST /v1/universe/import-tw-csv`

手動匯入台股清單 CSV。

**Request Body：**
```json
{
  "csv_content": "...",
  "source_name": "tw_manual_csv",
  "snapshot_id": null,
  "snapshot_as_of": null,
  "strict": true
}
```

**Response：**
```json
{
  "message": "TW CSV imported successfully",
  "added": 100,
  "updated": 50,
  "total": 150,
  "rejected": 5
}
```

**錯誤碼：**
- `400` — 缺少 csv_content 或來源名稱不合法
- `500` — 資料庫或系統錯誤

### `GET /v1/tw/stocks/{symbol}/broker-ratings`

查詢指定台股的券商升評/降評記錄（由 `tw_broker_ratings` 表讀取）。

**Query 參數：**
- `limit` — 最多筆數（預設 50，最大 200）

**Response：**
```json
{
  "symbol": "2330.TW",
  "count": 12,
  "records": [
    {
      "format_date": "2026/06/10",
      "broker": "元大",
      "rate_kind": "買進",
      "new_rate": "買進",
      "target_price": 1100.0,
      "fetched_at": "2026-06-14T10:00:00+00:00"
    }
  ]
}
```

### `POST /v1/tw/stocks/{symbol}/broker-ratings/refresh`

從 CNYes API 拉取最新券商評等並寫入 `tw_broker_ratings` 表。

**Query 參數：**
- `lookback_days` — 往回查幾天（預設 90，最大 365）

**Response：**
```json
{
  "symbol": "2330.TW",
  "fetched": 8,
  "inserted": 3,
  "lookback_days": 90
}
```

**錯誤碼：**
- `400` — 非 TW/TWO 股票
- `502` — CNYes API 無回應

---

## 六、Celery 背景任務

### `ingest_tw_universe_csv`

位置：`backend/app/tasks/universe_tasks.py`

- 使用 `@serialized_data_fetch` 互斥鎖避免並發衝突
- 更新前後記錄 universe 大小差異
- 觸發 universe drift alert
- 回傳：`{status, added, updated, total, rejected, timestamp}`

---

## 七、市場設定

```python
Market(
    code="TW",
    label="Taiwan",
    default_currency="TWD",
    timezone="Asia/Taipei",
    exchanges=("TWSE", "TPEX", "XTAI"),
)
```

**Provider 路由：**
- 行情/基本面：`yfinance`（不支援 Finviz 或 Alpha Vantage）
- 月營收 / ESG：`CNYes API`（`cnyes_tw_service.py`，自動在 fundamentals refresh 時執行）
- 券商評等：`CNYes API`（手動觸發 via `POST /v1/tw/stocks/{symbol}/broker-ratings/refresh`）

**CNYes symbol 格式轉換：**
- `2330.TW` → `TWS:2330:STOCK`
- `3008.TWO` → `TWS:3008:STOCK`
- 非數字代碼或非 TW/TWO 後綴 → 跳過（回傳 `None`）

---

## 八、前端篩選選項

| 選項 | 說明 |
|------|------|
| **All Taiwan** | 全部 TW 市場股票 |
| **Taiwan Stock Exchange** | 僅上市股票 (XTAI/TWSE) |
| **TAIEX** | 台灣加權指數成份股 |

---

## 九、CNYes TW 附加資料欄位

### `stock_fundamentals` 新增欄位

| 欄位 | 型別 | 說明 |
|------|------|------|
| `tw_revenue_monthly_latest` | BigInteger | 最新月營收（千元） |
| `tw_revenue_monthly_yoy` | Float | 月營收 YoY % |
| `tw_revenue_monthly_mom` | Float | 月營收 MoM % |
| `tw_revenue_monthly_date` | String(10) | 月份字串，如 `"2026-05"` |
| `tw_revenue_monthly_updated_at` | DateTime | 最後更新時間 |
| `tw_esg_grade` | String(5) | ESG 評等，如 `"AAA"`、`"BBB"`（indexed） |
| `tw_esg_updated_at` | DateTime | ESG 資料更新時間 |

### `tw_broker_ratings` 表（新增）

| 欄位 | 說明 |
|------|------|
| `symbol` | 股票代碼（如 `2330.TW`） |
| `format_date` | 評等日期（`"YYYY/MM/DD"`） |
| `broker` | 券商名稱 |
| `rate_kind` | 評等類型（買進/中立/賣出） |
| `new_rate` | 新評等 |
| `target_price` | 目標價 |
| `fetched_at` | 寫入時間 |

Unique constraint：`(symbol, format_date, broker)`

### CNYes API Rate Limit

`CNYesTWService` 使用 instance-level `_last_request_at` 追蹤，最短間隔 1 req/sec。Fundamentals batch refresh 已有自己的 yfinance rate limiter，CNYes 呼叫在同一個 symbol loop 內，等效保持 ≤1 req/sec。
