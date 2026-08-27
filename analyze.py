import sqlite3
import pandas as pd
from strategies import check_stock_strategies

DB_PATH = "taiwan_stock_daily.db"


def run_cross_analysis(
    selected_strategies, breakout_vol_ratio=1.8, attack_vol_ratio=2.0
):
    """執行全市場多策略交叉比對"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]

    results = []

    for table in tables:
        stock_id = table.replace("stock_", "")
        try:
            df = pd.read_sql_query(
                f"SELECT * FROM {table} ORDER BY date ASC", conn
            )
            if df.empty or len(df) < 60:
                continue

            stock_name = (
                df["stock_name"].iloc[-1]
                if "stock_name" in df.columns
                else stock_id
            )

            strat_res = check_stock_strategies(
                df,
                breakout_vol_ratio=breakout_vol_ratio,
                attack_vol_ratio=attack_vol_ratio,
            )

            if not strat_res:
                continue

            match_all = all(
                strat_res.get(key, False) for key in selected_strategies
            )

            if match_all:
                passed_count = sum(
                    1
                    for k in [
                        "S1_突破平台",
                        "S2_均線多頭",
                        "S3_MACD動能",
                        "S4_量價爆量",
                    ]
                    if strat_res.get(k, False)
                )

                item = {
                    "股票代碼": stock_id,
                    "股票名稱": stock_name,
                    "收盤價": strat_res["收盤價"],
                    "今日漲跌(%)": strat_res["今日漲跌(%)"],
                    "成交量(張)": strat_res["成交量(張)"],
                    "符合策略數": passed_count,
                    "S1_突破平台": "✅" if strat_res["S1_突破平台"] else "❌",
                    "S2_均線多頭": "✅" if strat_res["S2_均線多頭"] else "❌",
                    "S3_MACD動能": "✅" if strat_res["S3_MACD動能"] else "❌",
                    "S4_量價爆量": "✅" if strat_res["S4_量價爆量"] else "❌",
                    "月線日均斜率(%)": strat_res["月線日均斜率(%)"],
                    "突破爆量倍數": strat_res["突破爆量倍數"],
                    "爆量攻擊倍數": strat_res["爆量攻擊倍數"],
                }
                results.append(item)

        except Exception:
            continue

    conn.close()

    res_df = pd.DataFrame(results)
    if not res_df.empty:
        res_df = res_df.sort_values(
            by=["符合策略數", "成交量(張)"], ascending=[False, False]
        )

    return res_df