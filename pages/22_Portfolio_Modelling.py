import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import portfolio as pf
from src import portfolio_ui as pui
from src import universe as uni
from src.common import bootstrap

bootstrap("Portfolio Modelling", "🧪")
cfg = pui.settings_sidebar()
instruments = uni.load_instruments()

st.title("🧪 Portfolio Modelling & Construction — what *could be*")
st.caption("Build alternative versions of the portfolio side by side. Each scenario tab is an editable list of "
           "constituents and weights; the analysis tabs compare every scenario against the baseline.")

SCEN_COLS = ["ticker", "weight", "name", "category", "account"]


def scen_state() -> dict:
    if "pf_scen" not in st.session_state:
        st.session_state["pf_scen"] = {}      # name -> base DataFrame (fed to editor)
        st.session_state["pf_scen_ver"] = {}  # name -> editor version
    return st.session_state["pf_scen"]


def put_scenario(name: str, df: pd.DataFrame):
    df = df.copy()
    for c in SCEN_COLS:
        if c not in df.columns:
            df[c] = "" if c != "weight" else np.nan
    df = df[SCEN_COLS]
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(0)
    scen_state()[name] = df.reset_index(drop=True)
    st.session_state["pf_scen_ver"][name] = st.session_state["pf_scen_ver"].get(name, 0) + 1


def from_holdings(h: pd.DataFrame) -> pd.DataFrame:
    h = h[h["ticker"] != ""]
    g = h.groupby("ticker").agg(name=("name", "first"), account=("account", "first"),
                                category=("category", "first"), weight=("weight", "sum")).reset_index()
    if g["weight"].sum() > 0:
        g["weight"] = g["weight"] / g["weight"].sum()   # re-spread weight of rows without a ticker
    return g.sort_values("weight", ascending=False)


# --------------------------------------------------------------------------
# Baseline + scenario manager
# --------------------------------------------------------------------------
c1, c2 = st.columns([1.2, 2])
with c1:
    base_name, base_h = pui.pick("live", "Baseline (live portfolio)", "pf_model_base")
scen = scen_state()
if base_h is not None and "Current" not in scen:
    put_scenario("Current", from_holdings(base_h))
live_value = base_h["value"].sum(min_count=1) if base_h is not None else np.nan

with c2:
    with st.expander("➕ Add a scenario", expanded=len(scen) <= 1):
        a1, a2, a3 = st.columns([1.2, 1.4, 1])
        src_opts = ["Copy of Current", "Saved model portfolio", "Saved live portfolio", "Blank"]
        src = a1.selectbox("Start from", src_opts, key="pf_new_src")
        new_name = a3.text_input("Scenario name", value=f"Scenario {chr(65 + max(0, len(scen) - 1))}", key="pf_new_name")
        pick_saved = None
        if src == "Saved model portfolio":
            pick_saved = a2.selectbox("Model", pui.available("model") or ["(none)"], key="pf_new_model")
        elif src == "Saved live portfolio":
            pick_saved = a2.selectbox("Live", pui.available("live") or ["(none)"], key="pf_new_live")
        if st.button("Create scenario", type="primary"):
            if src == "Copy of Current" and "Current" in scen:
                put_scenario(new_name, scen["Current"])
            elif src == "Blank":
                put_scenario(new_name, pd.DataFrame(columns=SCEN_COLS))
            elif pick_saved and pick_saved != "(none)":
                kind = "model" if src.startswith("Saved model") else "live"
                put_scenario(new_name, from_holdings(pui.get_holdings(kind, pick_saved)))
            st.rerun()

if not scen:
    st.info("Pick a baseline live portfolio or create a scenario to begin.")
    st.stop()

names = list(scen.keys())
tab_objs = st.tabs([f"📝 {n}" for n in names] + ["⚖️ Compare", "🧭 Optimiser & frontier", "💥 Stress tests",
                                                 "🔮 Monte Carlo", "🔁 Rebalance to scenario"])

