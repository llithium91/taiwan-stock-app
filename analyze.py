import os
import pandas as pd
from sqlalchemy import create_engine, text
from strategies import check_stock_strategies

DB_URI = os.getenv("SUPABASE_URL", "sqlite:///taiwan_stock_daily.db")


def get_db_engine():
    if DB_URI.startswith("sqlite"):
        return create_engine(DB_URI)
    return create_engine(DB_URI, pool_pre_ping=True)


def run_cross_analysis(
    selected_strategies, breakout_vol_ratio=1.8, attack_vol_ratio=2.0
):
    """全市場多策略交叉比對 (支援 Supabase 與 SQLite)"""
    engine = get_db_engine()

    results = []

    try:
        if DB_URI.startswith("sqlite"):
            # 舊 SQLite 邏輯
            with engine.connect() as conn:
                res = conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table';")
                )
                tables = [row[0] for row in res.fetchall()]

            for table in tables:
                stock_id = table.replace("stock_", "")
                df = pd.read_sql_query(
                    f"SELECT * FROM {table} ORDER BY date ASC", engine
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

                if all(
                    strat_res.get(key, False) for key in selected_strategies
                ):
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
                    results.append({
                        "股票代碼": stock_id,
                        "股票名稱": stock_name,
                        "收盤價": strat_res["收盤價"],
                        "今日漲跌(%)": strat_res["今日漲跌(%)"],
                        "成交量(張)": strat_res["成交量(張)"],
                        "符合策略數": passed_count,
                        "S1_突破平台": (
                            "✅" if strat_res["S1_突破平台"] else "❌"
                        ),
                        "S2_均線多頭": (
                            "✅" if strat_res["S2_均線多頭"] else "❌"
                        ),
                        "S3_MACD動能": (
                            "✅" if strat_res["S3_MACD動能"] else "❌"
                        ),
                        "S4_量價爆量": (
                            "✅" if strat_res["S4_量價爆量"] else "❌"
                        ),
                        "月線日均斜率(%)": strat_res["月線日均斜率(%)"],
                        "突破爆量倍數": strat_res["突破爆量倍數"],
                        "爆量攻擊倍數": strat_res["爆量攻擊倍數"],
                    })
        else:
            # Supabase PostgreSQL 單一總表加速讀取
            full_df = pd.read_sql_table("taiwan_stocks_daily", engine)
            full_df = full_df.sort_values(by=["stock_id", "date"], ascending=[True, True])

            grouped = full_df.groupby("stock_id")

            for stock_id, df in grouped:
                if len(df) < 60:
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

                if all(
                    strat_res.get(key, False) for key in selected_strategies
                ):
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
                    results.append({
                        "股票代碼": stock_id,
                        "股票名稱": stock_name,
                        "收盤價": strat_res["收盤價"],
                        "今日漲跌(%)": strat_res["今日漲跌(%)"],
                        "成交量(張)": strat_res["成交量(張)"],
                        "符合策略數": passed_count,
                        "S1_突破平台": (
                            "✅" if strat_res["S1_突破平台"] else "❌"
                        ),
                        "S2_均線多頭": (
                            "✅" if strat_res["S2_均線多頭"] else "❌"
                        ),
                        "S3_MACD動能": (
                            "✅" if strat_res["S3_MACD動能"] else "❌"
                        ),
                        "S4_量價爆量": (
                            "✅" if strat_res["S4_量價爆量"] else "❌"
                        ),
                        "月線日均斜率(%)": strat_res["月線日均斜率(%)"],
                        "突破爆量倍數": strat_res["突破爆量倍數"],
                        "爆量攻擊倍數": strat_res["爆量攻擊倍數"],
                    })
    except Exception as e:
        print(f"分析失敗: {e}")

    engine.dispose()

    res_df = pd.DataFrame(results)
    if not res_df.empty:
        res_df = res_df.sort_values(
            by=["符合策略數", "成交量(張)"], ascending=[False, False]
        )

    return res_df
