import io

import numpy as np
import pandas as pd
import streamlit as st

from src import portfolio as pf
from src import portfolio_ui as pui
from src import universe as uni
from src.common import bootstrap

bootstrap("Portfolio Builder", "🧱")
cfg = pui.settings_sidebar()

st.title("🧱 Portfolio Builder")
st.caption(
    "Create or update a **Live portfolio** (what you actually hold), a **Model portfolio** (what could be) or a "
    "**Watchlist** (candidates). Paste straight from Excel -- tickers or names, weights or rand values, with or "
    "without account/category columns -- then check the matched tickers and save."
)

instruments = uni.load_instruments()
KIND_LABEL = {"live": "Live portfolio (what is)", "model": "Model portfolio (what could be)", "watchlist": "Watchlist"}

if "pf_edit" not in st.session_state:
    st.session_state["pf_edit"] = pd.DataFrame(columns=pf.HOLDING_COLUMNS)
    st.session_state["pf_edit_ver"] = 0
    st.session_state["pf_edit_meta"] = {"kind": "live", "name": "", "notes": "", "value_ccy": "ZAR"}


def set_editor(df: pd.DataFrame, **meta):
    st.session_state["pf_edit"] = pf.normalise_holdings(df) if not df.empty else df
    st.session_state["pf_edit_ver"] += 1
    st.session_state["pf_edit_meta"].update(meta)


tab_paste, tab_edit, tab_saved = st.tabs(["📋 1 · Paste from Excel", "✏️ 2 · Review, edit & save", "💾 Saved portfolios"])

# --------------------------------------------------------------------------
with tab_paste:
    st.markdown(
        "Copy a block of cells in Excel (with or without the header row) and paste below. Recognised layouts include:\n"
        "- `Ticker | Weight` (weights as 0.25, 25 or 25%)\n"
        "- `Name | Category | Purchase value | Current value | % weighting ...` (your Easy Equities sheet -- "
        "several stacked account blocks like **EE_ZAR_Acc / EE_USD_Acc / EE_TSFA_Acc** are split into accounts, "
        "*Total* rows are skipped, *Aggregate Cash* becomes a CASH line)\n"
        "- any table with a ticker **or** name column plus a value **or** weight column."
    )
    text = st.text_area("Paste here", height=240, key="pf_paste_text",
                        placeholder="Ticker\tWeight\nSTXNDQ.JO\t20%\nSTX500.JO\t20%\nNVDA\t5%\n...")
    if text.strip():
        parsed = pf.parse_paste(text)
        if parsed is None or parsed.raw.empty:
            st.error("Couldn't read any rows from that paste.")
        else:
            for n in parsed.notes:
                st.caption(n)
            st.markdown("**Detected columns** -- change any that are wrong:")
            opts = ["(none)"] + parsed.columns
            roles = ["ticker", "name", "value", "weight", "account", "category"]
            cols = st.columns(len(roles))
            mapping = {}
            for c, role in zip(cols, roles):
                cur = parsed.mapping.get(role)
                sel = c.selectbox(role.title(), opts, index=opts.index(cur) if cur in opts else 0, key=f"pf_map_{role}")
                mapping[role] = None if sel == "(none)" else sel
            with st.expander("Raw rows read", expanded=False):
                st.dataframe(parsed.raw, width="stretch")
            h = pf.build_holdings(parsed, mapping, instruments)
            unresolved = h[h["ticker"] == ""]
            c1, c2, c3 = st.columns(3)
            c1.metric("Rows", len(h))
            c2.metric("Tickers matched", int((h["ticker"] != "").sum()))
            c3.metric("Need a ticker", len(unresolved))
            if not unresolved.empty:
                st.warning("No ticker found for: " + ", ".join(unresolved["name"]) +
                           ". Fill these in on the next tab (or they'll be ignored in risk calcs).")
            prev = pui.as_pct(h, ["weight"])
            st.dataframe(prev, hide_index=True, width="stretch", column_config=pui.pct_cols(prev, ["weight"]))
            k1, k2, k3, k4 = st.columns([1.3, 1.5, 0.8, 1])
            kind = k1.selectbox("Save as", list(KIND_LABEL), format_func=KIND_LABEL.get, key="pf_paste_kind")
            name = k2.text_input("Name", value=f"{'EE_Portfolio' if kind == 'live' else 'Model' if kind == 'model' else 'Watchlist'}_{pd.Timestamp.today():%Y-%m-%d}",
                                 key="pf_paste_name")
            vccy = k3.selectbox("Values in", ["ZAR", "USD"], key="pf_paste_ccy")
            if k4.button("➡️ Send to editor", type="primary", width="stretch"):
                set_editor(h, kind=kind, name=name, value_ccy=vccy)
                st.success("Loaded into the editor -- open tab 2 to review and save.")