# Market data for the union of every scenario's tickers (so comparisons share one dataset)
all_tickers = sorted({t for df in scen.values() for t in df["ticker"] if t} | {pf.CASH_TICKER})
wl_tickers = []
for wname in pui.available("watchlist"):
    wl_tickers += pui.get_holdings("watchlist", wname)["ticker"].tolist()
md = pui.market_data(all_tickers, cfg)
pui.data_quality_box(md)

current = {}  # scenario -> weights Series (after editor edits)
labels = {}

# --------------------------------------------------------------------------
# Scenario tabs
# --------------------------------------------------------------------------
for n, tab in zip(names, tab_objs[: len(names)]):
    with tab:
        base_df = scen[n].copy()
        base_df["weight"] = base_df["weight"] * 100
        ver = st.session_state["pf_scen_ver"].get(n, 0)
        e1, e2 = st.columns([1.7, 1])
        with e1:
            ed = st.data_editor(base_df, num_rows="dynamic", width="stretch", key=f"scen_ed_{n}_{ver}", height=420,
                                column_config={"ticker": st.column_config.TextColumn("Yahoo ticker"),
                                               "weight": st.column_config.NumberColumn("Weight %", format="%.2f", step=0.25)})
        ed = ed.copy()
        ed["ticker"] = ed["ticker"].fillna("").astype(str).str.upper().str.strip()
        ed["weight"] = pd.to_numeric(ed["weight"], errors="coerce").fillna(0) / 100
        ed = ed[ed["ticker"] != ""]
        for r in ed.itertuples():
            labels[r.ticker] = (r.name or r.ticker)[:28] if isinstance(r.name, str) and r.name else r.ticker
        tot = ed["weight"].sum()
        with e2:
            pui.imetric(st, "Weights sum", pui.pct(tot, 2), None if abs(tot - 1) < 1e-6 else ("under-invested" if tot < 1 else "over 100%"))
            fill_cash = st.toggle("Treat shortfall as CASH", value=True, key=f"cash_{n}",
                                  help="If weights sum to less than 100%, the rest earns the risk-free rate.")
            add = st.multiselect("Add from watchlists", [t for t in dict.fromkeys(wl_tickers) if t not in ed["ticker"].values],
                                 key=f"add_{n}")
            typed = st.text_input("...or type tickers", key=f"typed_{n}", placeholder="e.g. SPY, STXRES.JO")
            aw = st.number_input("Weight % for added names", 0.0, 100.0, 2.0, 0.5, key=f"aw_{n}")
            if st.button("Add", key=f"addbtn_{n}", width="stretch"):
                new = add + [t.strip().upper() for t in typed.split(",") if t.strip()]
                rows = pd.DataFrame({"ticker": new, "name": [pf.lookup_name(t, instruments) for t in new],
                                     "account": "", "category": "", "weight": aw / 100})
                put_scenario(n, pd.concat([ed, rows], ignore_index=True))
                st.rerun()
            b1, b2 = st.columns(2)
            if b1.button("Normalise to 100%", key=f"norm_{n}", width="stretch") and tot > 0:
                ed["weight"] = ed["weight"] / tot
                put_scenario(n, ed)
                st.rerun()
            if b2.button("🗑️ Delete scenario", key=f"del_{n}", width="stretch"):
                scen.pop(n)
                st.rerun()

        w = ed.groupby("ticker")["weight"].sum()
        w = w[w > 0]
        if fill_cash and 0 < w.sum() < 1:
            w[pf.CASH_TICKER] = w.get(pf.CASH_TICKER, 0) + (1 - w.sum())
        current[n] = w

        # weighting schemes
        with st.expander("⚙️ Re-weight this scenario (construction rules)"):
            r1, r2, r3, r4 = st.columns([1.6, 1, 1, 1])
            scheme = r1.selectbox("Scheme", ["Equal weight", "Inverse volatility", "Inverse beta (beta parity)",
                                             "Equal risk contribution", "Minimum variance", "Maximum Sharpe",
                                             "Scale to target volatility (rest in cash)"], key=f"sch_{n}")
            maxw = r2.number_input("Max weight %", 1.0, 100.0, 25.0, 1.0, key=f"mw_{n}") / 100
            bench_for_beta = r3.selectbox("Beta vs", list(md.bench_returns.columns) or ["—"], key=f"bb_{n}")
            tv = r4.number_input("Target vol %", 1.0, 60.0, 12.0, 0.5, key=f"tv_{n}") / 100
            keep_cash = st.checkbox("Keep current cash weight fixed", value=True, key=f"kc_{n}")
            if st.button("Apply scheme", key=f"apply_{n}", type="primary"):
                risky = [t for t in w.index if t in md.returns.columns and t != pf.CASH_TICKER]
                cash_w = w.get(pf.CASH_TICKER, 0) if keep_cash else 0
                cov = pf.cov_matrix(md.returns[risky], md.ppy)
                mu = pf.ann_mean(md.returns[risky], md.ppy)
                if scheme == "Equal weight":
                    nw = pf.w_equal(risky)
                elif scheme == "Inverse volatility":
                    nw = pf.w_inverse_vol(cov)
                elif scheme.startswith("Inverse beta"):
                    betas = pd.Series({t: pf.beta_to(md.returns[t], md.bench_returns[bench_for_beta])[0] for t in risky})
                    nw = pf.w_inverse_beta(betas)
                elif scheme == "Equal risk contribution":
                    nw = pf.w_equal_risk(cov, max(maxw, 1 / len(risky)))
                elif scheme == "Minimum variance":
                    nw = pf.w_min_variance(cov, max(maxw, 1 / len(risky)))
                elif scheme == "Maximum Sharpe":
                    nw = pf.w_max_sharpe(mu, cov, md.rf_annual, max(maxw, 1 / len(risky)))
                else:
                    cur_r = w.reindex(risky).fillna(0)
                    cur_r = cur_r / cur_r.sum()
                    nw, cash_add = pf.scale_to_target_vol(cur_r, cov, tv)
                    cash_w = cash_add
                nw = nw * (1 - cash_w)
                newdf = ed.set_index("ticker").reindex(nw.index)
                newdf["weight"] = nw
                newdf = newdf.reset_index().rename(columns={"index": "ticker"})
                newdf["name"] = [labels.get(t, pf.lookup_name(t, instruments)) for t in newdf["ticker"]]
                if cash_w > 0:
                    newdf = pd.concat([newdf, pd.DataFrame([{"ticker": pf.CASH_TICKER, "name": "Cash", "weight": cash_w}])])
                put_scenario(n, newdf.fillna(""))
                st.rerun()
            st.caption("Long-only; weights sum to 100%. Inverse beta = the 'beta parity' column in your PORT_BETA sheet.")

        if len(w) == 0:
            st.info("Add constituents with weights to see this scenario's risk.")
            continue
        s = pf.portfolio_summary(md, w, cfg["conf"], cfg["h"], mc_sims=5000)
        if "error" in s:
            st.warning(s["error"])
            continue
        base_s = None
        if n != "Current" and "Current" in current:
            base_s = pf.portfolio_summary(md, current["Current"], cfg["conf"], cfg["h"], mc_sims=5000)
        m = st.columns(4) + st.columns(4)
        def _d(key, fmt=pui.pct, bkey=None):
            if base_s is None or "error" in base_s:
                return None
            a = s[key] if bkey is None else s["bench"][bkey]["beta_weighted"]
            b = base_s[key] if bkey is None else base_s["bench"][bkey]["beta_weighted"]
            return f"{(a - b) * (100 if fmt is pui.pct else 1):+.2f}{'pp' if fmt is pui.pct else ''}"
        m[0].metric("Volatility", pui.pct(s["vol"]), _d("vol"), delta_color="inverse")
        m[1].metric("Exp. return", pui.pct(s["exp_return"]), _d("exp_return"))
        m[2].metric("Sharpe", pui.num(s["sharpe"]), _d("sharpe", pui.num))
        m[3].metric(f"VaR {cfg['conf']:.0%} {cfg['h']}d", pui.pct(s["var_param"]), _d("var_param"), delta_color="inverse")
        m[4].metric("Max DD", pui.pct(s["max_dd"]), _d("max_dd"))
        blist = list(s["bench"].keys())
        for i in range(min(3, len(blist))):
            pui.imetric(m[5 + i], f"β {blist[i]}", pui.num(s["bench"][blist[i]]["beta_weighted"]),
                            _d("vol", pui.num, blist[i]) if base_s is not None else None)
        st.plotly_chart(pui.bar_weight_vs_risk(s["risk"], labels), width="stretch", key=f"rc_{n}")
        sv1, sv2 = st.columns([2, 1])
        save_name = sv1.text_input("Save this scenario as a model portfolio named", value=f"{n}", key=f"svn_{n}")
        if sv2.button("💾 Save as model", key=f"sv_{n}", width="stretch"):
            h = ed.copy()
            h["value"] = np.nan
            if fill_cash and 0 < h["weight"].sum() < 1:
                h = pd.concat([h, pd.DataFrame([{"ticker": pf.CASH_TICKER, "name": "Cash", "weight": 1 - h["weight"].sum()}])])
            pf.save_portfolio("model", save_name, pf.normalise_holdings(h), f"Saved from modelling scenario '{n}'")
            st.success(f"Saved model portfolio **{save_name}**.")

