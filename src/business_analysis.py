"""
Business Analysis tab: builds a deep-research prompt (28 questions covering
business model, financials, valuation, moat, options market, credit, etc.)
for a given company, listed on any market -- its own regulatory reporting
venue (SEC filings, JSE/SENS, LSE/RNS, etc.) is filled in based on the
company's primary market. The app itself doesn't run this prompt -- it
hands you the finished text to paste into your own Claude.ai chat (or
another AI assistant with web search), which does the actual research and
can produce the downloadable Word document the prompt asks for. That keeps
this tab free to run: no API key, no billing, no extra dependencies.
"""
import datetime as _dt

# Market -> (primary reporting venue description, regulatory news-feed name)
MARKET_FILING_NOTES = {
    "South Africa": ("Integrated Annual Reports, interim/half-year results, and SENS announcements", "SENS (the JSE's News Service)"),
    "United States": ("10-K/10-Q/8-K filings on SEC EDGAR, earnings releases, and investor presentations", "8-K filings and press releases"),
    "United Kingdom": ("Annual Reports, interim results, and RNS announcements", "RNS (Regulatory News Service)"),
    "Germany": ("Annual/interim reports and ad-hoc disclosures (Ad-hoc-Mitteilungen)", "ad-hoc disclosures"),
    "Japan": ("Annual securities reports (Yuho) and Tokyo Stock Exchange (TDnet) disclosures", "TDnet disclosures"),
    "Canada": ("Annual/interim filings on SEDAR+ and press releases", "SEDAR+ filings"),
    "Australia": ("Annual/interim reports and ASX announcements", "ASX announcements"),
    "India": ("Annual reports and BSE/NSE stock-exchange filings", "BSE/NSE filings"),
    "Brazil": ("Annual/interim reports (via CVM) and B3 disclosures", "B3/CVM disclosures"),
    "China/Hong Kong": ("Annual/interim reports and HKEX announcements", "HKEX announcements"),
}
DEFAULT_FILING_NOTE = ("annual/interim reports and investor presentations", "regulatory announcements")

