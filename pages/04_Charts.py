from dateutil.relativedelta import relativedelta
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from src import data, indicators
from src import universe as uni
from src.common import bootstrap
from src.theme import ACCENT, ACCENT_2, DOWN, MUTED, UP
from src.ui import range_bar_html

bootstrap("Charts", "📈")

st.title("📈 Price Chart")
st.caption("Candlestick charts with SMAs/Bollinger/RSI/MACD -- works for any instrument in the universe: equities, crypto, commodities, currencies, or bonds/rates.")

universe = uni.picker("charts", default_asset_classes=["Equity"], default_markets=["South Africa"])

# --------------------------------------------------------------------------
# Instrument picker
# --------------------------------------------------------------------------
c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    label_to_row = {f"{r['symbol']} — {r['name']}": r for _, r in universe.iterrows()}
    if not label_to_row:
        st.warning("No instruments match the current Asset Class / Market selection.")
        st.stop()
    choice = st.selectbox("Instrument", options=sorted(label_to_row.keys()))
    picked_row = label_to_row[choice]
    ticker = picked_row["yf_ticker"]
with c2:
    period = st.selectbox("Period", ["6mo", "1y", "2y", "5y", "10y", "max"], index=2)
with c3:
    interval = st.selectbox("Interval", ["1d", "1wk", "1mo"], index=0)

sma_windows = st.multiselect("Simple Moving Averages", [20, 50, 100, 200], default=[20, 50, 100, 200])

c4, c5, c6, c7 = st.columns(4)
with c4:
    show_bollinger = st.checkbox("Bollinger Bands (20, 2σ)")
with c5:
    show_rsi = st.checkbox("RSI (14)")
with c6:
    show_macd = st.checkbox("MACD (12, 26, 9)")
with c7:
    show_volume = st.checkbox("Volume", value=True)

c8, c9 = st.columns(2)
with c8:
    show_sr = st.checkbox("Support / Resistance")
with c9:
    show_trendlines = st.checkbox("Trend lines")

df = data.get_history(ticker, period=period, interval=interval)

if df.empty:
    st.error(
        f"No price data available for {ticker}. This can happen for illiquid/micro-cap or thinly-covered "
        "instruments, or if Yahoo Finance couldn't be reached."
    )
    st.stop()

df = indicators.add_all_smas(df, "Close", windows=tuple(sma_windows) if sma_windows else ())
if show_bollinger:
    df["BB_upper"], df["BB_mid"], df["BB_lower"] = indicators.bollinger_bands(df["Close"])
if show_rsi:
    df["RSI"] = indicators.rsi(df["Close"])
if show_macd:
    df["MACD"], df["MACD_signal"], df["MACD_hist"] = indicators.macd(df["Close"])

resistance_zones, support_zones, trend_high, trend_low = [], [], None, None
if show_sr or show_trendlines:
    swing_highs, swing_lows = indicators.find_swing_points(df, order=5)
    if show_sr:
        resistance_zones, support_zones = indicators.support_resistance_zones(swing_highs, swing_lows)
    if show_trendlines:
        trend_high = indicators.fit_trend_line(swing_highs)
        trend_low = indicators.fit_trend_line(swing_lows)

last, pct = data.last_price_change(df)

# 52-week window by actual date (not a fixed bar count), so this stays
# correct regardless of whether the chart interval above is daily, weekly,
# or monthly -- and uses the bar's High/Low (not just Close), which is the
# usual definition of a "52-week high/low" on most quote screens.
cutoff_52w = df.index.max() - relativedelta(years=1)
window_52w = df[df.index >= cutoff_52w]
high_52w = window_52w["High"].max() if not window_52w.empty else float("nan")
low_52w = window_52w["Low"].min() if not window_52w.empty else float("nan")

price_unit = picked_row.get("currency", "")
m1, m2, m3, m4 = st.columns(4)
m1.metric(f"Last Close ({price_unit})", f"{last:,.2f}" if last is not None else "—", f"{pct:+.2f}%" if pct is not None else None)
m2.metric("52w High", f"{high_52w:,.0f}" if high_52w == high_52w else "—")
m3.metric("52w Low", f"{low_52w:,.0f}" if low_52w == low_52w else "—")
above200 = indicators.pct_above_sma(df, 200)
m4.metric("Above 200-SMA", "Yes" if above200 else ("No" if above200 is False else "—"))

# --------------------------------------------------------------------------
# Day's/period range + 52-week range bars -- a quick visual read of where
# the current price sits within its recent range, like the range bars on
# most broker/quote apps.
# --------------------------------------------------------------------------
range_period_label = {"1d": "Day's", "1wk": "Week's", "1mo": "Month's"}.get(interval, "Period")
last_high = df["High"].iloc[-1] if not df.empty else None
last_low = df["Low"].iloc[-1] if not df.empty else None

rc1, rc2 = st.columns(2)
with rc1:
    st.markdown(
        range_bar_html(last_low, last_high, last, f"{range_period_label} Range", decimals=0),
        unsafe_allow_html=True,
    )
with rc2:
    st.markdown(
        range_bar_html(low_52w, high_52w, last, "52-Week Range", decimals=0),
        unsafe_allow_html=True,
    )

st.download_button(
    "⬇️ Download OHLCV (CSV)",
    data=df[["Open", "High", "Low", "Close", "Volume"]].to_csv().encode("utf-8"),
    file_name=f"{choice.split(' — ')[0]}_{period}_{interval}.csv",
    mime="text/csv",
)

