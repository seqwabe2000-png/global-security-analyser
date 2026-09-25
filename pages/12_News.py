import streamlit as st

from src import data, sens_news
from src import universe as uni
from src.common import bootstrap

bootstrap("News", "📰")

st.title("📰 Announcements & News")
st.caption(
    "SENS regulatory announcements exist only for JSE-listed shares (scraped from Sharenet's public "
    "SENS page -- no free official JSE SENS API exists), so that tab only appears for South African "
    "equities. Every instrument -- any market, any asset class -- gets a general news feed via Google "
    "News. If a section below comes up empty, run `python3 scripts/test_sens_connection.py` to check "
    "whether the source is reachable/still working."
)

universe = uni.picker("news", default_asset_classes=["Equity"], default_markets=["South Africa"], show_sector_filter=False)


def _matches(pool, query):
    q = query.strip().lower()
    if not q:
        return pool
    return pool[
        pool["symbol"].str.lower().str.contains(q, regex=False)
        | pool["name"].str.lower().str.contains(q, regex=False)
    ]


c1, c2, c3, c4 = st.columns([1.5, 1.3, 2, 1])
with c1:
    search_query = st.text_input(
        "🔍 Search (name or ticker)", placeholder="e.g. Naspers or NPN", key="sens_search"
    )
with c2:
    sector_filter = st.selectbox(uni.sector_label(universe["asset_class"].unique().tolist()), ["All"] + sorted(universe["gics_sector"].unique()))
    stock_universe = universe if sector_filter == "All" else universe[universe["gics_sector"] == sector_filter]

filtered = _matches(stock_universe, search_query)
if search_query and filtered.empty:
    broader = _matches(universe, search_query)
    if not broader.empty:
        st.caption(f"No matches for \"{search_query}\" in {sector_filter} -- showing matches across the current selection instead.")
        filtered = broader

with c3:
    label_to_row = {f"{r['symbol']} — {r['name']}": r for _, r in filtered.iterrows()}
    if not label_to_row:
        st.warning(f"No instruments match \"{search_query}\"." if search_query else "No instruments in this selection.")
        st.stop()
    choice = st.selectbox("Instrument", options=sorted(label_to_row.keys()))
    row = label_to_row[choice]
with c4:
    days = st.slider("Lookback (days)", 7, 180, 60, step=7)

is_jse_equity = (row["asset_class"] == "Equity") and (row["market"] == "South Africa")
news_query_context = {
    "Equity": f'{row["market"]}',
    "Crypto": "cryptocurrency",
    "Commodity": "commodity market",
    "Currency": "forex currency market",
    "Bond/Rate": "bond market rates",
    "Mutual Fund": "mutual fund",
}.get(row["asset_class"], "")


@st.cache_data(ttl=900, show_spinner=False)
def _cached_sens(symbol, days):
    return sens_news.fetch_sens(symbol, days=days)


@st.cache_data(ttl=900, show_spinner=False)
def _cached_news(query, days):
    return sens_news.fetch_news(query, days=days)


tab_labels = ["📰 News", f"🏷️ {row['gics_sector']} News"]
if is_jse_equity:
    tab_labels.insert(0, "📢 SENS Announcements")
tabs = st.tabs(tab_labels)
if is_jse_equity:
    tab_sens, tab_company_news, tab_sector_news = tabs
else:
    tab_sens = None
    tab_company_news, tab_sector_news = tabs

if tab_sens is not None:
    with tab_sens:
        with st.spinner("Fetching SENS announcements..."):
            sens_df = _cached_sens(row["symbol"], days)
        if sens_df.empty:
            st.info(f"No SENS announcements found for {row['symbol']} in the last {days} days (or the source is unreachable).")
        else:
            st.caption(f"{len(sens_df)} announcement(s) in the last {days} days. Click a row's link to open the full announcement.")
            display = sens_df.copy()
            display["Date"] = display["datetime"].dt.strftime("%Y-%m-%d %H:%M")
            display["Move %"] = display["pct_move"].map(lambda x: f"{x:+.2f}%" if x == x and x is not None else "—")
            display = display.rename(columns={"headline": "Headline", "code": "Code", "url": "Link"})
            display = display[["Date", "Code", "Headline", "Move %", "Link"]]
            st.dataframe(
                display,
                hide_index=True,
                width="stretch",
                height=min(700, 60 + 42 * len(display)),
                column_config={
                    "Date": st.column_config.TextColumn(width="small"),
                    "Code": st.column_config.TextColumn(width="small"),
                    "Headline": st.column_config.TextColumn(width="large"),
                    "Move %": st.column_config.TextColumn(width="small"),
                    "Link": st.column_config.LinkColumn(display_text="Open ↗", width="small"),
                },
            )
else:
    st.caption(
        "SENS announcements aren't shown for this instrument -- SENS only covers JSE-listed shares. "
        "Pick a South African equity above (Asset Class = Equity, Market = South Africa) to see that tab."
    )

with tab_company_news:
    with st.spinner("Fetching news..."):
        news_df = _cached_news(f'"{row["name"]}" {news_query_context}'.strip(), days)
    if news_df.empty:
        st.info(f"No recent news found for {row['name']} (or the source is unreachable).")
    else:
        st.caption(f"{len(news_df)} article(s) in the last {days} days.")
        display = news_df.copy()
        display["Date"] = display["published"].map(lambda d: d.strftime("%Y-%m-%d") if d is not None else "—")
        display = display.rename(columns={"title": "Headline", "source": "Source", "link": "Link"})
        display = display[["Date", "Headline", "Source", "Link"]]
        st.dataframe(
            display,
            hide_index=True,
            width="stretch",
            height=min(600, 60 + 42 * len(display)),
            column_config={
                "Date": st.column_config.TextColumn(width="small"),
                "Headline": st.column_config.TextColumn(width="large"),
                "Source": st.column_config.TextColumn(width="small"),
                "Link": st.column_config.LinkColumn(display_text="Open ↗", width="small"),
            },
        )

with tab_sector_news:
    with st.spinner("Fetching sector news..."):
        sector_news_df = _cached_news(f'"{row["gics_sector"]}" {row["market"]} {news_query_context}'.strip(), days)
    if sector_news_df.empty:
        st.info(f"No recent {row['gics_sector']} sector news found (or the source is unreachable).")
    else:
        st.caption(f"{len(sector_news_df)} article(s) in the last {days} days.")
        display = sector_news_df.copy()
        display["Date"] = display["published"].map(lambda d: d.strftime("%Y-%m-%d") if d is not None else "—")
        display = display.rename(columns={"title": "Headline", "source": "Source", "link": "Link"})
        display = display[["Date", "Headline", "Source", "Link"]]
        st.dataframe(
            display,
            hide_index=True,
            width="stretch",
            height=min(600, 60 + 42 * len(display)),
            column_config={
                "Date": st.column_config.TextColumn(width="small"),
                "Headline": st.column_config.TextColumn(width="large"),
                "Source": st.column_config.TextColumn(width="small"),
                "Link": st.column_config.LinkColumn(display_text="Open ↗", width="small"),
            },
        )
