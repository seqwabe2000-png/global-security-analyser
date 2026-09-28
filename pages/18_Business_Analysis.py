import streamlit as st

from src import business_analysis as ba
from src import universe as uni
from src.common import bootstrap

bootstrap("Business Analysis", "🏢")

st.title("🏢 Business Analysis")
st.caption(
    "Builds a deep, 28-question research prompt for any publicly listed company, anywhere -- business "
    "model, financials, valuation, moat, options market, credit, and more. The prompt automatically "
    "points the research at the right regulatory reporting venue for the company's market (SEC filings "
    "for the US, SENS for the JSE, RNS for the LSE, etc.). This tab doesn't run the research itself; it "
    "hands you the finished prompt to paste into your own Claude.ai chat (free plan works fine), which "
    "does the live web research and can hand you back a downloadable Word document -- no API key, no "
    "cost, nothing to configure."
)

# --------------------------------------------------------------------------
# Company selection
# --------------------------------------------------------------------------
instruments = uni.load_instruments()
equities = instruments[instruments["asset_class"] == "Equity"]
label_to_row = {f"{r['symbol']} — {r['name']} ({r['market']})": r for _, r in equities.iterrows()}

c1, c2 = st.columns([2, 2])
with c1:
    picked = st.selectbox(
        "Pick a company from the universe (optional)",
        options=["(type a company name/ticker below instead)"] + sorted(label_to_row.keys()),
    )
with c2:
    picked_row = label_to_row.get(picked)
    default_company = picked_row["name"] if picked_row is not None else ""
    company = st.text_input(
        "Company name / ticker to analyze",
        value=default_company,
        placeholder="e.g. Capitec Bank Holdings, or any listed company worldwide",
    )

if company.strip():
    market = picked_row["market"] if (picked_row is not None and company.strip() == picked_row["name"]) else None
    prompt = ba.build_prompt(company.strip(), market=market)

    st.subheader("Your research prompt")
    st.caption("Click the copy icon in the top-right corner of the box below.")
    st.code(prompt, language=None, wrap_lines=True)

    b1, b2 = st.columns([1, 3])
    with b1:
        st.link_button("Open Claude.ai ↗", "https://claude.ai/new", width="stretch")
    with b2:
        st.caption(
            "Paste the copied prompt into a new chat there and send it. It'll take a couple of "
            "minutes since it's doing real research with several web searches -- that's normal."
        )
else:
    st.info("Pick a stock above, or type a company name/ticker, to generate its research prompt.")
