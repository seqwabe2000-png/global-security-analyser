import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import data, indicators, sens_news
from src import universe as uni
from src.common import bootstrap
from src.theme import ACCENT, ACCENT_2, DOWN, MUTED

bootstrap("Event Study", "🗓️")

st.title("🗓️ Announcement Event Study")
st.markdown(
    "<div class='jse-card'>"
    "<b>What this tool does:</b> pick a stock below and it automatically pulls that stock's past SENS "
    "announcements, works out how much the price actually moved on each announcement day, and ranks "
    "them so you can see which news mattered most. Then you can click any one announcement to see the "
    "price path before and after it, or look at the average pattern across all the big ones. "
    "<b>JSE-only:</b> this page is built on SENS announcement history, which only exists for JSE-listed "
    "shares -- for any other market/asset class, use the <b>News</b> page instead.</div>",
    unsafe_allow_html=True,
)
st.write("")

instruments = uni.load_instruments()
universe = instruments[(instruments["asset_class"] == "Equity") & (instruments["market"] == "South Africa")]

# --------------------------------------------------------------------------
# Step 1 -- pick a stock (the only thing you *need* to do)
# --------------------------------------------------------------------------
st.subheader("① Choose a stock")
c1, c2 = st.columns([1.3, 2])
with c1:
    sector_filter = st.selectbox("Sector filter (optional)", ["All sectors"] + sorted(universe["gics_sector"].unique()))
    stock_universe = universe if sector_filter == "All sectors" else universe[universe["gics_sector"] == sector_filter]
with c2:
    label_to_row = {f"{r['symbol']} — {r['name']}": r for _, r in stock_universe.iterrows()}
    if not label_to_row:
        st.warning("No stocks in this sector.")
        st.stop()
    choice = st.selectbox("Stock", options=sorted(label_to_row.keys()))
    row = label_to_row[choice]

with st.expander("⚙️ Advanced settings (optional — the defaults work well for most stocks)"):
    st.caption(
        "Only change these if the results below feel too noisy (too many small announcements) or too "
        "sparse (too few announcements)."
    )
    ac1, ac2, ac3 = st.columns(3)
    with ac1:
        lookback_days = st.slider(
            "How far back to look (days)", 90, 730, 365, step=30,
            help="How many days of past SENS announcements to pull in.",
        )
    with ac2:
        window = st.slider(
            "Price path length (± trading days)", 3, 20, 10,
            help="How many trading days before/after each announcement to show in the price-path charts.",
        )
    with ac3:
        min_move = st.slider(
            "\"Major\" move threshold (%)", 0.5, 10.0, 2.0, step=0.5,
            help="Announcements where the stock moved less than this on the reaction day are treated as minor and hidden from the ranked list.",
        )

st.divider()


@st.cache_data(ttl=900, show_spinner=False)
def _cached_sens(symbol, days):
    return sens_news.fetch_sens(symbol, days=days)


with st.spinner(f"Fetching {row['symbol']}'s SENS announcements and price history..."):
    sens_df = _cached_sens(row["symbol"], lookback_days)
    price_period = {90: "1y", 365: "2y"}.get(lookback_days, "5y" if lookback_days > 365 else "2y")
    if lookback_days > 700:
        price_period = "5y"
    price_df = data.get_history(row["yf_ticker"], period=price_period, interval="1d")

if price_df.empty:
    st.error(f"No price data available for {row['symbol']}.")
    st.stop()

if sens_df.empty:
    st.info(
        f"No SENS announcements found for {row['symbol']} in the last {lookback_days} days. Try picking "
        "a different stock, or open **Advanced settings** above and increase \"How far back to look\". "
        "If this keeps happening for every stock, the SENS source may be unreachable -- run "
        "`python3 scripts/test_sens_connection.py` to check."
    )
    st.stop()

# --------------------------------------------------------------------------
# Compute each announcement's reaction-day return directly from OUR price
# data (rather than trusting the scraped % move, which may use a different
# reference price) and rank by |return|.
# --------------------------------------------------------------------------
events = []
for _, r in sens_df.iterrows():
    path = indicators.event_window(price_df, r["datetime"], window=window)
    if path is None or 0 not in path.index:
        continue
    day0_return = path.loc[0]
    events.append(
        {
            "datetime": r["datetime"],
            "headline": r["headline"],
            "url": r["url"],
            "day0_return": day0_return,
            "path": path,
        }
    )

