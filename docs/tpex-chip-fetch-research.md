# 上櫃（TPEX）分點資料自動抓取 — 調查報告

- 調查日期：2026-07-05
- 範圍：讓籌碼判讀（chip）模組能自動取得**上櫃股票**的券商分點明細，供 LINE Bot 即時判讀。
- 測試工具：Playwright（真實 Chromium）實地操作 TPEX 官網 brokerBS 頁。

---

## 1. 背景與問題

籌碼判讀 pipeline 需要「券商分點買賣明細」作為輸入。

| 市場 | 分點來源 | 自動化狀態 |
|------|----------|-----------|
| 上市 TWSE | `bsr.twse.com.tw`（圖形 CAPTCHA） | 已可自動（ddddocr 解 CAPTCHA） |
| 上櫃 TPEX | `tpex.org.tw` brokerBS | 先前判定「無法自動、只能人工上傳 CSV」 |

TPEX 官網公告：

> 《重要提醒公告》本系統自 103 年 12 月 1 日起調整查詢方式，查詢及下載每一檔證券前得**驗證非機器人程式**。

加上整站掛有 Cloudflare，先前結論是「上櫃只能請使用者手動下載 CSV 上傳」。本次調查重新以真實瀏覽器驗證此結論是否仍成立。

---

## 2. 調查方法

以 Playwright 開啟真實 Chromium，實地操作下列頁面並攔截網路請求：

- 頁面：`https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html`
- 動作：輸入股票代碼（實測 `6488` 環球晶、`5483` 中美晶）→ 按「查詢」/Enter。
- 觀察：驗證元件型態、資料如何載入、可否取得結構化資料。

---

## 3. 主要發現

### 3.1 驗證機制 = Cloudflare Turnstile（隱形／managed 模式），非圖形 CAPTCHA

- 頁面載入後會載入 Cloudflare Turnstile（`challenges.cloudflare.com/...`）。
- 在**真實瀏覽器**情境下，Turnstile 會**自動通過、無需人工解題**，也沒有出現任何需要辨識的 CAPTCHA 圖片。
- 這與 TWSE `bsr` 的圖形 CAPTCHA 不同：**TPEX 這條不需要 OCR。**

### 3.2 真正的資料端點（回傳乾淨 JSON）

輸入代碼並查詢後，頁面向下列端點發出 **POST**：

```
POST https://www.tpex.org.tw/www/zh-tw/afterTrading/brokerBS
Content-Type: application/x-www-form-urlencoded
Body: cf-turnstile-response=<Turnstile token>
```

回應為 `application/json`，結構如下：

```json
{
  "tables": [
    {
      "fields": ["交易日期","證券代號","成交筆數","成交金額","成交股數","週轉率(%)","開盤價","最高價","最低價","收盤價"],
      "data": [["115年7月3日","5483 中美晶","28946","6,621,876,273","32,536,540","5","197.50","211.00","195.50","210.50"]]
    },
    {
      "title": "券商買賣日報表（一般交易）",
      "fields": ["序號","券商","價格","買進股數","賣出股數"],
      "data": [
        [1,"1020 合庫","196.50","1000","0"],
        [2,"1020 合庫","197.50","2000","10000"]
      ]
    }
  ],
  "stat": "ok"
}
```

- `tables[0]`：當日 OHLC、成交量、**交易日期（民國）**、**證券代號＋名稱**。
- `tables[1]`：完整分點列，欄位 `序號 / 券商 / 價格 / 買進股數 / 賣出股數`，剛好對應現有 ETL 需要的 `[Broker, Price, Buy, Sell]`（股數單位）。

### 3.3 關鍵限制（實測踩到）

1. **Turnstile token 必填且為單次性**：`POST` 一定要帶 `cf-turnstile-response`。
   - ⟹ 純 `requests` / `curl_cffi` **無法直接呼叫**（拿不到 token），一定要真瀏覽器執行 Turnstile JS 產生 token。
2. **需等待 Turnstile 就緒**：頁面載入後需等約 4–6 秒讓 token 產生，太快查詢會回 `401`。
3. **「下載 CSV」按鈕會再次觸發 Turnstile 並回 `401`**：
   - ⟹ 不要走 CSV 下載路徑；改用「查詢」動作觸發的 JSON 回應（或直接解析已渲染的 DOM 表）。
4. **資料僅限「當日」**：官網「本系統僅提供上櫃證券當日交易資料」，適用每日收盤後的即時判讀。
5. 使用條款：資料不得逕自散布或販售，本專案僅供自用判讀。

### 3.4 CSV 格式相容性

使用者實際下載的 `6488_1150703.csv`（環球晶）為 TPEX 單欄格式：

```
券商買賣證券成交價量資訊
證券代碼,6488
序號,券商,價格,買進股數,賣出股數
"1","1020 合庫","1160","5","0"
...
```

與現有 `backend/app/services/chip/etl.py` 的 `single5` 解析路徑完全相容 —— 手動上傳 `POST /v1/chip/analyze` 早已可判讀上櫃股。**缺的只有「自動抓取」。**

