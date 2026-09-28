import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import indicators
from src import portfolio as pf
from src import portfolio_ui as pui
from src import universe as uni
from src.common import bootstrap

bootstrap("Watchlist", "👀")
cfg = pui.settings_sidebar()
instruments = uni.load_instruments()

st.title("👀 Watchlist — candidates vs. your live portfolio")
st.caption("Kept separate from the live portfolio. For each candidate: its own risk, how it correlates with what you "
           "already own, and what adding a position would do to portfolio volatility, VaR and beta.")

c1, c2, c3 = st.columns([1.2, 1.2, 1])
with c1:
    wl_name, wl = pui.pick("watchlist", "Watchlist", "pf_wl_pick")
with c2:
    live_name, live = pui.pick("live", "Compare against live portfolio", "pf_wl_live")
add_w = c3.slider("Hypothetical position size", 1, 25, 5, format="%d%%", key="wl_addw") / 100

with st.expander("➕ Quick-add to a watchlist"):
    lab = {f"{r.symbol} — {r.name} ({r.market})": r.yf_ticker for r in instruments.itertuples()}
    q1, q2, q3 = st.columns([2, 1.4, 1])
    sel = q1.multiselect("Search", sorted(lab), key="wl_q")
    typed = q2.text_input("or tickers", key="wl_typed", placeholder="MP, ONDS, WDC")
    target = q3.text_input("Watchlist name", value=wl_name or "Ideas", key="wl_target")
    if st.button("Add to watchlist"):
        new = [lab[s] for s in sel] + [t.strip().upper() for t in typed.split(",") if t.strip()]
        base = pui.get_holdings("watchlist", target) if target in pui.available("watchlist") else pd.DataFrame(columns=pf.HOLDING_COLUMNS)
        rows = pd.DataFrame({"ticker": new, "name": [pf.lookup_name(t, instruments) for t in new], "account": "", "category": "",
                             "value": np.nan, "weight": np.nan})
        merged = pd.concat([base, rows], ignore_index=True).drop_duplicates("ticker")
        pf.save_portfolio("watchlist", target, merged, "")
        pui.working()["watchlist"].pop(target, None)
        st.success(f"Saved {len(new)} name(s) to **{target}**.")
        st.rerun()

if wl is None or wl.empty:
    st.stop()

cand = [t for t in wl["ticker"].unique() if t]
live_t = live[live["ticker"] != ""]["ticker"].tolist() if live is not None else []
md = pui.market_data(cand + live_t, cfg)
pui.data_quality_box(md)
names = {r.ticker: (r.name or r.ticker)[:30] for r in wl.itertuples()}

base_w = pf.aggregate_by_ticker(live[live["ticker"] != ""]) if live is not None else None
base_s = pf.portfolio_summary(md, base_w, cfg["conf"], cfg["h"], mc_sims=2000) if base_w is not None else None
port = base_s["series"] if base_s and "error" not in base_s else None

rows = []
for t in cand:
    if t not in md.returns:
        rows.append({"ticker": t, "name": names.get(t, t), "status": "no data"})
        continue
    r = md.returns[t].dropna()
    mu, sd = r.mean() * md.ppy, r.std() * np.sqrt(md.ppy)
    row = {"ticker": t, "name": names.get(t, t), "held?": "✅" if t in live_t else "",
           "ann. return": mu, "ann. vol": sd, "Sharpe": (mu - md.rf_annual) / sd if sd else np.nan,
           "max DD": pf.max_drawdown(r)}
    pl = md.prices_local[t].dropna()
    pr = indicators.period_returns(pl)
    for k in ("1D", "MTD", "YTD", "1Y"):
        row[k] = pr.get(k, np.nan) / 100 if k in pr else np.nan
    last_y = pl[pl.index > pl.index.max() - pd.DateOffset(years=1)]
    if len(last_y) > 5:
        row["52w range pos."] = (pl.iloc[-1] - last_y.min()) / (last_y.max() - last_y.min()) if last_y.max() > last_y.min() else np.nan
    for b in md.bench_returns.columns:
        row[f"β {b}"] = pf.beta_to(r, md.bench_returns[b])[0]
    if port is not None:
        row["corr to portfolio"] = pf.beta_to(r, port)[1]
        mi = pf.marginal_impact(md, base_w[base_w.index.isin(md.returns.columns)], t, add_w, cfg["conf"], cfg["h"])
        row[f"Δ vol (+{add_w:.0%})"] = mi["Δ vol"]
        row[f"Δ VaR (+{add_w:.0%})"] = mi["Δ VaR"]
        row[f"Δ Sharpe (+{add_w:.0%})"] = mi["Δ Sharpe"]
        for b in md.bench_returns.columns:
            row[f"Δ β {b}"] = mi.get(f"Δ beta {b}")
    rows.append(row)