summaries = {n: pf.portfolio_summary(md, w, cfg["conf"], cfg["h"], mc_sims=5000) for n, w in current.items() if len(w)}
summaries = {n: s for n, s in summaries.items() if "error" not in s}
ti = len(names)

# --------------------------------------------------------------------------
# Compare
# --------------------------------------------------------------------------
with tab_objs[ti]:
    if not summaries:
        st.info("No scenario has weights yet.")
    else:
        rows = {}
        for n, s in summaries.items():
            r = {"Holdings": s["n_assets"], "Volatility": s["vol"], "Expected return": s["exp_return"], "CAGR (back-test)": s["cagr"],
                 "Sharpe": s["sharpe"], "Sortino": s["sortino"], "Max drawdown": s["max_dd"],
                 f"VaR {cfg['conf']:.0%} {cfg['h']}d param": s["var_param"], f"VaR {cfg['conf']:.0%} {cfg['h']}d hist": s["var_hist"],
                 "CVaR hist": s["cvar_hist"], "Diversification ratio": s["div_ratio"], "Effective N": s["eff_n"],
                 "Avg correlation (weighted)": s["avg_corr_weighted"]}
            for b, bb in s["bench"].items():
                r[f"Beta {b}"] = bb["beta_weighted"]
                r[f"Tracking error {b}"] = bb["tracking_error"]
            if live_value == live_value:
                r[f"VaR {cfg['conf']:.0%} {cfg['h']}d (money, param)"] = s["var_param"] * live_value
            rows[n] = r
        comp = pd.DataFrame(rows)
        pct_rows = [i for i in comp.index if any(k in i for k in ("Vol", "return", "CAGR", "drawdown", "VaR", "CVaR", "Tracking"))
                    and "money" not in i]
        disp = comp.copy().astype(object)
        for i in comp.index:
            disp.loc[i] = [pui.pct(v) if i in pct_rows else (pui.money(v) if "money" in i else pui.num(v, 2 if i != "Holdings" else 0))
                           for v in comp.loc[i]]
        st.dataframe(disp, width="stretch", height=36 * len(disp) + 40)
        st.caption("On the scenario tabs, the small deltas under each metric are versus *Current* (pp = percentage points).")

        c1, c2 = st.columns(2)
        pts = {n: (s["vol"], s["exp_return"]) for n, s in summaries.items()}
        c1.markdown("**Risk vs return**")
        c1.plotly_chart(pui.scatter_risk_return(pd.DataFrame(columns=["vol", "return"]), highlight=pts, h=380),
                        width="stretch")
        metric = c2.selectbox("Compare metric", ["Volatility", f"VaR {cfg['conf']:.0%} {cfg['h']}d param", "Max drawdown",
                                                 "Sharpe"] + [f"Beta {b}" for b in md.bench_returns.columns], key="cmp_metric")
        vals = comp.loc[metric]
        is_pct = metric in pct_rows
        fig = go.Figure(go.Bar(x=vals.index, y=vals.values * (100 if is_pct else 1),
                               marker_color=[pui.SERIES[i % 8] for i in range(len(vals))],
                               hovertemplate="%{x}<br>%{y:.2f}" + ("%" if is_pct else "") + "<extra></extra>"))
        fig.update_yaxes(title=metric, ticksuffix="%" if is_pct else "")
        c2.plotly_chart(pui._layout(fig, 380, showlegend=False), width="stretch")

        cum = pd.DataFrame({n: (1 + s["series"]).cumprod() - 1 for n, s in summaries.items()})
        st.plotly_chart(pui.line_chart(cum, "Back-tested cumulative return"), width="stretch")
        dd = pd.DataFrame({n: pf.drawdown_series(s["series"]) for n, s in summaries.items()})
        st.plotly_chart(pui.line_chart(dd, "Drawdown", h=280), width="stretch")

        wt = pd.DataFrame({n: w for n, w in current.items()}).fillna(0)
        wt.insert(0, "name", [labels.get(t, pf.lookup_name(t, instruments)) for t in wt.index])
        if "Current" in wt:
            for n in current:
                if n != "Current":
                    wt[f"Δ {n}"] = wt[n] - wt["Current"]
        wcols = [c for c in wt.columns if c != "name"]
        wt = pui.as_pct(wt.sort_values(wcols[0], ascending=False), wcols)
        st.markdown("**Weights by scenario**")
        st.dataframe(wt, width="stretch", column_config=pui.pct_cols(wt, wcols))
        pui.formulas("Portfolio variance & volatility", "Expected portfolio return", "Sharpe ratio", "Parametric VaR",
                     "Historical VaR", "Diversification", "Beta")

