import os
import sqlite3
import time
import analyze  # 多策略分析模組
import pandas as pd
import plot_chart  # 繪圖模組
import streamlit as st
import update_data

st.set_page_config(page_title="台股量化選股與 K 線分析系統", layout="wide")

st.title("📈 台股量化選股與互動 K 線控制台")

# ==================== 1. 側邊欄：操作與資料庫狀態監控 ====================
st.sidebar.header("🕹️ 操作控制台")

DB_PATH = "taiwan_stock_daily.db"


def get_db_status():
    """查詢 SQLite 資料庫狀態：總股票數與真正的最新交易日 (取多檔最大值)"""
    if not os.path.exists(DB_PATH):
        return None

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]

        if not tables:
            conn.close()
            return None

        stock_count = len(tables)

        latest_dates = []
        for table in tables[:15]:
            try:
                date_df = pd.read_sql_query(
                    f"SELECT date FROM {table} ORDER BY date DESC LIMIT 1", conn
                )
                if not date_df.empty:
                    latest_dates.append(date_df["date"].iloc[0])
            except Exception:
                continue

        conn.close()

        real_latest_date = max(latest_dates) if latest_dates else "未知"

        return {"stock_count": stock_count, "latest_date": real_latest_date}
    except Exception:
        return None


# 顯示資料庫狀態卡片
st.sidebar.subheader("💾 資料庫即時狀態")
db_info = get_db_status()

if db_info:
    st.sidebar.success(f"📅 **最新資料日期**：{db_info['latest_date']}")
    st.sidebar.info(f"📊 **已備份股票數**：{db_info['stock_count']} 檔")
else:
    st.sidebar.warning("⚠️ **目前無資料**：請點擊下方按鈕更新資料庫。")

# 手動更新與即時進度呈現
if st.sidebar.button("📥 下載/更新最新收盤數據"):
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()

    def update_ui_progress(current, total, message):
        pct = min(1.0, max(0.0, current / total)) if total > 0 else 0
        progress_bar.progress(pct)
        status_text.info(message)

    try:
        update_data.update_database(progress_callback=update_ui_progress)
        st.sidebar.success("✅ 資料庫更新完成！")
        time.sleep(1)
        st.rerun()
    except Exception as e:
        st.sidebar.error(f"❌ 更新失敗: {e}")

st.sidebar.divider()

# ==================== 2. 策略選擇與倍數設定區 (Form 防爆機制) ====================
with st.sidebar.form("strategy_form"):
    st.subheader("🎯 策略與倍數參數設定")

    strategy_map = {
        "💥 策略1: 突破平台整理 (Breakout)": "S1_突破平台",
        "📈 策略2: 均線多頭排列 (Trend)": "S2_均線多頭",
        "⚡ 策略3: MACD 動能轉強 (Momentum)": "S3_MACD動能",
        "🔥 策略4: 爆量攻擊換手 (Volume)": "S4_量價爆量",
    }

    selected_options = st.multiselect(
        "選擇要同時滿足的策略：",
        options=list(strategy_map.keys()),
        default=[list(strategy_map.keys())[0]],
    )
    selected_keys = [strategy_map[opt] for opt in selected_options]

    st.markdown("---")
    st.markdown("⚙️ **爆量倍數精細微調**")

    breakout_vol_ratio = st.slider(
        "💥 策略1-突破平台 (對比 5日均量)：",
        min_value=1.0,
        max_value=5.0,
        value=1.8,
        step=0.1,
    )

    attack_vol_ratio = st.slider(
        "🔥 策略4-爆量攻擊 (對比 20日均量)：",
        min_value=1.2,
        max_value=5.0,
        value=2.0,
        step=0.1,
    )

    submitted = st.form_submit_button("🚀 套用設定並執行分析")

# ==================== 3. 主畫面執行與數據呈現 ====================
if submitted or st.session_state.get("run_analysis", False):
    st.session_state["run_analysis"] = True

    if not os.path.exists(DB_PATH):
        st.error("找不到資料庫，請先從左側執行『下載/更新最新收盤數據』！")
    elif not selected_keys:
        st.warning("請至少勾選一種選股策略！")
    else:
        with st.spinner("正在進行全台股多重策略比對中..."):
            result_df = analyze.run_cross_analysis(
                selected_keys,
                breakout_vol_ratio=breakout_vol_ratio,
                attack_vol_ratio=attack_vol_ratio,
            )
            st.session_state["result_df"] = result_df

# 展示分析結果與 K 線圖
if "result_df" in st.session_state and not st.session_state["result_df"].empty:
    result_df = st.session_state["result_df"]

    st.success(
        f"🎯 分析完成！共找到 {len(result_df)} 档同時符合條件的標的："
    )

    display_cols = [
        "股票代碼",
        "股票名稱",
        "收盤價",
        "今日漲跌(%)",
        "成交量(張)",
        "符合策略數",
        "S1_突破平台",
        "S2_均線多頭",
        "S3_MACD動能",
        "S4_量價爆量",
        "突破爆量倍數",
        "爆量攻擊倍數",
        "月線日均斜率(%)",
    ]

    st.dataframe(
        result_df[display_cols], use_container_width=True, hide_index=True
    )

    st.divider()

    st.subheader("📊 個股互動式 K 線與 KD 圖檢視")

    stock_options = [
        f"{row['股票代碼']} {row['股票名稱']} (漲幅: {row['今日漲跌(%)']}%)"
        for _, row in result_df.iterrows()
    ]

    selected_stock_str = st.selectbox("選擇要檢視的股票：", stock_options)

    if selected_stock_str:
        target_id = selected_stock_str.split(" ")[0]
        target_name = selected_stock_str.split(" ")[1]

        conn = sqlite3.connect(DB_PATH)
        stock_kdf = pd.read_sql_query(
            f"SELECT * FROM stock_{target_id}", conn
        )
        conn.close()

        if not stock_kdf.empty:
            stock_kdf["MA5"] = stock_kdf["close"].rolling(5).mean()
            stock_kdf["MA20"] = stock_kdf["close"].rolling(20).mean()
            stock_kdf["MA60"] = stock_kdf["close"].rolling(60).mean()

            low_min9 = stock_kdf["min"].rolling(9).min()
            high_max9 = stock_kdf["max"].rolling(9).max()
            rsv = (
                (stock_kdf["close"] - low_min9) / (high_max9 - low_min9) * 100
            ).fillna(50)

            k_list, d_list = [50.0], [50.0]
            for r in rsv:
                k = (2 / 3) * k_list[-1] + (1 / 3) * r
                d = (2 / 3) * d_list[-1] + (1 / 3) * k
                k_list.append(k)
                d_list.append(d)

            stock_kdf["K"] = k_list[1:]
            stock_kdf["D"] = d_list[1:]

            kdf_show = stock_kdf.tail(80)

            fig = plot_chart.draw_candlestick(
                kdf_show, target_id, target_name
            )
            st.plotly_chart(fig, use_container_width=True)

elif "result_df" in st.session_state and st.session_state["result_df"].empty:
    st.info("今日無同時符合上述『多重共振交集條件』的股票。")