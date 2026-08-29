import os
import sqlite3
import time
from datetime import datetime, timedelta
import warnings
import pandas as pd
import requests
from sqlalchemy import create_engine

warnings.filterwarnings("ignore")

# 優先讀取環境變數 SUPABASE_URL，若無則降級回本機 SQLite
DB_URI = os.getenv("SUPABASE_URL", "sqlite:///taiwan_stock_daily.db")


def get_db_engine():
    """建立穩定連線的 SQLAlchemy Engine (適應 Supabase Connection Pooler)"""
    if DB_URI.startswith("sqlite"):
        return create_engine(DB_URI)
    return create_engine(
        DB_URI,
        pool_pre_ping=True,  # 自動檢查連線活性，避免開頭卡住
        pool_size=5,
        max_overflow=10,
        connect_args={"connect_timeout": 30},
    )


def fetch_twse_tpex_daily(date_str):
    """從證交所 (TWSE) 與櫃買中心 (TPEx) 下載全市場當日收盤數據"""
    formatted_date = date_str.replace("-", "")
    records = []

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

                                    records.append({
                                        "date": date_str,
                                        "stock_id": stock_id,
                                        "stock_name": stock_name,
                                        "open": open_p,
                                        "max": max_p,
                                        "min": min_p,
                                        "close": close_p,
                                        "Trading_Volume": vol,
                                    })
                                except ValueError:
                                    continue
                break
        except Exception:
            time.sleep(1)

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

                            records.append({
                                "date": date_str,
                                "stock_id": stock_id,
                                "stock_name": stock_name,
                                "open": open_p,
                                "max": max_p,
                                "min": min_p,
                                "close": close_p,
                                "Trading_Volume": vol,
                            })
                        except ValueError:
                            continue
                break
        except Exception as e:
            if attempt == 3:
                print(f"\n⚠️ 抓取 TPEx 失敗 ({date_str}): {e}")
            time.sleep(2.0)

    return pd.DataFrame(records)


def update_database(progress_callback=None):
    """更新全市場資料庫 (優化 Supabase 分批 Chunk 寫入機制)"""
    engine = get_db_engine()

    today = datetime.now()
    trading_dates = []

    # 回溯 70 天 (約 50 個交易日，剛好滿 60MA)
    for i in range(70):
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
        time.sleep(0.2)
        df_day = fetch_twse_tpex_daily(date_str)

        if not df_day.empty:
            all_dfs.append(df_day)
            msg = f"📥 [下載中 {idx}/{total_days}] 日期: {date_str} (取得 {len(df_day)} 檔)"
        else:
            msg = f"☕ [休市/無數據 {idx}/{total_days}] 日期: {date_str}"

        if progress_callback:
            progress_callback(idx, total_days, msg)

    if all_dfs:
        if progress_callback:
            progress_callback(
                total_days, total_days, "💾 正在將數據分批寫入 Supabase 雲端資料庫..."
            )

        full_df = pd.concat(all_dfs, ignore_index=True)

        # 核心關鍵修復：加入 chunksize=2000 與 method='multi'，避免單次 SQL 語句過大連線卡住
        if DB_URI.startswith("sqlite"):
            full_df.to_sql(
                "taiwan_stocks_daily", engine, if_exists="replace", index=False
            )
        else:
            # 雲端 Supabase PostgreSQL 優化分批寫入
            full_df.to_sql(
                "taiwan_stocks_daily",
                engine,
                if_exists="replace",
                index=False,
                chunksize=2000,
                method="multi",
            )

        if progress_callback:
            progress_callback(
                total_days,
                total_days,
                f"✅ 寫入完成！共成功備份 {len(full_df['stock_id'].unique())} 檔股票數據。",
            )

    engine.dispose()


if __name__ == "__main__":
    update_database()
