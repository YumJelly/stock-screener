# 為了讓左右兩側圖表的軸距（X軸範圍）完全一致以利橫向對比，
# 我們需要在計算出買進與賣出矩陣的橫向累積最大值後，找出全域的最大限界值 (global_max_xlim)。
# 然後，強制將左圖與右圖的 X 軸上限設定為同一個數值：ax.set_xlim(0, global_max_xlim)。

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import Patch
import csv
import io
import re
import tkinter as tk
from tkinter import filedialog
from pathlib import Path


def get_zone(price, b1, b2, b3, b4):
    if price <= b1:
        return '低價區'
    elif price <= b2:
        return '低價緩衝區'
    elif price <= b3:
        return '均價交戰區'
    elif price <= b4:
        return '高價緩衝區'
    return '高價區'


def _normalize_column_name(name):
    return str(name).strip().lstrip('\ufeff').replace(' ', '').replace('　', '').replace('_', '').lower()


def _standardize_broker_columns(df):
    df = df.copy()
    df.columns = [str(col).strip().lstrip('\ufeff') for col in df.columns]

    column_aliases = {
        'broker_code': ['broker_code', 'brokercode', '券商代號', '券商代碼', '代號'],
        'broker_name': ['broker_name', 'brokername', '券商名稱', '分點名稱', '名稱', '券商'],
        'price': ['price', '單價', '價格', '成交價'],
        'buy_volume': ['buy_volume', 'buyvolume', '買進股數', '買進張數', '買進量'],
        'sell_volume': ['sell_volume', 'sellvolume', '賣出股數', '賣出張數', '賣出量'],
    }

    lookup = {_normalize_column_name(col): col for col in df.columns}
    rename_map = {}
    for canonical_name, aliases in column_aliases.items():
        for alias in aliases:
            normalized_alias = _normalize_column_name(alias)
            if normalized_alias in lookup:
                rename_map[lookup[normalized_alias]] = canonical_name
                break

    if rename_map:
        df = df.rename(columns=rename_map)

    required_columns = ['broker_code', 'broker_name', 'price', 'buy_volume', 'sell_volume']
    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        raise KeyError(f"缺少必要欄位: {', '.join(missing_columns)}；可用欄位: {', '.join(map(str, df.columns))}")

    for column in ['broker_code', 'broker_name']:
        df[column] = df[column].astype(str).str.strip()

    for column in ['price', 'buy_volume', 'sell_volume']:
        df[column] = pd.to_numeric(
            df[column].astype(str).str.replace(',', '', regex=False).str.strip(),
            errors='coerce'
        ).fillna(0)

    return df


def _looks_like_header_row(values):
    tokens = {_normalize_column_name(value) for value in values if str(value).strip()}
    known_tokens = {
        _normalize_column_name(alias)
        for aliases in {
            'broker_code': ['broker_code', 'brokercode', '券商代號', '券商代碼', '代號'],
            'broker_name': ['broker_name', 'brokername', '券商名稱', '分點名稱', '名稱', '券商'],
            'price': ['price', '單價', '價格', '成交價'],
            'buy_volume': ['buy_volume', 'buyvolume', '買進股數', '買進張數', '買進量'],
            'sell_volume': ['sell_volume', 'sellvolume', '賣出股數', '賣出張數', '賣出量'],
        }.values()
        for alias in aliases
    }
    return bool(tokens & known_tokens)


def _standardize_headerless_broker_columns(df):
    df = df.copy()
    df = df.dropna(axis=1, how='all').dropna(axis=0, how='all').reset_index(drop=True)

    if df.empty:
        raise ValueError('CSV 內容為空')

    first_row = df.iloc[0].astype(str).tolist()
    if _looks_like_header_row(first_row):
        df.columns = first_row
        df = df.iloc[1:].reset_index(drop=True)
        return _standardize_broker_columns(df)

    width = df.shape[1]

    if width >= 9:
        df = df.iloc[:, :9].copy()
        df.columns = ['symbol', 'name', 'seq', 'broker_code', 'broker_name', 'price', 'buy_volume', 'sell_volume', 'trade_type']
        return _standardize_broker_columns(df)

    if width >= 6:
        df = df.iloc[:, :6].copy()
        df.columns = ['seq', 'broker_raw', 'price', 'buy_volume', 'sell_volume', 'trade_type']
        df['broker_raw'] = df['broker_raw'].astype(str).str.strip()
        broker_parts = df['broker_raw'].str.split(' ', n=1, expand=True)
        df['broker_code'] = broker_parts[0].fillna('').astype(str).str.strip()
        if broker_parts.shape[1] > 1:
            df['broker_name'] = broker_parts[1].fillna('').astype(str).str.strip()
        else:
            df['broker_name'] = df['broker_raw']
        df = df.drop(columns=['broker_raw', 'seq', 'trade_type'], errors='ignore')
        return _standardize_broker_columns(df)

    if width >= 5:
        df = df.iloc[:, :5].copy()
        df.columns = ['broker_code', 'broker_name', 'price', 'buy_volume', 'sell_volume']
        return _standardize_broker_columns(df)

    raise KeyError(f'無法推斷 CSV 欄位，共 {width} 欄')