# --------------------------------------------------------------------------
# Optimiser & efficient frontier
# --------------------------------------------------------------------------
with tab_objs[ti + 1]:
    o1, o2, o3 = st.columns([1.4, 1, 1])
    uni_src = o1.selectbox("Investable universe", [f"Tickers in {n}" for n in names] + ["All scenarios + watchlists"], key="opt_uni")
    maxw = o2.number_input("Max weight per asset %", 1.0, 100.0, 20.0, 1.0, key="opt_maxw") / 100
    use_cash = o3.checkbox("Include CASH", value=False, key="opt_cash")
    if uni_src.startswith("Tickers in"):
        tick = [t for t in current.get(uni_src[len("Tickers in "):], pd.Series(dtype=float)).index]
    else:
        tick = sorted(set(all_tickers) | set(wl_tickers))
    md_opt = md if set(tick) <= set(md.returns.columns) else pui.market_data(tick, cfg)
    tick = [t for t in tick if t in md_opt.returns.columns and (use_cash or t != pf.CASH_TICKER)]
    if len(tick) < 2:
        st.info("Need at least two instruments with data.")
    elif st.button("Run optimiser", type="primary") or st.session_state.get("opt_res", {}).get("key") == (tuple(tick), maxw, cfg["frequency"], cfg["lookback"], cfg["base"]):
        key = (tuple(tick), maxw, cfg["frequency"], cfg["lookback"], cfg["base"])
        if st.session_state.get("opt_res", {}).get("key") != key:
            with st.spinner("Optimising..."):
                R = md_opt.returns[tick]
                cov, mu = pf.cov_matrix(R, md_opt.ppy), pf.ann_mean(R, md_opt.ppy).fillna(0)
                mw = max(maxw, 1 / len(tick))
                res = {"Min variance": pf.w_min_variance(cov, mw), "Max Sharpe": pf.w_max_sharpe(mu, cov, md_opt.rf_annual, mw),
                       "Equal risk contribution": pf.w_equal_risk(cov, mw), "Inverse volatility": pf.w_inverse_vol(cov),
                       "Equal weight": pf.w_equal(tick)}
                st.session_state["opt_res"] = {"key": key, "res": res, "frontier": pf.efficient_frontier(mu, cov, mw, 25),
                                               "cloud": pf.random_portfolios(mu, cov, 2500), "mu": mu, "cov": cov}
        o = st.session_state["opt_res"]
        mu, cov = o["mu"], o["cov"]
        hl = {}
        for k_, w_ in o["res"].items():
            hl[k_] = (float(np.sqrt(w_ @ cov @ w_)), float(w_ @ mu))
        for n, s in summaries.items():
            hl[n] = (s["vol"], s["exp_return"])
        assets = pd.DataFrame({"vol": np.sqrt(np.diag(cov)), "return": mu.values}, index=[labels.get(t, t)[:14] for t in cov.index])
        st.plotly_chart(pui.scatter_risk_return(assets, highlight=hl, frontier=o["frontier"], cloud=o["cloud"], h=560),
                        width="stretch")
        st.caption("The frontier and optimised mixes use historical means as expected returns -- these are noisy, so "
                   "treat Max Sharpe as a sensitivity, not a recommendation. Min variance / ERC depend only on Σ and are more stable.")
        ow = pd.DataFrame(o["res"])
        ow.insert(0, "name", [labels.get(t, pf.lookup_name(t, instruments)) for t in ow.index])
        wc = list(o["res"].keys())
        ow = pui.as_pct(ow.sort_values("Max Sharpe", ascending=False), wc)
        st.dataframe(ow.round(2), width="stretch", column_config=pui.pct_cols(ow, wc))
        k1, k2 = st.columns([1.4, 1])
        which = k1.selectbox("Create a scenario from", wc, key="opt_make")
        if k2.button("➕ Create scenario", width="stretch"):
            w_ = o["res"][which]
            put_scenario(which, pd.DataFrame({"ticker": w_.index, "name": [labels.get(t, t) for t in w_.index], "weight": w_.values}))
            st.rerun()
    pui.formulas("Weighting schemes", "Risk contribution")

