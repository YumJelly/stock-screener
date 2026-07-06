"""前 20 大主力分點「K 線價位區間對稱 T 型圖」headless 渲染。

移植自 ``ploting/BrokerIOChartTanalysis_V1.1.py``，去除 tkinter / plt.show，
改為 Agg backend，接受已正規化的分點 DataFrame（欄位 ``[Broker, Price, Buy,
Sell]``，單位：張），回傳 PNG bytes。同一份邏輯供：

- 單日圖：某 (stock, date) 的 snapshot。
- 期間累計圖：追蹤視窗內多日 snapshot 合併。
"""
from __future__ import annotations

import io
import logging

import matplotlib

matplotlib.use("Agg")  # headless；務必在 pyplot 之前設定

import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.gridspec as gridspec  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

logger = logging.getLogger(__name__)

_ZONES = ["低價區", "低價緩衝區", "均價交戰區", "高價緩衝區", "高價區"]
_BUY_COLORS = ["#058E07", "#7fc380", "#f0fa82", "#fd4d2d", "#FA0404"]
_SELL_COLORS = ["#058E07", "#7fc380", "#f0fa82", "#fd4d2d", "#FA0404"]

# 優先嘗試的 CJK 字型（Linux 伺服器常見）
_CJK_FONT_CANDIDATES = [
    "Microsoft JhengHei",
    "Noto Sans CJK TC",
    "Noto Sans CJK SC",
    "Noto Sans TC",
    "WenQuanYi Zen Hei",
    "WenQuanYi Micro Hei",
    "AR PL UMing TW",
    "Source Han Sans TW",
]

_font_configured = False


def _ensure_cjk_font() -> None:
    """挑選一個可用的 CJK 字型；找不到不致命（中文可能顯示為方框）。"""
    global _font_configured
    if _font_configured:
        return
    available = {f.name for f in font_manager.fontManager.ttflist}
    chosen = next((n for n in _CJK_FONT_CANDIDATES if n in available), None)
    if chosen:
        plt.rcParams["font.sans-serif"] = [chosen] + plt.rcParams.get(
            "font.sans-serif", []
        )
    else:
        logger.warning(
            "[broker_chart] 找不到 CJK 字型，圖表中文可能顯示為方框；"
            "候選：%s",
            ", ".join(_CJK_FONT_CANDIDATES),
        )
    plt.rcParams["axes.unicode_minus"] = False
    _font_configured = True


def _get_zone(price: float, b1: float, b2: float, b3: float, b4: float) -> str:
    if price <= b1:
        return "低價區"
    if price <= b2:
        return "低價緩衝區"
    if price <= b3:
        return "均價交戰區"
    if price <= b4:
        return "高價緩衝區"
    return "高價區"