def _load_broker_dataframe(path):
    try:
        return _standardize_broker_columns(pd.read_csv(path, dtype=str))
    except Exception:
        pass

    try:
        raw_df = pd.read_csv(path, header=None, dtype=str)
        return _standardize_headerless_broker_columns(raw_df)
    except Exception as exc:
        pass

    text = None
    last_exc = None
    for encoding in ('utf-8-sig', 'utf-8', 'cp950', 'big5'):
        try:
            text = Path(path).read_text(encoding=encoding)
            break
        except Exception as exc:
            last_exc = exc

    if text is None:
        raise ValueError(f'{Path(path).name} 無法讀取：{last_exc}') from last_exc

    rows = []
    reader = csv.reader(io.StringIO(text))
    for row in reader:
        cleaned_row = [cell.strip() for cell in row]
        if any(cleaned_row):
            rows.append(cleaned_row)

    if not rows:
        raise ValueError(f'{Path(path).name} 內容為空')

    records = []
    stock_symbol = ''
    stock_name = ''
    in_data = False

    def parse_broker_raw(value):
        value = str(value).strip()
        match = re.match(r'^(\d+)\s*(.*)$', value)
        if match:
            return match.group(1), match.group(2).strip() or match.group(1)
        parts = value.split(' ', 1)
        if len(parts) == 2 and parts[0].strip():
            return parts[0].strip(), parts[1].strip()
        return value, value

    for row in rows:
        first = row[0].strip() if row else ''
        normalized_first = _normalize_column_name(first)

        if len(row) >= 2 and normalized_first in {'證券代碼', '證券代號', '股票代碼', '股票代號', '代碼', '代號'}:
            stock_symbol = row[1].strip().strip('="').strip('"')
            if len(row) >= 3:
                stock_name = row[2].strip()
            continue

        if normalized_first == '序號' and len(row) >= 5 and '券商' in row[1]:
            in_data = True
            continue

        if not in_data or not first.isdigit() or len(row) < 5:
            continue

        broker_code, broker_name = parse_broker_raw(row[1])
        records.append({
            'symbol': stock_symbol,
            'name': stock_name,
            'seq': int(first),
            'broker_code': broker_code,
            'broker_name': broker_name,
            'price': row[2],
            'buy_volume': row[3],
            'sell_volume': row[4],
            'trade_type': row[5] if len(row) > 5 and row[5] else '一般',
        })

    if not records:
        raise ValueError(f'{Path(path).name} 無法解析，最後錯誤：{last_exc}')

    return _standardize_broker_columns(pd.DataFrame.from_records(records))