# --------------------------------------------------------------------------
# Period returns (1D / WTD / MTD / QTD / YTD / 1Y / 3Y / 5Y / 10Y / MAX)
# Pulled from as much daily history as Yahoo will give us, independent of
# whatever period/interval is selected for the chart above.
# --------------------------------------------------------------------------
st.markdown("**Period returns**")
max_hist = data.get_history(ticker, period="max", interval="1d")
preturns = indicators.period_returns(max_hist["Close"]) if not max_hist.empty else {}
if preturns:
    pills = []
    for label in indicators.PERIOD_RETURN_LABELS:
        if label in preturns:
            val = preturns[label]
            cls = "jse-up" if val >= 0 else "jse-down"
            pills.append(f"<span class='jse-pill'>{label}&nbsp;<span class='{cls}'>{val:+.1f}%</span></span>")
    st.markdown("".join(pills), unsafe_allow_html=True)
else:
    st.caption("Not enough history to compute period returns yet.")

st.divider()

# --------------------------------------------------------------------------
# Build subplot rows: price (+volume as overlay row), RSI, MACD
# --------------------------------------------------------------------------
extra_rows = int(show_rsi) + int(show_macd)
row_heights = [0.65] + [0.15] if show_volume else [0.8]
specs_rows = 1 + int(show_volume) + extra_rows
heights = []
if show_volume:
    heights = [0.55, 0.15]
else:
    heights = [0.7]
heights += [0.15] * extra_rows
# normalise
total = sum(heights)
heights = [h / total for h in heights]

titles = ["Price"]
if show_volume:
    titles.append("Volume")
if show_rsi:
    titles.append("RSI (14)")
if show_macd:
    titles.append("MACD")

fig = make_subplots(
    rows=len(heights),
    cols=1,
    shared_xaxes=True,
    vertical_spacing=0.03,
    row_heights=heights,
    subplot_titles=titles,
)

fig.add_trace(
    go.Candlestick(
        x=df.index,
        open=df["Open"],
        high=df["High"],
        low=df["Low"],
        close=df["Close"],
        name=choice.split(" — ")[0],
        increasing_line_color=UP,
        decreasing_line_color=DOWN,
    ),
    row=1,
    col=1,
)

sma_colors = {20: "#FFB020", 50: ACCENT_2, 100: "#B36AE2", 200: ACCENT}
for w in sma_windows:
    col = f"SMA{w}"
    if col in df:
        fig.add_trace(
            go.Scatter(x=df.index, y=df[col], name=col, line=dict(width=1.3, color=sma_colors.get(w))),
            row=1,
            col=1,
        )

if show_bollinger:
    fig.add_trace(go.Scatter(x=df.index, y=df["BB_upper"], name="BB Upper", line=dict(width=1, color=MUTED, dash="dot")), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["BB_lower"], name="BB Lower", line=dict(width=1, color=MUTED, dash="dot"), fill="tonexty", fillcolor="rgba(139,147,167,0.07)"), row=1, col=1)

for zone in resistance_zones:
    fig.add_hline(
        y=zone["level"], row=1, col=1, line_dash="solid", line_color=DOWN,
        opacity=min(0.85, 0.35 + 0.15 * zone["touches"]),
        annotation_text=f"R ({zone['touches']}x)", annotation_position="right", annotation_font_size=10,
    )
for zone in support_zones:
    fig.add_hline(
        y=zone["level"], row=1, col=1, line_dash="solid", line_color=UP,
        opacity=min(0.85, 0.35 + 0.15 * zone["touches"]),
        annotation_text=f"S ({zone['touches']}x)", annotation_position="right", annotation_font_size=10,
    )

last_date = df.index.max()
for trend, label, color in ((trend_high, "Downtrend line", DOWN), (trend_low, "Uptrend line", UP)):
    if trend is None:
        continue
    x0, x1 = trend["start_date"], last_date
    y0 = trend["slope"] * trend["x0_ordinal"] + trend["intercept"]
    y1 = trend["slope"] * x1.toordinal() + trend["intercept"]
    fig.add_trace(
        go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines", name=label,
                   line=dict(color=color, width=1.5, dash="dash")),
        row=1, col=1,
    )

current_row = 1
if show_volume:
    current_row += 1
    colors = [UP if c >= o else DOWN for o, c in zip(df["Open"], df["Close"])]
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="Volume", marker_color=colors, opacity=0.6), row=current_row, col=1)

if show_rsi:
    current_row += 1
    fig.add_trace(go.Scatter(x=df.index, y=df["RSI"], name="RSI", line=dict(color=ACCENT_2, width=1.3)), row=current_row, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color=DOWN, row=current_row, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color=UP, row=current_row, col=1)

if show_macd:
    current_row += 1
    fig.add_trace(go.Scatter(x=df.index, y=df["MACD"], name="MACD", line=dict(color=ACCENT_2, width=1.3)), row=current_row, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MACD_signal"], name="Signal", line=dict(color="#FFB020", width=1.3)), row=current_row, col=1)
    hist_colors = [UP if v >= 0 else DOWN for v in df["MACD_hist"].fillna(0)]
    fig.add_trace(go.Bar(x=df.index, y=df["MACD_hist"], name="Histogram", marker_color=hist_colors, opacity=0.5), row=current_row, col=1)

fig.update_layout(
    height=700 + 150 * extra_rows,
    xaxis_rangeslider_visible=False,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    hovermode="x unified",
)

st.plotly_chart(fig, width="stretch")