# --------------------------------------------------------------------------
with tab_edit:
    meta = st.session_state["pf_edit_meta"]
    c1, c2, c3 = st.columns([1.3, 1.6, 0.8])
    meta["kind"] = c1.selectbox("Type", list(KIND_LABEL), index=list(KIND_LABEL).index(meta.get("kind", "live")),
                                format_func=KIND_LABEL.get, key="pf_edit_kind")
    meta["name"] = c2.text_input("Name", value=meta.get("name", ""), key=f"pf_edit_name_{st.session_state['pf_edit_ver']}")
    meta["value_ccy"] = c3.selectbox("Values in", ["ZAR", "USD"], index=["ZAR", "USD"].index(meta.get("value_ccy", "ZAR")),
                                     key=f"pf_edit_ccy_{st.session_state['pf_edit_ver']}")

    # quick-add from the universe
    with st.expander("➕ Add instruments by search", expanded=st.session_state["pf_edit"].empty):
        lab = {f"{r.symbol} — {r.name} ({r.market})": r.yf_ticker for r in instruments.itertuples()}
        add = st.multiselect("Search the global universe", sorted(lab), key="pf_add_sel")
        c_a, c_b = st.columns([2, 1])
        typed = c_a.text_input("...or type Yahoo tickers (comma separated), e.g. `STXNDQ.JO, NVDA, BTC-USD, CASH`", key="pf_add_typed")
        if c_b.button("Add", width="stretch"):
            new = [lab[a] for a in add] + [t.strip().upper() for t in typed.split(",") if t.strip()]
            cur = st.session_state["pf_edit"]
            rows = pd.DataFrame({"ticker": new, "name": [pf.lookup_name(t, instruments) for t in new],
                                 "account": "", "category": "", "value": np.nan, "weight": np.nan})
            set_editor(pd.concat([cur, rows], ignore_index=True))
            st.rerun()

    cur = st.session_state["pf_edit"].copy()
    view = cur.copy()
    view["weight"] = view["weight"] * 100
    edited = st.data_editor(
        view, num_rows="dynamic", width="stretch", key=f"pf_editor_{st.session_state['pf_edit_ver']}",
        column_config={
            "ticker": st.column_config.TextColumn("Yahoo ticker", help="e.g. STX40.JO, NVDA, BTC-USD, CASH"),
            "name": st.column_config.TextColumn("Name"),
            "account": st.column_config.TextColumn("Account / sub-account"),
            "category": st.column_config.TextColumn("Category"),
            "value": st.column_config.NumberColumn("Value", format="%.2f",
                                                   help="Current value. If any values are filled, weights are computed from values."),
            "weight": st.column_config.NumberColumn("Weight %", format="%.3f", help="Used only when no values are given."),
        },
    )
    edited = edited.copy()
    edited["weight"] = pd.to_numeric(edited["weight"], errors="coerce") / 100
    norm = pf.normalise_holdings(edited) if not edited.empty else edited

    b1, b2, b3, b4 = st.columns(4)
    if b1.button("🔎 Fill missing tickers from names", width="stretch"):
        for i, r in norm.iterrows():
            if not r["ticker"] and r["name"]:
                t, _ = pf.resolve_ticker(r["name"], instruments)
                norm.at[i, "ticker"] = t or ""
            if r["ticker"] and not r["name"]:
                norm.at[i, "name"] = pf.lookup_name(r["ticker"], instruments)
        set_editor(norm)
        st.rerun()
    if b2.button("⚖️ Equal-weight all rows", width="stretch"):
        norm["value"] = np.nan
        norm["weight"] = 1 / max(len(norm), 1)
        set_editor(norm)
        st.rerun()
    if b3.button("🧹 Clear", width="stretch"):
        set_editor(pd.DataFrame(columns=pf.HOLDING_COLUMNS), name="")
        st.rerun()

    if not norm.empty:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Holdings", len(norm))
        m2.metric("Total value", pui.money(norm["value"].sum(min_count=1), meta["value_ccy"]))
        m3.metric("Weights sum", pui.pct(norm["weight"].sum(), 1))
        m4.metric("Missing tickers", int((norm["ticker"] == "").sum()))
        if norm["account"].replace("", np.nan).notna().any():
            acc = norm.groupby(norm["account"].replace("", "(none)"))[["value", "weight"]].sum(min_count=1)
            acc = pui.as_pct(acc.reset_index(), ["weight"])
            st.dataframe(acc, hide_index=True, width="stretch", column_config=pui.pct_cols(acc, ["weight"]))

    notes = st.text_area("Notes (optional)", value=meta.get("notes", ""), key=f"pf_notes_{st.session_state['pf_edit_ver']}")
    s1, s2, s3 = st.columns(3)
    if s1.button("💾 Save", type="primary", width="stretch", disabled=norm.empty or not meta["name"]):
        pf.save_portfolio(meta["kind"], meta["name"], norm, notes, {"value_ccy": meta["value_ccy"]})
        pui.working()[meta["kind"]][meta["name"]] = norm
        st.session_state["pf_edit"] = norm
        st.success(f"Saved **{meta['name']}** as {KIND_LABEL[meta['kind']]} (data/portfolios/{meta['kind']}/).")
    if s2.button("Use for this session only", width="stretch", disabled=norm.empty or not meta["name"]):
        pui.working()[meta["kind"]][meta["name"]] = norm
        st.success("Available on the risk / modelling pages until you close the app.")
    s3.download_button("⬇️ Download CSV", norm.to_csv(index=False).encode(), file_name=f"{meta['name'] or 'portfolio'}.csv",
                       width="stretch", disabled=norm.empty)