def load_and_prepare_data(csv_paths):
    frames = []
    for path in csv_paths:
        try:
            frames.append(_load_broker_dataframe(path))
        except Exception as e:
            print(f"{Path(path).name} 欄位對應失敗，已跳過：{e}")

    if not frames:
        raise ValueError('所有 CSV 都無法完成欄位對應，請確認檔案格式或欄位位置。')

    df = pd.concat(frames, ignore_index=True)    
    try:     
        df['broker_code'] = df['broker_code'].astype(str)
        df['broker_name'] = df['broker_name'].astype(str)
        mismatch_mask = df['broker_code'] != df['broker_name']
        df.loc[mismatch_mask, 'broker_name'] = (
            df.loc[mismatch_mask, 'broker_code']
            + df.loc[mismatch_mask, 'broker_name'].str.lstrip()
        )
    except Exception as e:
        print("非上市編號,跳過券商分點名稱合併作業")

    df['buy_ts'] = (df['buy_volume'] / 1000).astype(int)
    df['sell_ts'] = (df['sell_volume'] / 1000).astype(int)
    df['net_vol'] = ((df['buy_volume'] - df['sell_volume']) / 1000).astype(int)
    #df['net_vol'] = (df['buy_ts'] - df['sell_ts']).abs()    
    broker_net = df.groupby('broker_name').agg(
        buy_ts=('buy_ts', 'sum'),
        sell_ts=('sell_ts', 'sum'),
        net_vol=('net_vol', 'sum')
    ).reset_index()
    #broker_net['abs_net'] = broker_net['net_vol'].abs()
    broker_net['abs_net'] = (broker_net['buy_ts'] - broker_net['sell_ts']).abs()
    broker_net.reset_index(drop=True, inplace=True)

    top20_brokers = broker_net.sort_values(by='abs_net', ascending=False).head(20)['broker_name'].tolist()

    #top20_net_map = broker_net.set_index('broker_name')['net_vol'].to_dict()
    top20_net_map = broker_net.set_index('broker_name')['abs_net'].to_dict()


    low = df['price'].min()
    high = df['price'].max()
    if low == high:
        low -= 0.01
        high += 0.01
    rng = high - low
    b1 = low + rng * 0.10
    b2 = low + rng * 0.30
    b3 = low + rng * 0.70
    b4 = low + rng * 0.90
    df['zone'] = df['price'].apply(lambda price: get_zone(price, b1, b2, b3, b4))

    df_top20 = df[df['broker_name'].isin(top20_brokers)]
    pivot_data = df_top20.groupby(['broker_name', 'zone']).agg({'buy_ts': 'sum', 'sell_ts': 'sum'}).reset_index()

    zones = ['低價區', '低價緩衝區', '均價交戰區', '高價緩衝區', '高價區']
    num_brokers = len(top20_brokers)
    buy_matrix = np.zeros((num_brokers, len(zones)))
    sell_matrix = np.zeros((num_brokers, len(zones)))

    for i, broker_name in enumerate(top20_brokers):
        broker_data = pivot_data[pivot_data['broker_name'] == broker_name]
        row_buy_total = 0
        row_sell_total = 0
        for j, zone in enumerate(zones):
            zone_data = broker_data[broker_data['zone'] == zone]
            if not zone_data.empty:
                buy_value = zone_data['buy_ts'].sum()
                sell_value = zone_data['sell_ts'].sum()
                buy_matrix[i, j] = buy_value
                sell_matrix[i, j] = sell_value
                row_buy_total += buy_value
                row_sell_total += sell_value
        row_net = row_buy_total - row_sell_total
        #print(
        #    broker_name,
        #    'buy_total=', row_buy_total,
        #    'sell_total=', row_sell_total,
        #    'net=', row_net,
        #    'buy_row=', buy_matrix[i].tolist(),
        #    'sell_row=', sell_matrix[i].tolist()
        #)
        

    zone_counts = df['zone'].value_counts().reindex(zones, fill_value=0)
    print(f'Price range used for zones: {low:.2f} ~ {high:.2f}')
    print("分隔區間:",b1,b2,b3,b4)
    #print('Zone counts: ' + ', '.join(f'{zone}={int(zone_counts[zone])}' for zone in zones))
    #print(broker_net.sort_values(by='net_vol', ascending=False).head(15).to_string(index=False))    
    #print(top20_brokers)   
    #print(top20_net_map)
    #print(buy_matrix) 
    return top20_brokers, zones, buy_matrix, sell_matrix, top20_net_map