PROMPT_TEMPLATE = """\
# BUSINESS ANALYSIS v2.6 (multi-market)

You are an expert financial analyst specializing in business model analysis \
of publicly listed companies, using their own reporting ({filing_docs}) as \
the primary source, plus reputable market-data sources for anything those \
documents don't cover (consensus estimates, options market data, peer \
comparisons, credit instruments, recent news). Please use web search to \
find current information -- don't rely only on what you already know, \
since prices, estimates and news change constantly.

Today's date is {today}. The company to analyze is: **{company}**.

If this company is dual-listed (e.g. also trades on another exchange with \
its own regulatory filings, such as a US SEC 10-K/10-Q/20-F, JSE/SENS, or \
LSE/RNS), use those filings too wherever they add information the primary \
listing's reporting doesn't cover.

## DATA TO GATHER (in this priority order)
1. The company's most recent interim / half-year (HY) results announcement \
or trading statement for the current financial year.
2. The company's most recent Integrated Annual Report / Annual Financial \
Statements (AFS) -- for the full business model, segments, and risk \
disclosures.
3. If the current-year interim results aren't out yet, say so explicitly \
and use the most recent regulatory announcement or investor presentation \
instead.
4. Recent {regulatory_feed} for anything not yet in a formal report -- \
guidance updates, corporate actions, trading statements.

Before writing the report, state which documents you actually found and \
used (e.g. "Using [Company]'s FY2026 Integrated Annual Report and HY2027 \
results announcement dated ...").

## THE 28 QUESTIONS
Answer each of these in plain English (aim for a smart, non-specialist \
reader), with a citation for every factual claim, concise but not overly \
brief:

1. What does the company do? Include a short excerpt from its own annual \
report describing its business.
2. What is the sector, industry and sub-industry the company operates in \
(GICS classification), and what is its market cap?
3. How does it make money? List revenue streams/segments from most to \
least important, with % breakdown.
4. Who are its customers? (Individuals, SMBs, enterprises, governments, etc.)
5. Where does it operate? Key geographies with % breakdown if it operates \
in more than one.
6. How often do customers buy? Recurring vs. one-time, contracts, \
retention data.
7. Can it raise prices? Evidence from margins, pricing commentary, risk \
factors.
8. What happens in a recession? Cyclicality, past performance, management \
warnings.
9. What are the biggest business risks, and what is the company's guidance \
on future earnings?
10. What are the consensus estimates for EPS, earnings growth, and revenue \
growth for the current year, next year, and the year after that? (Use \
sources like Yahoo Finance, INET BFA, Moneyweb, Sharenet, Koyfin, \
investing.com.)
11. Why is the company expected to grow at those rates? Catalysts for \
growth over 3-6 months, 6-12 months, and 12-24 months and longer, with \
qualitative evidence from recent reporting.
12. What are the most important KPIs (profits and otherwise) that \
management and the market focus on?
13. What are the most important industry-specific KPIs, and how does the \
company measure on them?
14. What are the industry's expected growth rates, and why (headwinds/ \
tailwinds)?
15. What is the forward-looking valuation for the company (P/E, EPS \
growth, revenue growth, PEG, P/B), and why is the market pricing it there \
relative to its sector?
16. Compare the company to its sector peers: valuation metrics, revenue/ \
earnings estimates, and qualitative evidence for each peer's expected \
growth rate.
17. Does the company have a moat? What type (intangible assets, switching \
costs, network effect, cost advantage, efficient scale) and how strong -- \
compared with sector peers?
18. What is the company doing wrong, and what is it doing right?
19. What is the current price target for the stock from its current \
trading level, including expected % move and holding period?
20. What is the latest news flow on this company (announcements, analyst \
rating changes, M&A activity)? Keep it to news no more than 6 months old \
unless something older is still critical.
21. What is the options market pricing for this stock, short-dated to \
longer-dated? Implied volatility, and which strikes have high open \
interest? (If this stock has no listed options market, say so explicitly \
rather than guessing.)
22. What do the historical descriptive statistics / measures of centrality \
look like (historical volatility, return distribution)? Use 2y, 5y, 10y, \
and full-history lookbacks.
23. Does the company have public debt, fixed income instruments, or CDS \
outstanding? If so: current yields across maturities, market prices, and \
market sentiment (premium/discount and why).
24. What is the company's cash flow generation ability and trend? Compute \
FCF/Sales, FCF/NI, OCF/Sales, OCF/NI over a 5-year lookback.
25. What are the company's revenue and earnings growth trends over the \
last 5 years?
26. Is there any expected cash outflow that could affect future cash flow \
(capex plans, debt maturities, litigation, etc.)?
27. What is the company's financial health? Liquidity and solvency metrics \
over a 5-year trend.
28. Are there any announced or planned corporate events (M&A, buybacks, \
preference share issuance, stock splits, etc.)?

## OUTPUT FORMAT
Write the full report in clean Markdown (do not wrap it in a code block). \
Structure:

- A header: `# Business Analysis: [Company Name] ([Ticker])`
- Links (if found) to: the Investor Relations site, the latest investor \
presentation, the latest interim/HY results, the latest Annual Report, and \
the date of the next scheduled results release.
- One `###`-level subsection per question above, numbered, each with a \
short descriptive title.
- Use bullet points for revenue/segment and geographic breakdowns, with \
percentages where available.
- A short "What's going right / What's going wrong" subsection with two \
bullet lists.
- A closing "Sources" section, numbered, one line per source used.
- When you're done, please also create a downloadable Word document with \
the full report.

## GUARDRAILS
- Plain-English, no unexplained jargon.
- Every factual claim needs a citation.
- Prioritize the company's own reporting first; use third-party sources \
for anything the company's own documents don't cover (consensus estimates, \
options data, peer comparisons, credit instruments).
- If something genuinely can't be found (e.g. no listed options market, no \
public debt), say so plainly instead of guessing or omitting the section.
- Keep answers concise but informative -- this should read like a strong \
sell-side initiation note, not a wall of text.
"""


def build_prompt(company: str, market: str = None) -> str:
    today = _dt.date.today().strftime("%Y-%m-%d")
    filing_docs, regulatory_feed = MARKET_FILING_NOTES.get(market, DEFAULT_FILING_NOTE)
    return PROMPT_TEMPLATE.format(
        company=company, today=today, filing_docs=filing_docs, regulatory_feed=regulatory_feed,
    )