# --------------------------------------------------------------------------
# Stress tests
# --------------------------------------------------------------------------
with tab_objs[ti + 2]:
    if not summaries:
        st.info("No scenarios.")
    else:
        st.markdown("#### Historical scenarios — today's weights through past crises")
        bl = list(md.bench_returns.columns)
        proxy_b = st.selectbox("Proxy benchmark for assets that didn't exist yet", bl or ["—"], key="st_b")
        with st.expander("Add a custom window"):
            d1, d2, d3 = st.columns(3)
            cn = d1.text_input("Label", "Custom", key="st_cn")
            cs = d2.date_input("Start", pd.Timestamp("2018-01-26"), key="st_cs")
            ce = d3.date_input("End", pd.Timestamp("2018-12-24"), key="st_ce")
        windows = dict(pf.STRESS_SCENARIOS)
        windows[f"{cn} ({cs:%b-%y} → {ce:%b-%y})"] = (str(cs), str(ce))
        res, detail = {}, {}
        for wn, (a, b) in windows.items():
            res[wn] = {}
            for n in summaries:
                d = pf.stress_test(md, current[n], a, b, proxy_b if bl else None)
                detail[(wn, n)] = d
                res[wn][n] = d.attrs.get("portfolio_return", np.nan) if not d.empty else np.nan
            res[wn][f"{proxy_b} (benchmark)"] = detail[(wn, list(summaries)[0])].attrs.get("benchmark_return", np.nan)
        rt = pd.DataFrame(res).T
        first = list(summaries)[0]
        rt[f"weight covered ({first})"] = pd.Series({wn: detail[(wn, first)].attrs.get("coverage", np.nan) for wn in windows})
        num_cols = list(rt.columns)
        rtd = pui.as_pct(rt, num_cols)
        st.dataframe(rtd, width="stretch", column_config=pui.pct_cols(rtd, num_cols))
        s1, s2 = st.columns(2)
        wsel = s1.selectbox("Detail for window", list(windows), key="st_w")
        nsel = s2.selectbox("Scenario", list(summaries), key="st_n")
        d = detail[(wsel, nsel)].copy()
        if not d.empty:
            d["label"] = [labels.get(t, t) for t in d["ticker"]]
            d = d[d["weight"] > 0].sort_values("contribution")
            show = pd.concat([d.head(12), d.tail(8)]).drop_duplicates("ticker")
            st.plotly_chart(pui.contribution_bar(show, "contribution", "label", title_x="Contribution to portfolio return"),
                            width="stretch")
            dd_ = pui.as_pct(d[["label", "weight", "return", "contribution", "source"]], ["weight", "return", "contribution"])
            with st.expander("All holdings"):
                st.dataframe(dd_, hide_index=True, width="stretch", column_config=pui.pct_cols(dd_, ["weight", "return", "contribution"]))
        pui.formulas("Stress test")

        st.divider()
        st.markdown("#### Hypothetical factor shock")
        fac = md.bench_returns.copy()
        if cfg["base"] != "LOCAL" and not md.fx_returns.empty:
            fx_c = "USD" if cfg["base"] == "ZAR" else "ZAR"
            if fx_c in md.fx_returns:
                fac[f"{fx_c}/{cfg['base']}"] = md.fx_returns[fx_c]
        if fac.empty:
            st.info("No factors available.")
        else:
            st.caption("Each holding's return is regressed on these factor returns (all in base currency); the shock is "
                       "pushed through the loadings. A rand-weakening shock is a positive USD/ZAR move.")
            cols = st.columns(len(fac.columns))
            shocks = {}
            for c, f in zip(cols, fac.columns):
                shocks[f] = c.slider(f"{f} move %", -50.0, 50.0, -20.0 if "/" not in f else 10.0, 1.0, key=f"fs_{f}") / 100
            L = pf.factor_model(md, fac)
            out = {}
            for n in summaries:
                fs = pf.factor_shock(L, current[n], shocks)
                out[n] = fs.attrs["portfolio_return"]
            fig = go.Figure(go.Bar(x=list(out), y=np.array(list(out.values())) * 100,
                                   marker_color=[pui.UP if v >= 0 else pui.DOWN for v in out.values()],
                                   hovertemplate="%{x}<br>%{y:.2f}%<extra></extra>"))
            fig.update_yaxes(title="Estimated portfolio return", ticksuffix="%")
            st.plotly_chart(pui._layout(fig, 320, showlegend=False), width="stretch")
            if live_value == live_value:
                st.caption(" · ".join(f"**{n}**: {pui.money(v * live_value, cfg['base'])}" for n, v in out.items()))
            with st.expander("Factor loadings per holding"):
                Ld = L.copy()
                Ld.index = [labels.get(t, t) for t in Ld.index]
                st.dataframe(Ld.round(3), width="stretch")
            pui.formulas("Factor shock")