def _build_matrices(df: pd.DataFrame):
    """回傳 (top20_brokers, buy_matrix, sell_matrix)。

    df 欄位 ``[Broker, Price, Buy, Sell]``（單位：張）。
    """
    df = df.copy()
    df["Broker"] = df["Broker"].astype(str).str.strip()
    for col in ("Price", "Buy", "Sell"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    broker_net = (
        df.groupby("Broker")
        .agg(buy_ts=("Buy", "sum"), sell_ts=("Sell", "sum"))
        .reset_index()
    )
    broker_net["abs_net"] = (broker_net["buy_ts"] - broker_net["sell_ts"]).abs()
    top20 = (
        broker_net.sort_values("abs_net", ascending=False)
        .head(20)["Broker"]
        .tolist()
    )

    low = float(df["Price"].min())
    high = float(df["Price"].max())
    if low == high:
        low -= 0.01
        high += 0.01
    rng = high - low
    b1 = low + rng * 0.10
    b2 = low + rng * 0.30
    b3 = low + rng * 0.70
    b4 = low + rng * 0.90
    df["zone"] = df["Price"].apply(lambda p: _get_zone(p, b1, b2, b3, b4))

    df_top = df[df["Broker"].isin(top20)]
    pivot = (
        df_top.groupby(["Broker", "zone"])
        .agg({"Buy": "sum", "Sell": "sum"})
        .reset_index()
    )

    n = len(top20)
    buy_matrix = np.zeros((n, len(_ZONES)))
    sell_matrix = np.zeros((n, len(_ZONES)))
    for i, broker in enumerate(top20):
        b_data = pivot[pivot["Broker"] == broker]
        for j, zone in enumerate(_ZONES):
            z = b_data[b_data["zone"] == zone]
            if not z.empty:
                buy_matrix[i, j] = z["Buy"].sum()
                sell_matrix[i, j] = z["Sell"].sum()
    return top20, buy_matrix, sell_matrix


def render_t_chart(df: pd.DataFrame, title: str) -> bytes:
    """繪製對稱 T 型圖，回傳 PNG bytes。

    Parameters
    ----------
    df : pd.DataFrame
        欄位 ``[Broker, Price, Buy, Sell]``（單位：張）。
    title : str
        圖表主標題。
    """
    if df is None or df.empty:
        raise ValueError("分點資料為空，無法繪製 T 型圖")

    _ensure_cjk_font()
    top20, buy_matrix, sell_matrix = _build_matrices(df)
    if not top20:
        raise ValueError("無有效分點資料，無法繪製 T 型圖")

    max_buy_row = buy_matrix.sum(axis=1).max()
    max_sell_row = sell_matrix.sum(axis=1).max()
    global_max_xlim = max(max_buy_row, max_sell_row, 1.0) * 1.05

    fig = plt.figure(figsize=(16, 9))
    try:
        gs = gridspec.GridSpec(1, 3, width_ratios=[45, 12, 45])
        ax_buy = plt.subplot(gs[0])
        ax_name = plt.subplot(gs[1])
        ax_sell = plt.subplot(gs[2])

        y_pos = np.arange(len(top20))
        buy_totals = buy_matrix.sum(axis=1)
        sell_totals = sell_matrix.sum(axis=1)

        # 買進（左，反向 x 軸）
        left_base = np.zeros(len(top20))
        for j in range(len(_ZONES)):
            ax_buy.barh(
                y_pos, buy_matrix[:, j], left=left_base,
                color=_BUY_COLORS[j], edgecolor="grey", height=0.6,
            )
            for i, width in enumerate(buy_matrix[:, j]):
                if width > 0:
                    ax_buy.text(
                        left_base[i] + width / 2, y_pos[i],
                        f"{int(round(width))}", ha="center", va="center",
                        fontsize=8, color="black",
                    )
            left_base += buy_matrix[:, j]
        for i, total in enumerate(buy_totals):
            ax_buy.annotate(
                f"總 {int(round(total))}", xy=(total, y_pos[i]),
                xytext=(-6, 0), textcoords="offset points",
                ha="right", va="center", fontsize=9, color="black", clip_on=False,
            )
        ax_buy.set_xlim(0, global_max_xlim)
        ax_buy.invert_xaxis()
        ax_buy.set_title("買進張數 (高 -> 中 -> 低)", fontsize=13, color="red", pad=15)
        ax_buy.grid(axis="x", linestyle="--", alpha=0.5)
        ax_buy.set_yticks(y_pos)
        ax_buy.set_yticklabels([])
        ax_buy.invert_yaxis()

        # 中間券商名稱 + 淨額
        ax_name.axis("off")
        for i, name in enumerate(top20):
            net_value = buy_totals[i] - sell_totals[i]
            ax_name.text(
                0.5, i, f"{name} ({int(round(net_value)):+,})",
                ha="center", va="center", fontsize=10, fontweight="bold",
            )
        ax_name.set_ylim(ax_buy.get_ylim())

        # 賣出（右）
        right_base = np.zeros(len(top20))
        for j in range(len(_ZONES)):
            ax_sell.barh(
                y_pos, sell_matrix[:, j], left=right_base,
                color=_SELL_COLORS[j], edgecolor="grey", height=0.6,
            )
            for i, width in enumerate(sell_matrix[:, j]):
                if width > 0:
                    ax_sell.text(
                        right_base[i] + width / 2, y_pos[i],
                        f"{int(round(width))}", ha="center", va="center",
                        fontsize=8, color="black",
                    )
            right_base += sell_matrix[:, j]
        for i, total in enumerate(sell_totals):
            ax_sell.annotate(
                f"總 {int(round(total))}", xy=(total, y_pos[i]),
                xytext=(6, 0), textcoords="offset points",
                ha="left", va="center", fontsize=9, color="black", clip_on=False,
            )
        ax_sell.set_xlim(0, global_max_xlim)
        ax_sell.set_title("賣出張數 (低 -> 中 -> 高)", fontsize=13, color="green", pad=15)
        ax_sell.grid(axis="x", linestyle="--", alpha=0.5)
        ax_sell.set_yticks(y_pos)
        ax_sell.set_yticklabels([])
        ax_sell.set_ylim(ax_buy.get_ylim())

        buy_handles = [
            Patch(facecolor=_BUY_COLORS[i], edgecolor="grey", label=f"{_ZONES[i]} 買量")
            for i in range(len(_ZONES))
        ]
        sell_handles = [
            Patch(facecolor=_SELL_COLORS[i], edgecolor="grey", label=f"{_ZONES[i]} 賣量")
            for i in range(len(_ZONES))
        ]
        fig.subplots_adjust(bottom=0.22)
        fig.legend(
            handles=buy_handles, loc="lower center",
            bbox_to_anchor=(0.5, 0.075), ncol=5, fontsize=10,
            frameon=True, edgecolor="grey", title="買量區間",
        )
        fig.legend(
            handles=sell_handles, loc="lower center",
            bbox_to_anchor=(0.5, 0.015), ncol=5, fontsize=10,
            frameon=True, edgecolor="grey", title="賣量區間",
        )
        fig.suptitle(title, fontsize=16, fontweight="bold", y=0.98)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        buf.seek(0)
        return buf.getvalue()
    finally:
        plt.close(fig)


# ── snapshot → chart builders ────────────────────────────────────────────────

_CHART_COLUMNS = ["Broker", "Price", "Buy", "Sell"]


def _rows_to_df(rows: list) -> pd.DataFrame:
    """把 snapshot 的 list[[broker, price, buy, sell]] 轉為 DataFrame。"""
    if not rows:
        return pd.DataFrame(columns=_CHART_COLUMNS)
    return pd.DataFrame(rows, columns=_CHART_COLUMNS)


def _stock_name(db, stock_id: str) -> str | None:
    """盡力取得中文名稱（.TW / .TWO 皆試）供圖表標題使用。"""
    try:
        from ...models.stock_universe import StockUniverse

        for cand in (stock_id, f"{stock_id}.TW", f"{stock_id}.TWO"):
            hit = (
                db.query(StockUniverse.name)
                .filter(StockUniverse.symbol == cand)
                .first()
            )
            if hit and hit[0]:
                return hit[0]
    except Exception:  # noqa: BLE001
        pass
    return None


def _stock_id_candidates(stock_id: str) -> list[str]:
    """snapshot 可能以 bare code 或帶市場後綴儲存，回傳嘗試順序。"""
    sid = (stock_id or "").strip().upper()
    bare = sid
    for suf in (".TW", ".TWO"):
        if bare.endswith(suf):
            bare = bare[: -len(suf)]
            break
    seen: list[str] = []
    for cand in (sid, bare, f"{bare}.TW", f"{bare}.TWO"):
        if cand and cand not in seen:
            seen.append(cand)
    return seen


def _resolve_snapshot_stock_id(db, stock_id: str) -> str | None:
    """找出實際有 snapshot 的 stock_id 變體。"""
    from ...models.chip_broker_snapshot import ChipBrokerSnapshot

    for cand in _stock_id_candidates(stock_id):
        hit = (
            db.query(ChipBrokerSnapshot.stock_id)
            .filter(ChipBrokerSnapshot.stock_id == cand)
            .first()
        )
        if hit:
            return hit[0]
    return None


def count_snapshot_days(db, stock_id: str) -> int:
    """回傳某股目前累積的 snapshot 天數（供決定是否送累計圖）。"""
    from ...models.chip_broker_snapshot import ChipBrokerSnapshot

    resolved = _resolve_snapshot_stock_id(db, stock_id)
    if resolved is None:
        return 0
    return (
        db.query(ChipBrokerSnapshot)
        .filter(ChipBrokerSnapshot.stock_id == resolved)
        .count()
    )



def build_daily_chart(db, stock_id: str, trade_date: str | None = None) -> bytes:
    """繪製某股單一交易日的 T 型圖（trade_date 省略時取最新一日）。"""
    from ...models.chip_broker_snapshot import ChipBrokerSnapshot

    resolved = _resolve_snapshot_stock_id(db, stock_id)
    if resolved is None:
        raise ValueError(f"查無 {stock_id} 的分點 snapshot（無法繪製單日 T 型圖）")

    q = db.query(ChipBrokerSnapshot).filter(
        ChipBrokerSnapshot.stock_id == resolved
    )
    if trade_date:
        snap = q.filter(ChipBrokerSnapshot.trade_date == trade_date).one_or_none()
    else:
        snap = q.order_by(ChipBrokerSnapshot.trade_date.desc()).first()
    if snap is None or not snap.rows:
        raise ValueError(f"查無 {stock_id} 的分點 snapshot（無法繪製單日 T 型圖）")

    name = _stock_name(db, resolved)
    header = f"{resolved} {name}" if name else resolved
    title = (
        f"{header}（{snap.trade_date}）前 20 大主力分點 K 線價位區間對稱 T 型圖"
    )
    return render_t_chart(_rows_to_df(snap.rows), title)


def build_cumulative_chart(
    db, stock_id: str, window_days: int = 30
) -> bytes:
    """繪製某股「期間累計」T 型圖，合併近 ``window_days`` 日的所有 snapshot。"""
    from ...models.chip_broker_snapshot import ChipBrokerSnapshot

    resolved = _resolve_snapshot_stock_id(db, stock_id)
    if resolved is None:
        raise ValueError(f"查無 {stock_id} 的分點 snapshot（無法繪製累計 T 型圖）")

    snaps = (
        db.query(ChipBrokerSnapshot)
        .filter(ChipBrokerSnapshot.stock_id == resolved)
        .order_by(ChipBrokerSnapshot.trade_date.desc())
        .limit(window_days)
        .all()
    )
    if not snaps:
        raise ValueError(f"查無 {stock_id} 的分點 snapshot（無法繪製累計 T 型圖）")

    frames = [_rows_to_df(s.rows) for s in snaps if s.rows]
    frames = [f for f in frames if not f.empty]
    if not frames:
        raise ValueError(f"{stock_id} 的分點 snapshot 皆為空，無法繪製累計 T 型圖")

    merged = pd.concat(frames, ignore_index=True)
    dates = sorted(s.trade_date for s in snaps if s.rows)
    n_days = len(dates)
    name = _stock_name(db, resolved)
    header = f"{resolved} {name}" if name else resolved
    span = f"{dates[0]}~{dates[-1]}" if dates else ""
    title = (
        f"{header}（{n_days} 日彙整 {span}）前 20 大主力分點 "
        "K 線價位區間對稱 T 型圖"
    )
    return render_t_chart(merged, title)
