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
        except Exception:
            time.sleep(1.5)

    return pd.DataFrame(records)


def get_db_latest_date(conn):
    """檢查資料庫中現有的最新日期"""
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]

        if not tables:
            return None

        # 抽查前 10 檔表格取得最大日期
        latest_dates = []
        for t in tables[:10]:
            try:
                df = pd.read_sql_query(
                    f"SELECT date FROM {t} ORDER BY date DESC LIMIT 1", conn
                )
                if not df.empty:
                    latest_dates.append(df["date"].iloc[0])
            except Exception:
                continue

        return max(latest_dates) if latest_dates else None
    except Exception:
        return None


def update_database(progress_callback=None):
    """智慧增量更新資料庫 (資料庫有舊資料時僅補抓欠缺日期，極速完成)"""
    conn = sqlite3.connect(DB_PATH)

    db_latest = get_db_latest_date(conn)
    today = datetime.now()

    trading_dates = []

    if db_latest is None:
        # 【全量初始化】資料庫空白，抓過去 80 個交易日 (約 110 日曆天)
        lookback_days = 110
        if progress_callback:
            progress_callback(
                0, 100, "🔍 資料庫初次建立，將備份歷史 80 個交易日數據..."
            )
    else:
        # 【智慧增量更新】只補抓最新日期之後的缺漏交易日
        latest_dt = datetime.strptime(db_latest, "%Y-%m-%d")
        delta_days = (today - latest_dt).days

        if delta_days <= 0:
            if progress_callback:
                progress_callback(
                    1, 1, f"✅ 資料庫已是最新狀態 ({db_latest})，無需更新！"
                )
            conn.close()
            return

        lookback_days = delta_days

    # 產生需要補抓的日期清單
    for i in range(lookback_days, 0, -1):
        d = today - timedelta(days=i)
        if d.weekday() < 5:  # 排除週末
            date_str = d.strftime("%Y-%m-%d")
            if db_latest is None or date_str > db_latest:
                trading_dates.append(date_str)

    total_days = len(trading_dates)

    if total_days == 0:
        if progress_callback:
            progress_callback(1, 1, "✅ 目前已是最新交易日數據！")
        conn.close()
        return

    if progress_callback:
        progress_callback(
            0,
            total_days,
            f"🚀 啟動智慧增量更新，僅需抓取欠缺的 {total_days} 個交易日...",
        )

    all_dfs = []
    for idx, date_str in enumerate(trading_dates, 1):
        time.sleep(0.3)
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
                total_days, total_days, "💾 正在將新數據追加 (Append) 至 SQLite..."
            )

        full_df = pd.concat(all_dfs, ignore_index=True)
        grouped = full_df.groupby("stock_id")
        total_stocks = len(grouped)

        for idx, (s_id, group_df) in enumerate(grouped, 1):
            table_name = f"stock_{s_id}"

            if db_latest is None:
                # 第一次全量直接覆蓋
                group_df.to_sql(
                    table_name, conn, if_exists="replace", index=False
                )
            else:
                # 增量更新：先讀取既有資料，結合新數據並去重後寫回
                try:
                    existing_df = pd.read_sql_query(
                        f"SELECT * FROM {table_name}", conn
                    )
                    combined_df = pd.concat(
                        [existing_df, group_df], ignore_index=True
                    )
                    combined_df = combined_df.drop_duplicates(
                        subset=["date"]
                    ).sort_values("date")
                    combined_df.to_sql(
                        table_name, conn, if_exists="replace", index=False
                    )
                except Exception:
                    group_df.to_sql(
                        table_name, conn, if_exists="replace", index=False
                    )

            if progress_callback and (
                idx % 300 == 0 or idx == total_stocks
            ):
                progress_callback(
                    total_days,
                    total_days,
                    f"⚙️ 增量寫入進度: {idx}/{total_stocks} 檔股票",
                )

        if progress_callback:
            progress_callback(
                total_days,
                total_days,
                f"✅ 更新完成！成功補充 {total_days} 個交易日數據。",
            )

    conn.close()


if __name__ == "__main__":
    update_database()