# --------------------------------------------------------------------------
with tab_saved:
    for kind in pf.KINDS:
        names = pf.list_saved(kind)
        st.markdown(f"#### {KIND_LABEL[kind]} ({len(names)})")
        if not names:
            st.caption("None saved yet.")
            continue
        for n in names:
            h, payload = pf.load_portfolio(kind, n)
            c1, c2, c3, c4, c5 = st.columns([3, 1.6, 1, 1, 1])
            c1.markdown(f"**{n}**  \n<span class='jse-pill'>{len(h)} holdings</span>"
                        f"<span class='jse-pill'>saved {payload.get('saved_at', '')[:16]}</span>", unsafe_allow_html=True)
            c2.caption(payload.get("notes", "")[:120])
            if c3.button("Edit", key=f"ed_{kind}_{n}", width="stretch"):
                set_editor(h, kind=kind, name=n, notes=payload.get("notes", ""),
                           value_ccy=payload.get("meta", {}).get("value_ccy", "ZAR"))
                st.success("Loaded into the editor tab.")
            if c4.button("Copy → model", key=f"cp_{kind}_{n}", width="stretch"):
                pf.save_portfolio("model", f"{n}_model", h, f"Copied from {kind}:{n}")
                st.success(f"Created model portfolio {n}_model")
            if c5.button("🗑️ Delete", key=f"del_{kind}_{n}", width="stretch"):
                pf.delete_portfolio(kind, n)
                pui.working()[kind].pop(n, None)
                st.rerun()
    st.divider()
    up = st.file_uploader("Import a CSV / Excel file (same columns as the editor, or any layout the paste reader understands)",
                          type=["csv", "xlsx"])
    if up is not None:
        if up.name.endswith(".xlsx"):
            xl = pd.read_excel(up, header=None, dtype=str)
            txt = xl.fillna("").to_csv(sep="\t", index=False, header=False)
        else:
            txt = up.getvalue().decode(errors="ignore")
        parsed = pf.parse_paste(txt)
        if parsed is not None:
            h = pf.build_holdings(parsed, parsed.mapping, instruments)
            st.dataframe(h, hide_index=True, width="stretch")
            if st.button("Send imported file to editor"):
                set_editor(h, name=up.name.rsplit(".", 1)[0])
                st.success("Loaded into the editor tab.")