def plot_chart(top20_brokers, zones, buy_matrix, sell_matrix, top20_net_map, output_path, chart_title):
    max_buy_row = buy_matrix.sum(axis=1).max()
    max_sell_row = sell_matrix.sum(axis=1).max()
    global_max_xlim = max(max_buy_row, max_sell_row) * 1.05

    plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei']
    plt.rcParams['axes.unicode_minus'] = False

    fig = plt.figure(figsize=(16, 9))
    gs = gridspec.GridSpec(1, 3, width_ratios=[45, 10, 45])

    ax_buy = plt.subplot(gs[0])
    ax_name = plt.subplot(gs[1])
    ax_sell = plt.subplot(gs[2])

    buy_colors  = ["#058E07", "#7fc380", "#f0fa82", "#fd4d2d", "#FA0404"]
    sell_colors = ["#058E07", "#7fc380", "#f0fa82", "#fd4d2d", "#FA0404"]
    y_pos = np.arange(len(top20_brokers))
    buy_totals = buy_matrix.sum(axis=1)
    sell_totals = sell_matrix.sum(axis=1)

    left_base = np.zeros(len(top20_brokers))
    for j in range(len(zones)):
        ax_buy.barh(y_pos, buy_matrix[:, j], left=left_base, color=buy_colors[j], label=f'{zones[j]} 買量', edgecolor='grey', height=0.6)
        for i, width in enumerate(buy_matrix[:, j]):
            if width > 0:
                ax_buy.text(
                    left_base[i] + width / 2,
                    y_pos[i],
                    f'{int(round(width))}',
                    ha='center',
                    va='center',
                    fontsize=8,
                    color='black'
                )
        left_base += buy_matrix[:, j]
    for i, total in enumerate(buy_totals):
        ax_buy.annotate(
            f'總 {int(round(total))}',
            xy=(total, y_pos[i]),
            xytext=(-6, 0),
            textcoords='offset points',
            ha='right',
            va='center',
            fontsize=9,
            color='black',
            clip_on=False
        )
    ax_buy.set_xlim(0, global_max_xlim)
    ax_buy.invert_xaxis()
    ax_buy.set_title('買進張數 (高 -> 中 -> 低)', fontsize=13, color='red', pad=15)
    ax_buy.grid(axis='x', linestyle='--', alpha=0.5)
    ax_buy.set_yticks(y_pos)
    ax_buy.set_yticklabels([])
    ax_buy.invert_yaxis()

    ax_name.axis('off')
    for i, name in enumerate(top20_brokers):
        net_value = buy_totals[i] - sell_totals[i]
        ax_name.text(
            0.5,
            i,
            f'{name} ({int(round(net_value)):+,})',
            ha='center',
            va='center',
            fontsize=11,
            fontweight='bold'
        )
    ax_name.set_ylim(ax_buy.get_ylim())

    right_base = np.zeros(len(top20_brokers))
    for j in range(len(zones)):
        ax_sell.barh(y_pos, sell_matrix[:, j], left=right_base, color=sell_colors[j], label=f'{zones[j]} 賣量', edgecolor='grey', height=0.6)
        for i, width in enumerate(sell_matrix[:, j]):
            if width > 0:
                ax_sell.text(
                    right_base[i] + width / 2,
                    y_pos[i],
                    f'{int(round(width))}',
                    ha='center',
                    va='center',
                    fontsize=8,
                    color='black'
                )
        right_base += sell_matrix[:, j]
    for i, total in enumerate(sell_totals):
        ax_sell.annotate(
            f'總 {int(round(total))}',
            xy=(total, y_pos[i]),
            xytext=(6, 0),
            textcoords='offset points',
            ha='left',
            va='center',
            fontsize=9,
            color='black',
            clip_on=False
        )
    ax_sell.set_xlim(0, global_max_xlim)
    ax_sell.set_title('賣出張數 (低 -> 中 -> 高)', fontsize=13, color='green', pad=15)
    ax_sell.grid(axis='x', linestyle='--', alpha=0.5)
    ax_sell.set_yticks(y_pos)
    ax_sell.set_yticklabels([])
    ax_sell.set_ylim(ax_buy.get_ylim())

    buy_handles = [Patch(facecolor=buy_colors[i], edgecolor='grey', label=f'{zones[i]} 買量') for i in range(len(zones))]
    sell_handles = [Patch(facecolor=sell_colors[i], edgecolor='grey', label=f'{zones[i]} 賣量') for i in range(len(zones))]

    fig.subplots_adjust(bottom=0.22)
    fig.legend(
        handles=buy_handles,
        loc='lower center',
        bbox_to_anchor=(0.5, 0.075),
        ncol=5,
        fontsize=10,
        frameon=True,
        edgecolor='grey',
        title='買量區間'
    )
    fig.legend(
        handles=sell_handles,
        loc='lower center',
        bbox_to_anchor=(0.5, 0.015),
        ncol=5,
        fontsize=10,
        frameon=True,
        edgecolor='grey',
        title='賣量區間'
    )

    plt.suptitle(chart_title, fontsize=16, fontweight='bold', y=0.98)
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.show()
    plt.close(fig)


def main(csv_paths):
    first_file_stem = Path(csv_paths[0]).stem
    parts = first_file_stem.split('_', 1)
    stock_no = parts[0] if parts else first_file_stem
    chart_title = f'{stock_no} ({len(csv_paths)}日彙整) 前 20 大主力分點 K 線價位區間對稱 T 型圖 (依資料價格自動五分區)'

    output_path = 'broker_t_chart_shared_xlim.png'
    top20_brokers, zones, buy_matrix, sell_matrix, top20_net_map = load_and_prepare_data(csv_paths)
    plot_chart(top20_brokers, zones, buy_matrix, sell_matrix, top20_net_map, output_path, chart_title)
    print('Shared xlim applied successfully.')


if __name__ == '__main__':
    while True:
        root = tk.Tk()
        root.withdraw()
        csv_paths = filedialog.askopenfilenames(
            title='選擇一個或多個 CSV 檔案',
            filetypes=[('CSV files', '*.csv'), ('All files', '*.*')]
        )
        root.destroy()

        if not csv_paths:
            print('未選擇檔案，已取消執行。')
            break

        invalid_paths = [path for path in csv_paths if not Path(path).stem]
        if invalid_paths:
            print('檔名無法取得，已結束迴圈。')
            break

        main(list(csv_paths))