# --------------------------------------------------------------------------
# Monte Carlo
# --------------------------------------------------------------------------
with tab_objs[ti + 3]:
    if not summaries:
        st.info("No scenarios.")
    else:
        m1, m2, m3, m4, m5 = st.columns(5)
        sel = m1.multiselect("Scenarios", list(summaries), default=list(summaries)[:2], key="mc_sel")
        start = m2.number_input("Starting value", 0.0, 1e10, float(live_value) if live_value == live_value else 100000.0, 1000.0, key="mc_start")
        contrib = m3.number_input("Monthly contribution", 0.0, 1e8, 0.0, 500.0, key="mc_c")
        yrs = m4.slider("Years", 1, 30, 5, key="mc_y")
        method = m5.radio("Method", ["Bootstrap", "Normal"], key="mc_m", help="Bootstrap resamples actual historical "
                          "portfolio returns (keeps fat tails); Normal uses μp and σp.")
        target = st.number_input("Goal value (probability of reaching it is shown)", 0.0, 1e11, start * 1.5, 1000.0, key="mc_goal")
        per_period = contrib * 12 / md.ppy
        rows = []
        for i, n in enumerate(sel):
            s = summaries[n]
            proj = pf.project_value(s["series"], md.ppy, yrs, start, per_period, method, 4000,
                                    s["exp_return"], s["vol"])
            st.markdown(f"**{n}**")
            st.plotly_chart(pui.fan_chart(proj, md.ppy, cfg["base"], h=360), width="stretch", key=f"fan_{n}")
            f = proj["final"]
            rows.append({"Scenario": n, "Median": np.median(f), "5th pct": np.percentile(f, 5), "95th pct": np.percentile(f, 95),
                         "Invested": proj["invested"][-1], "P(loss)": proj["prob_loss"], "P(reach goal)": float(np.mean(f >= target))})
        if rows:
            t = pd.DataFrame(rows)
            for c in ("Median", "5th pct", "95th pct", "Invested"):
                t[c] = t[c].map(lambda v: pui.money(v, cfg["base"]))
            for c in ("P(loss)", "P(reach goal)"):
                t[c] = t[c].map(lambda v: pui.pct(v, 1))
            st.dataframe(t, hide_index=True, width="stretch")
        pui.formulas("Monte Carlo projection")

