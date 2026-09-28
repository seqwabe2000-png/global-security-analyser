"""
Offline smoke test for the portfolio pages (20-25) using synthetic prices
(scripts/_fake_market.py), incl. a JSE cents/rands glitch and late-listed stocks.
Run: python3 scripts/smoke_test_portfolio.py
"""
import os
import sys
import traceback
from unittest import mock

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "scripts"))
from streamlit.testing.v1 import AppTest  # noqa: E402

from _fake_market import fake_bulk, fake_history  # noqa: E402

PAGES = ["20_Portfolio_Builder.py", "21_Live_Portfolio_Risk.py", "22_Portfolio_Modelling.py", "23_Watchlist.py",
         "24_Constituent_Analysis.py", "25_Risk_Formulas.py"]
PASTE = open(os.path.join(BASE, "data", "seed", "ee_portfolio_2026_08_27.tsv")).read()


def new(page):
    at = AppTest.from_file(os.path.join(BASE, "pages", page), default_timeout=120)
    at.session_state["authenticated"] = True
    at.session_state["username"] = "smoketest"
    return at


def check(at, label, results):
    if at.exception:
        results.append((label, "FAIL", str(at.exception[0].message)[:600] + "\n" + "\n".join(at.exception[0].stack_trace[-6:])))
    else:
        results.append((label, "OK", ""))


results = []
with mock.patch("src.data.get_history_bulk", side_effect=fake_bulk), \
     mock.patch("src.data.get_history", side_effect=lambda t, **k: fake_history(t)):
    for page in PAGES:
        try:
            at = new(page)
            at.run()
            check(at, page, results)
        except Exception as e:
            results.append((page, "ERROR", f"{e}\n{traceback.format_exc(limit=4)}"))

    # --- interactions -------------------------------------------------------
    try:
        at = new("20_Portfolio_Builder.py"); at.run()
        at.text_area(key="pf_paste_text").input(PASTE).run()
        check(at, "Builder: paste EE sheet", results)
        [b for b in at.button if "Send to editor" in b.label][0].click().run()
        check(at, "Builder: send to editor", results)
        [b for b in at.button if "Fill missing" in b.label][0].click().run()
        check(at, "Builder: fill tickers", results)
    except Exception as e:
        results.append(("Builder interactions", "ERROR", f"{e}\n{traceback.format_exc(limit=4)}"))

    try:
        at = new("21_Live_Portfolio_Risk.py"); at.run()
        for base in ("USD", "LOCAL"):
            at.radio(key="pf_base").set_value(base).run()
            check(at, f"Live: base={base}", results)
        for f in ("Daily", "Monthly"):
            at.radio(key="pf_freq").set_value(f).run()
            check(at, f"Live: freq={f}", results)
        at.radio(key="live_grp").set_value("category").run()
        check(at, "Live: group by category", results)
    except Exception as e:
        results.append(("Live interactions", "ERROR", f"{e}\n{traceback.format_exc(limit=4)}"))

    try:
        at = new("22_Portfolio_Modelling.py"); at.run()
        [b for b in at.button if b.label == "Create scenario"][0].click().run()
        check(at, "Model: create scenario", results)
        at.selectbox(key="sch_Scenario A").set_value("Equal risk contribution").run()
        [b for b in at.button if b.key == "apply_Scenario A"][0].click().run()
        check(at, "Model: apply ERC", results)
        at.selectbox(key="sch_Scenario A").set_value("Scale to target volatility (rest in cash)").run()
        [b for b in at.button if b.key == "apply_Scenario A"][0].click().run()
        check(at, "Model: target vol", results)
        [b for b in at.button if b.label == "Run optimiser"][0].click().run()
        check(at, "Model: optimiser", results)
        [b for b in at.button if "Create scenario" in b.label and b.label.startswith("➕")][0].click().run()
        check(at, "Model: scenario from optimiser", results)
        at.selectbox(key="st_w").set_value(list(at.selectbox(key="st_w").options)[2]).run()
        check(at, "Model: stress detail", results)
    except Exception as e:
        results.append(("Model interactions", "ERROR", f"{e}\n{traceback.format_exc(limit=4)}"))

    try:
        at = new("24_Constituent_Analysis.py"); at.run()
        opts = at.multiselect(key="ca_sel").options
        at.multiselect(key="ca_sel").set_value([o for o in opts][:4]).run()
        check(at, "Constituent: multi", results)
        at.radio(key="ca_kind").set_value("watchlist").run()
        check(at, "Constituent: watchlist source", results)
    except Exception as e:
        results.append(("Constituent interactions", "ERROR", f"{e}\n{traceback.format_exc(limit=4)}"))

n_fail = 0
for name, status, detail in results:
    n_fail += status != "OK"
    print(f"{name:40s} {status:6s} {detail}")
print(f"{len(results) - n_fail}/{len(results)} checks passed")
sys.exit(1 if n_fail else 0)