### 3.5 ⚠️ 更正：伺服器端「自動化」無法通過 Turnstile（2026-07-05 容器實測）

前述 3.1「真實瀏覽器隱形通過」是以 VS Code 的**整合式瀏覽器**（Electron，非自動化）測得。
在 backend Docker 容器內以 **Playwright 啟動的 Chromium** 實測後，結論不同：

| 瀏覽器（同一台主機/IP） | `navigator.webdriver` | Turnstile token |
|------|:---:|:---:|
| 整合式（Electron，非自動化） | `false` | ✅ 第 0 秒即取得（len≈794） |
| Playwright Chromium（headless） | — | ❌ 30 秒仍為空 |
| Playwright Chromium（Xvfb 有頭） | — | ❌ 25 秒仍為空 |

- 送出時 `cf-turnstile-response=` **為空** → 伺服器回 `{"stat":"請等待機器人驗證成功後，再做查詢，謝謝。"}`。
- token 空與否**與 IP、headless/有頭無關**，而是 Cloudflare managed Turnstile 偵測到
  **瀏覽器自動化指紋（Playwright/CDP）** 就拒發 token。
- 要再往下（stealth/指紋偽裝、rebrowser-patches、第三方解 captcha 服務）本質上是
  **主動繞過 Cloudflare 反自動化控制**，不在本專案採用範圍。

---

## 4. 結論（更正版）

- 上櫃分點的 **ETL/判讀早已可用**（手動上傳 CSV 即可）。
- **伺服器端「全自動」抓取不可行**：Cloudflare Turnstile 專門封鎖瀏覽器自動化，
  Playwright（無論 headless 或 Xvfb 有頭）都拿不到必要的 token。
- 只有「真人操作的一般瀏覽器」能取得 token —— 這正對應官網設計的**人工下載 CSV**流程。
- ⟹ **建議 TPEX 維持「人工下載 CSV → 上傳判讀」**（Tier 1），不採自動化繞過 Turnstile。


---

## 5. 建議實作（Tier 2）

### 架構

```
LINE 收到 .TWO 代號
  → stock_context.ensure_chip_result()
    → tpex_broker_service.fetch_broker_rows(code)         # Playwright + Turnstile 自動通過
      → POST afterTrading/brokerBS 之 JSON → 解析 tables[1]
    → pipeline.process_rows(db, code, "TPEX", rows)        # 沿用既有判讀流程
      → OHLC/昨收/交易日改由 TPEX OpenAPI（免驗證碼）補上
  → 回覆「📊 籌碼判讀」區塊顯示分數／分類
```

### 檔案

- 新增 `backend/app/services/chip/tpex_broker_service.py`
  - `fetch_broker_rows(stock_id)`：Playwright 流程（goto → 等 Turnstile 6s → 填代碼 → Enter → `expect_response(afterTrading/brokerBS)` → `resp.json()`）。
  - `_parse(payload)`：取 `tables[1].data` → `[{broker, price, buy_volume, sell_volume}, ...]`（相容 `etl.dataframe_from_rows`）。
- 修改 `backend/app/services/chip/stock_context.py`
  - `ensure_chip_result()` 的 `.TWO` 分支：先嘗試 `fetch_broker_rows` + `process_rows`；失敗才 fallback 回 Tier 1 引導訊息。
- 相依與映像
  - `backend/requirements-runtime.txt` 加入 `playwright`。
  - `backend/Dockerfile` 安裝 chromium（`playwright install --with-deps chromium`），設定 `PLAYWRIGHT_BROWSERS_PATH`。
  - 以非 root（uid 1000）執行，`launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage"])`。

### 執行方式（沿用 Option A）

- 於 LINE 背景任務內 inline 執行（僅 2 名使用者，可接受每檔約 10–15s）。
- 新鮮度閘門：該股已有「最近交易日」判讀就跳過，避免重複啟動瀏覽器。

### 風險與維運

- **脆弱性**：TPEX 若改版 Turnstile sitekey / 端點 / 前端流程，抓取會失敗；需容錯與逾時，失敗即 fallback 到「請上傳 CSV」。
- **映像肥大**：chromium + 相依約使 backend 映像增加 ~400MB，建置時間變長。
- **資源**：每次啟動瀏覽器佔記憶體；2 使用者的量級可接受，未來量大再改為常駐 context 或獨立 worker/佇列。
- **合規**：僅供自用判讀，不得散布或販售 TPEX 資料。

---

## 6. 附錄：實測端點清單

| 端點 | 用途 |
|------|------|
| `GET https://www.tpex.org.tw/data/menu/zh-tw/menu.json` | 站台選單（非資料） |
| `GET https://www.tpex.org.tw/www/zh-tw/api/codeQuery?type=stk_reg&query=<code>` | 股票代碼查詢 |
| `POST https://www.tpex.org.tw/www/zh-tw/afterTrading/brokerBS` | **分點資料（需 Turnstile token）** |
| `https://challenges.cloudflare.com/cdn-cgi/challenge-platform/...` | Cloudflare Turnstile 挑戰 |
</content>
</invoke>