# --------------------------------------------------------------------------
# Rebalance
# --------------------------------------------------------------------------
with tab_objs[ti + 4]:
    if "Current" not in current or len(current) < 2:
        st.info("Create a scenario other than *Current* to generate a trade list.")
    else:
        r1, r2 = st.columns(2)
        tgt = r1.selectbox("Target scenario", [n for n in current if n != "Current"], key="rb_t")
        cap = r2.number_input(f"Capital ({cfg['base']})", 0.0, 1e11, float(live_value) if live_value == live_value else 100000.0,
                              1000.0, key="rb_cap")
        last_px = md.prices_base.ffill().iloc[-1] if not md.prices_base.empty else pd.Series(dtype=float)
        # JSE shares are quoted in cents on Yahoo -> rands per share
        div = pd.Series({t: 100.0 for t in last_px.index if str(t).endswith(".JO") and cfg["base"] in ("ZAR", "LOCAL")})
        tl = pf.trade_list(current["Current"], current[tgt], cap, last_px, div)
        tl.insert(0, "name", [labels.get(t, pf.lookup_name(t, instruments)) for t in tl.index])
        tl = tl[(tl["current weight"] > 0) | (tl["target weight"] > 0)]
        pc = ["current weight", "target weight", "Δ weight"]
        tld = pui.as_pct(tl, pc)
        cc = pui.pct_cols(tld, pc)
        cc.update({c: st.column_config.NumberColumn(c, format="%,.2f") for c in ("current value", "target value", "trade value", "last price (base)")})
        st.dataframe(tld, width="stretch", column_config=cc, height=520)
        b1, b2, b3 = st.columns(3)
        b1.metric("Buys", pui.money(tl.loc[tl["trade value"] > 0, "trade value"].sum(), cfg["base"]))
        b2.metric("Sells", pui.money(-tl.loc[tl["trade value"] < 0, "trade value"].sum(), cfg["base"]))
        b3.metric("Turnover", pui.pct(tl["Δ weight"].abs().sum() / 2, 1))
        st.caption("Units are approximate (latest close, base currency, JSE prices converted from cents). Check "
                   "sub-account limits (e.g. TFSA contribution caps) and costs before trading.")
        st.download_button("⬇️ Trade list (CSV)", tl.to_csv().encode(), f"trades_to_{tgt}.csv")