tbl = pd.DataFrame(rows).set_index("ticker")
front = ["name", "held?"] + [c for c in tbl.columns if c.startswith("Δ") or c == "corr to portfolio"]
tbl = tbl[[c for c in front if c in tbl.columns] + [c for c in tbl.columns if c not in front]]
pc = [c for c in tbl.columns if c in ("ann. return", "ann. vol", "max DD", "1D", "MTD", "YTD", "1Y", "52w range pos.")
      or c.startswith("Δ vol") or c.startswith("Δ VaR")]
tbld = pui.as_pct(tbl, pc)
st.dataframe(tbld.round(3), width="stretch", column_config=pui.pct_cols(tbld, pc), height=min(700, 38 * len(tbld) + 40))
if port is not None:
    st.caption(f"Δ columns: effect of adding {add_w:.0%} of the name to **{live_name}**, funded pro-rata from existing holdings. "
               "Negative Δ vol / Δ VaR = the name diversifies the portfolio.")

c1, c2 = st.columns(2)
with c1:
    ok = tbl.dropna(subset=["ann. vol"]) if "ann. vol" in tbl else pd.DataFrame()
    if not ok.empty:
        pts = pd.DataFrame({"vol": ok["ann. vol"], "return": ok["ann. return"]}, index=ok.index)
        hl = {live_name: (base_s["vol"], base_s["exp_return"])} if port is not None else None
        st.markdown("**Risk vs return**")
        st.plotly_chart(pui.scatter_risk_return(pts, highlight=hl, h=420), width="stretch")
with c2:
    if port is not None and "corr to portfolio" in tbl:
        d = tbl["corr to portfolio"].dropna().sort_values()
        fig = go.Figure(go.Bar(x=d.values, y=[names.get(t, t) for t in d.index], orientation="h",
                               marker_color=[pui.SERIES[0] if v < 0.5 else pui.SERIES[1] for v in d.values],
                               hovertemplate="%{y}<br>ρ %{x:.2f}<extra></extra>"))
        fig.update_xaxes(range=[-1, 1], title=f"Correlation to {live_name}")
        st.markdown("**Correlation to the live portfolio** (orange ≥ 0.5 = adds little diversification)")
        st.plotly_chart(pui._layout(fig, 420, showlegend=False), width="stretch")

st.divider()
a1, a2, a3 = st.columns([2, 1, 1])
pickd = a1.multiselect("Selected candidates", cand, format_func=lambda t: names.get(t, t), key="wl_pick")
if a2.button("➕ Add to a modelling scenario", width="stretch", disabled=not pickd):
    scen = st.session_state.setdefault("pf_scen", {})
    st.session_state.setdefault("pf_scen_ver", {})
    nm = "Watchlist adds"
    base = scen.get("Current", pd.DataFrame(columns=["ticker", "name", "account", "category", "weight"])).copy()
    base["weight"] = base["weight"] * (1 - add_w * len(pickd))
    add = pd.DataFrame({"ticker": pickd, "name": [names.get(t, t) for t in pickd], "account": "", "category": "Watchlist",
                        "weight": add_w})
    scen[nm] = pd.concat([base, add], ignore_index=True)
    st.session_state["pf_scen_ver"][nm] = st.session_state["pf_scen_ver"].get(nm, 0) + 1
    st.switch_page("pages/22_Portfolio_Modelling.py")
if a3.button("🔬 Analyse selected", width="stretch", disabled=not pickd):
    st.session_state["pf_focus"] = {"kind": "watchlist", "name": wl_name, "tickers": pickd}
    st.switch_page("pages/24_Constituent_Analysis.py")
pui.formulas("Marginal impact of a new position", "Beta", "Correlation", "Sharpe ratio")
