import plotly.graph_objects as go
from plotly.subplots import make_subplots


def draw_candlestick(df, stock_id, stock_name):
    """繪製台股互動式 K 線圖 (包含主圖 K 線+均線、副圖成交量、副圖 KD 指標)"""
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        subplot_titles=(f"{stock_id} {stock_name} 日 K 線圖", "成交量", "KD 指標"),
        row_heights=[0.55, 0.2, 0.25],
    )

    # 1. 主圖：K 線
    fig.add_trace(
        go.Candlestick(
            x=df["date"],
            open=df["open"],
            high=df["max"],
            low=df["min"],
            close=df["close"],
            name="K線",
            increasing_line_color="red",  # 台股紅漲
            decreasing_line_color="green",  # 台股綠跌
        ),
        row=1,
        col=1,
    )

    # 均線
    if "MA5" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["MA5"],
                line=dict(color="orange", width=1),
                name="5MA",
            ),
            row=1,
            col=1,
        )
    if "MA20" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["MA20"],
                line=dict(color="blue", width=1.5),
                name="20MA",
            ),
            row=1,
            col=1,
        )
    if "MA60" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["MA60"],
                line=dict(color="purple", width=1.5),
                name="60MA",
            ),
            row=1,
            col=1,
        )

    # 2. 副圖：成交量 (張)
    vol_colors = [
        "red" if c >= o else "green"
        for c, o in zip(df["close"], df["open"])
    ]
    fig.add_trace(
        go.Bar(
            x=df["date"],
            y=df["Trading_Volume"] / 1000,
            marker_color=vol_colors,
            name="成交量(張)",
        ),
        row=2,
        col=1,
    )

    # 3. 副圖：KD 指標
    if "K" in df.columns and "D" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["K"],
                line=dict(color="red", width=1.5),
                name="K值",
            ),
            row=3,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["D"],
                line=dict(color="blue", width=1.5),
                name="D值",
            ),
            row=3,
            col=1,
        )

    fig.update_layout(
        xaxis_rangeslider_visible=False,
        height=750,
        margin=dict(l=20, r=20, t=40, b=20),
    )

    return fig