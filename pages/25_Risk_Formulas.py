import streamlit as st

from src import portfolio as pf
from src import portfolio_ui as pui
from src.common import bootstrap

bootstrap("Risk Formulas", "📐")
cfg = pui.settings_sidebar()

st.title("📐 Risk formulas & methodology")
st.caption("Every portfolio number in this app, with the formula used to calculate it. The same definitions appear "
           "in the 'How these numbers are calculated' expanders on each page.")

st.markdown(f"""
**Current settings:** base currency **{cfg['base']}** · **{cfg['frequency']}** returns (P = {pf.PERIODS_PER_YEAR[cfg['frequency']]}
periods per year) · lookback **{cfg['lookback']}** · risk-free **{cfg['rf']:.2%}** · VaR **{cfg['conf']:.1%}** over
**{cfg['h']}** trading days (= {pf.horizon_periods(cfg['h'], pf.PERIODS_PER_YEAR[cfg['frequency']]):.2f} {cfg['frequency'].lower()} periods).
""")

groups = {
    "Inputs": ["Returns", "Annualised return", "Annualised volatility", "Covariance matrix"],
    "Portfolio risk": ["Portfolio variance & volatility", "Expected portfolio return", "Risk contribution", "Diversification",
                       "Correlation"],
    "Risk-adjusted return": ["Sharpe ratio", "Sortino ratio", "Tracking error & information ratio", "Maximum drawdown"],
    "Market sensitivity": ["Beta", "Target volatility & beta hedge"],
    "Value at Risk": ["Parametric VaR", "Historical VaR", "Expected Shortfall (CVaR)", "Cornish-Fisher VaR", "Monte Carlo VaR"],
    "Construction & scenarios": ["Weighting schemes", "Stress test", "Factor shock", "Monte Carlo projection",
                                 "Marginal impact of a new position"],
}
for g, keys in groups.items():
    st.subheader(g)
    for k in keys:
        latex, text = pf.FORMULAS[k]
        with st.container(border=True):
            st.markdown(f"**{k}**")
            st.latex(latex)
            st.caption(text)

st.subheader("Data handling")
st.markdown("""
- **Prices**: Yahoo Finance adjusted closes (dividends reinvested), cached on disk for 6 hours; *Refresh prices* in the sidebar forces a re-download.
- **JSE cents/rands glitches**: JSE shares are quoted in cents; if a bar jumps by ~100× (a unit flip) the rest of the series is rescaled, and one-bar spikes that immediately reverse are removed. These corrections are listed under *Data notes* on each page. (This is what caused the 7,094% "volatility" for STX40 in the old risk report.)
- **FX**: each asset is converted to the base currency with Yahoo's `CCYBASE=X` daily rate (e.g. `USDZAR=X`). Benchmarks are converted too, so betas are measured consistently.
- **Mixed histories**: covariances use each pair's full overlapping history; the constant-weight back-test re-spreads the weight of a not-yet-listed asset over the others until it has data.
- **Cash** (`CASH` ticker): zero volatility, earns the risk-free rate.
- **Frequencies**: weekly = Friday close, monthly = month-end close. Daily data drops weekends (crypto) and forward-fills holidays up to 5 days.
- **Check against your workbook**: using the TFSA_WEEKLY_VOL sheet's own weekly returns and allocations, this engine reproduces its portfolio volatility (9.7639%) and equal-weight average correlation (0.2819) exactly.
""")
