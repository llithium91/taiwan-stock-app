import sqlite3
import numpy as np
import pandas as pd


def compute_indicators(df):
    """計算技術指標：MA, MACD"""
    df = df.copy()

    df["MA5"] = df["close"].rolling(5).mean()
    df["MA20"] = df["close"].rolling(20).mean()
    df["MA60"] = df["close"].rolling(60).mean()

    exp12 = df["close"].ewm(span=12, adjust=False).mean()
    exp26 = df["close"].ewm(span=26, adjust=False).mean()
    df["DIF"] = exp12 - exp26
    df["MACD"] = df["DIF"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"] = df["DIF"] - df["MACD"]

    return df


def check_stock_strategies(
    df, breakout_vol_ratio=1.8, attack_vol_ratio=2.0
):
    """對單一股票 DataFrame 檢查 4 大策略"""
    if len(df) < 60:
        return {}

    df = compute_indicators(df)

    latest = df.iloc[-1]
    prev = df.iloc[-2]
    history_20 = df.iloc[-21:-1]

    # ---------- 策略 1: 💥 突破平台整理 ----------
    high_20 = history_20["max"].max()
    low_20 = history_20["min"].min()
    platform_amp = (high_20 - low_20) / low_20 if low_20 > 0 else 1

    vol_ma5 = history_20["Trading_Volume"].tail(5).mean()
    vol_ratio_breakout = (
        latest["Trading_Volume"] / vol_ma5 if vol_ma5 > 0 else 0
    )

    prev_close = prev["close"]
    today_pct = (
        (latest["close"] - prev_close) / prev_close
        if prev_close > 0
        else 0
    )

    cond_s1 = (
        (latest["close"] > high_20)
        and (today_pct >= 0.02)
        and (vol_ratio_breakout >= breakout_vol_ratio)
        and (platform_amp <= 0.18)
    )

    # ---------- 策略 2: 📈 均線多頭排列 ----------
    ma20_prev5 = history_20.iloc[-5]["MA20"]
    ma20_slope = (
        ((latest["MA20"] - ma20_prev5) / ma20_prev5 * 100) / 5
        if ma20_prev5 > 0
        else 0
    )

    cond_s2 = (
        (latest["close"] > latest["MA5"])
        and (latest["MA5"] > latest["MA20"])
        and (latest["MA20"] > latest["MA60"])
        and (ma20_slope > 0.1)
    )

    # ---------- 策略 3: ⚡ MACD 動能轉強 ----------
    macd_cross_up = (prev["DIF"] <= prev["MACD"]) and (
        latest["DIF"] > latest["MACD"]
    )
    macd_hist_turn_red = (prev["MACD_Hist"] < 0) and (
        latest["MACD_Hist"] > 0
    )
    cond_s3 = macd_cross_up or macd_hist_turn_red

    # ---------- 策略 4: 🔥 爆量攻擊換手 ----------
    vol_ma20 = history_20["Trading_Volume"].mean()
    vol_ratio_attack = (
        latest["Trading_Volume"] / vol_ma20 if vol_ma20 > 0 else 0
    )

    cond_s4 = (
        (vol_ratio_attack >= attack_vol_ratio)
        and (today_pct > 0.015)
        and (latest["close"] >= latest["open"])
    )

    return {
        "S1_突破平台": cond_s1,
        "S2_均線多頭": cond_s2,
        "S3_MACD動能": cond_s3,
        "S4_量價爆量": cond_s4,
        "收盤價": round(latest["close"], 2),
        "今日漲跌(%)": round(today_pct * 100, 2),
        "成交量(張)": int(latest["Trading_Volume"] / 1000),
        "月線日均斜率(%)": round(ma20_slope, 2),
        "突破爆量倍數": round(vol_ratio_breakout, 2),
        "爆量攻擊倍數": round(vol_ratio_attack, 2),
    }
    