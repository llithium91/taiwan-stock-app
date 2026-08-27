import sqlite3
import time
from datetime import datetime, timedelta
import warnings
import pandas as pd
import requests

warnings.filterwarnings("ignore")

DB_PATH = "taiwan_stock_daily.db"


def fetch_twse_tpex_daily(date_str):
    """從證交所 (TWSE) 與櫃買中心 (TPEx) 下載全市場當日收盤數據"""
    formatted_date = date_str.replace("-", "")
    records = []

    # 1. 上市股票 (TWSE)
    twse_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    twse_url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={formatted_date}&type=ALLBUT0999&response=json"

    for attempt in range(4):
        try:
            res = requests.get(twse_url, headers=twse_headers, timeout=15)
            data = res.json()
            if data.get("stat") == "OK":
                for t in data.get("tables", []):
                    if "每日收盤行情" in t.get("title", ""):
                        for row in t.get("data", []):
                            stock_id = row[0].strip()
                            if len(stock_id) == 4 and stock_id.isdigit():
                                try:
                                    close_p = float(
                                        row[8].replace(",", "").strip()
                                    )
                                    open_p = float(
                                        row[5].replace(",", "").strip()
                                    )
                                    max_p = float(
                                        row[6].replace(",", "").strip()
                                    )
                                    min_p = float(
                                        row[7].replace(",", "").strip()
                                    )
                                    vol = int(row[2].replace(",", "").strip())
                                    stock_name = row[1].strip()

                                    records.append(
                                        {
                                            "date": date_str,
                                            "stock_id": stock_id,
                                            "stock_name": stock_name,
                                            "open": open_p,
                                            "max": max_p,
                                            "min": min_p,
                                            "close": close_p,
                                            "Trading_Volume": vol,
                                        }
                                    )
                                except ValueError:
                                    continue
                break
        except Exception:
            time.sleep(1)

    # 2. 上櫃股票 (TPEx)
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    roc_date = f"{dt.year - 1911}/{dt.month:02d}/{dt.day:02d}"
    tpex_url = f"https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&o=json&d={roc_date}"

    tpex_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Referer": "https://www.tpex.org.tw/",
    }

    for attempt in range(4):
        try:
            res = requests.get(tpex_url, headers=tpex_headers, timeout=20)
            data = res.json()
            if "aaData" in data:
                for row in data["aaData"]:
                    stock_id = row[0].strip()
                    if len(stock_id) == 4 and stock_id.isdigit():
                        try:
                            close_p = float(row[2].replace(",", "").strip())
                            open_p = float(row[4].replace(",", "").strip())
                            max_p = float(row[5].replace(",", "").strip())
                            min_p = float(row[6].replace(",", "").strip())
                            vol = int(row[8].replace(",", "").strip())
                            stock_name = row[1].strip()

                            records.append(
                                {
                                    "date": date_str,
                                    "stock_id": stock_id,
                                    "stock_name": stock_name,
                                    "open": open_p,
                                    "max": max_p,
                                    "min": min_p,
                                    "close": close_p,
                                    "Trading_Volume": vol,
                                }
                            )
                        except ValueError:
                            continue
                break
        except Exception as e:
            if attempt == 3:
                print(f"\n⚠️ 抓取 TPEx 失敗 ({date_str}): {e}")
            time.sleep(2.0)

    return pd.DataFrame(records)


def update_database(progress_callback=None):
    """更新全市場資料庫 (具備自動回溯補齊功能)"""
    conn = sqlite3.connect(DB_PATH)

    today = datetime.now()
    trading_dates = []

    for i in range(110):
        d = today - timedelta(days=i)
        if d.weekday() < 5:
            trading_dates.append(d.strftime("%Y-%m-%d"))

    trading_dates = trading_dates[::-1]
    total_days = len(trading_dates)

    if progress_callback:
        progress_callback(
            0, total_days, f"🚀 連線證交所/櫃買中心 (共 {total_days} 個交易日)..."
        )

    all_dfs = []
    for idx, date_str in enumerate(trading_dates, 1):
        time.sleep(0.4)
        df_day = fetch_twse_tpex_daily(date_str)

        if not df_day.empty:
            all_dfs.append(df_day)
            msg = f"📥 [下載中 {idx}/{total_days}] 日期: {date_str} (取得 {len(df_day)} 檔股票)"
        else:
            msg = f"☕ [休市/無數據 {idx}/{total_days}] 日期: {date_str}"

        if progress_callback:
            progress_callback(idx, total_days, msg)

    if all_dfs:
        if progress_callback:
            progress_callback(
                total_days, total_days, "💾 正在整理數據並寫入 SQLite 資料庫..."
            )

        full_df = pd.concat(all_dfs, ignore_index=True)
        grouped = full_df.groupby("stock_id")
        total_stocks = len(grouped)

        for idx, (s_id, group_df) in enumerate(grouped, 1):
            table_name = f"stock_{s_id}"
            group_df.to_sql(table_name, conn, if_exists="replace", index=False)

            if progress_callback and (
                idx % 200 == 0 or idx == total_stocks
            ):
                progress_callback(
                    total_days,
                    total_days,
                    f"⚙️ 寫入資料庫進度: {idx}/{total_stocks} 檔股票",
                )

        if progress_callback:
            progress_callback(
                total_days,
                total_days,
                f"✅ 更新完成！共成功備份 {total_stocks} 檔台股個股數據。",
            )

    conn.close()


if __name__ == "__main__":
    update_database()