if not events:
    st.warning("None of the SENS announcements in this window line up with available price history.")
    st.stop()

events_df = pd.DataFrame(events).sort_values("day0_return", key=lambda s: s.abs(), ascending=False)
major = events_df[events_df["day0_return"].abs() >= min_move]

st.subheader("② Which announcements moved the price the most")
st.caption(
    f"{len(major)} of {row['symbol']}'s {len(events_df)} announcements in the last {lookback_days} days "
    f"moved the price by at least {min_move:.1f}% on the day. Ranked biggest move first."
)

if major.empty:
    st.info(
        "No announcements clear the current threshold. Open **Advanced settings** above and lower the "
        "\"Major move\" threshold to see more."
    )
    st.stop()

display = major[["datetime", "headline", "day0_return"]].copy()
display["datetime"] = display["datetime"].dt.strftime("%Y-%m-%d %H:%M")
display["day0_return"] = display["day0_return"].map(lambda x: f"{x:+.2f}%")
display = display.rename(columns={"datetime": "Date", "headline": "Headline", "day0_return": "Reaction-day move"})
st.dataframe(display, hide_index=True, width="stretch", height=min(400, 40 + 35 * len(display)))

st.divider()
st.subheader("③ Zoom into one announcement")
st.caption("Pick any announcement from the ranked list to see exactly how the price moved before and after it.")

options = [f"{r['datetime'].strftime('%Y-%m-%d')} ({r['day0_return']:+.2f}%) — {r['headline'][:60]}" for _, r in major.iterrows()]
picked = st.selectbox("Announcement", options)
picked_row = major.iloc[options.index(picked)]

fig = go.Figure()
fig.add_trace(
    go.Scatter(
        x=list(picked_row["path"].index),
        y=picked_row["path"].values,
        mode="lines+markers",
        line=dict(color=ACCENT if picked_row["day0_return"] >= 0 else DOWN, width=2),
        name=row["symbol"],
    )
)
fig.add_vline(x=0, line_dash="dot", line_color=MUTED, annotation_text="Announcement day")
fig.add_hline(y=0, line_dash="dot", line_color=MUTED)
fig.update_layout(
    height=420,
    xaxis_title="Trading days relative to announcement (0 = announcement day)",
    yaxis_title="Cumulative return vs. day before (%)",
)
st.plotly_chart(fig, width="stretch")
if picked_row["url"]:
    st.caption(f"[Read the full announcement]({picked_row['url']})")

st.divider()
st.subheader("④ The average pattern across all major announcements")
st.caption(
    f"Every one of the {len(major)} announcements above (the ones that cleared the threshold), each "
    "lined up so day 0 = its own announcement day, then averaged. The shaded band is ±1 standard "
    "deviation -- how much individual announcements varied around that average. This is the classic "
    "event-study view: does this stock tend to keep drifting after a big announcement, or reverse?"
)

aligned = pd.DataFrame({i: r["path"] for i, r in major.reset_index(drop=True).iterrows()})
avg_path = aligned.mean(axis=1)
std_path = aligned.std(axis=1)

fig2 = go.Figure()
fig2.add_trace(
    go.Scatter(
        x=list(avg_path.index) + list(avg_path.index)[::-1],
        y=list((avg_path + std_path).values) + list((avg_path - std_path).values)[::-1],
        fill="toself",
        fillcolor="rgba(61,139,255,0.12)",
        line=dict(width=0),
        showlegend=False,
        hoverinfo="skip",
    )
)
fig2.add_trace(go.Scatter(x=list(avg_path.index), y=avg_path.values, mode="lines+markers", line=dict(color=ACCENT_2, width=2.5), name="Average path"))
fig2.add_vline(x=0, line_dash="dot", line_color=MUTED, annotation_text="Announcement day")
fig2.add_hline(y=0, line_dash="dot", line_color=MUTED)
fig2.update_layout(
    height=420,
    xaxis_title="Trading days relative to announcement (0 = announcement day)",
    yaxis_title="Avg cumulative return vs. day before (%)  ±1σ band",
)
st.plotly_chart(fig2, width="stretch")
