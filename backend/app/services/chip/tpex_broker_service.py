"""TPEX（上櫃）券商分點自動抓取。

TPEX brokerBS 頁掛 Cloudflare Turnstile（隱形/managed 模式），真實瀏覽器會
自動通過、無圖形 CAPTCHA。資料端點 POST ``.../afterTrading/brokerBS`` 需帶
``cf-turnstile-response`` token，故無法用純 requests，改以 Playwright 驅動
headless Chromium 取得該 token 並攔截 JSON 回應。

詳見 docs/tpex-chip-fetch-research.md。

回傳的 rows 相容 :func:`app.services.chip.etl.dataframe_from_rows`，可直接餵入
``pipeline.process_rows(db, code, "TPEX", rows)``。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

BROKER_URL = "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html"
_DATA_URL_FRAGMENT = "afterTrading/brokerBS"


class TPEXBrokerUnavailable(Exception):
    """無法自動取得 TPEX 分點資料（Playwright 缺席、Turnstile 失敗、查無資料等）。"""


def fetch_broker_rows(
    stock_id: str,
    *,
    nav_timeout_ms: int = 45000,
    settle_ms: int = 6000,
    response_timeout_ms: int = 30000,
    attempts: int = 3,
) -> list[dict]:
    """以 Playwright 抓取單一上櫃股票的券商分點明細。

    Parameters
    ----------
    stock_id : str
        上櫃股票代號（例如 ``"5483"``）。
    settle_ms : int
        頁面載入後等待 Turnstile 產生 token 的時間（太短會 401）。
    attempts : int
        Cloudflare 對 headless 偶爾會擋，失敗自動重試的次數。

    Returns
    -------
    list[dict]
        ``[{"broker","price","buy_volume","sell_volume"}, ...]``（股數單位）。

    Raises
    ------
    TPEXBrokerUnavailable
        Playwright 未安裝、或抓取/解析失敗。
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        raise TPEXBrokerUnavailable(f"playwright 未安裝或無法載入：{exc}") from exc

    code = (stock_id or "").strip().upper()
    if not code:
        raise TPEXBrokerUnavailable("未提供股票代號")

    last_err: Exception | None = None
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        try:
            for attempt in range(1, attempts + 1):
                context = browser.new_context(
                    locale="zh-TW",
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                )
                page = context.new_page()
                try:
                    # 用 "commit"（收到回應即返回）避開 Cloudflare JS 過場拖住
                    # domcontentloaded 的問題；再明確等待真正的表單出現。
                    page.goto(BROKER_URL, wait_until="commit", timeout=nav_timeout_ms)
                    box = page.get_by_role("textbox", name="股票代碼：")
                    box.wait_for(state="visible", timeout=nav_timeout_ms)
                    page.wait_for_timeout(settle_ms)  # 等 Turnstile 就緒

                    box.fill(code)
                    with page.expect_response(
                        lambda r: _DATA_URL_FRAGMENT in r.url,
                        timeout=response_timeout_ms,
                    ) as resp_info:
                        box.press("Enter")
                    resp = resp_info.value
                    if resp.status != 200:
                        raise TPEXBrokerUnavailable(
                            f"brokerBS 回應非 200（{resp.status}），Turnstile 可能未通過"
                        )
                    return _parse_rows(resp.json())
                except TPEXBrokerUnavailable:
                    # 「查無資料/stat 非 ok」屬於明確結果，不必重試。
                    raise
                except Exception as exc:  # noqa: BLE001
                    last_err = exc
                    logger.info(
                        "TPEX fetch attempt %d/%d failed for %s: %s",
                        attempt,
                        attempts,
                        code,
                        exc,
                    )
                finally:
                    context.close()
        finally:
            browser.close()

    raise TPEXBrokerUnavailable(f"TPEX 抓取失敗（重試 {attempts} 次）：{last_err}")


def _parse_rows(payload: dict | None) -> list[dict]:
    """把 brokerBS JSON 的分點表轉為 dataframe_from_rows 相容的 rows。"""
    if not payload or payload.get("stat") != "ok":
        raise TPEXBrokerUnavailable("TPEX 回應無有效資料（stat != ok）")

    broker_tbl = None
    for tbl in payload.get("tables") or []:
        fields = tbl.get("fields") or []
        if "買進股數" in fields and "券商" in fields:
            broker_tbl = tbl
            break
    if not broker_tbl or not broker_tbl.get("data"):
        raise TPEXBrokerUnavailable("查無分點資料（可能非當日、代號錯誤或非上櫃）")

    rows: list[dict] = []
    for r in broker_tbl["data"]:
        # r = [序號, "1020 合庫", "196.50", "1000", "0"]
        if not r or len(r) < 5:
            continue
        broker = str(r[1]).strip()
        if not broker:
            continue
        try:
            price = float(str(r[2]).replace(",", ""))
            buy = int(float(str(r[3]).replace(",", "")))
            sell = int(float(str(r[4]).replace(",", "")))
        except (ValueError, TypeError):
            continue
        rows.append(
            {"broker": broker, "price": price, "buy_volume": buy, "sell_volume": sell}
        )

    if not rows:
        raise TPEXBrokerUnavailable("分點資料解析後為空")
    return rows
