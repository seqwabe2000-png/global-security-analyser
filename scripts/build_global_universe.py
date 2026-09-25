"""
Build the GLOBAL instrument universe used by the Global Security Analyser.

This is the multi-asset-class, multi-market successor to
`scripts/build_universe.py` (which only ever built the JSE equity list).
Run this any time you edit one of the curated lists below, or after editing
`data/jse_universe.csv`/`data/jse_sector_map.csv` (still the source for the
South African equity slice).

Output: data/universe/instruments.csv -- one row per tradable instrument,
every asset class, every market, with a single consistent schema:

    asset_class        Equity | Crypto | Commodity | Currency | Bond/Rate
    market             "South Africa", "United States", "Global", ...
    symbol             short code, no exchange suffix (e.g. "AAPL", "BTC")
    yf_ticker          the actual Yahoo Finance ticker to fetch
    name               display name
    gics_sector        sector for equities; a comparable *category* grouping
                        for every other asset class (crypto narrative, e.g.
                        "Layer 1"; commodity group, e.g. "Energy"; "Major FX"
                        / "EM FX" for currencies; "Government Yields" /
                        "Government Bonds" / "Corporate Bonds" for rates).
                        Kept as "gics_sector" (not renamed to "category") so
                        every existing sector-grouping/filter/breadth
                        function in src/ keeps working unmodified across
                        every asset class -- the UI just labels the control
                        "Sector / Category" instead of "GICS Sector".
    industry           finer sub-grouping, same idea as gics_sector.
    currency           the currency the instrument is quoted in.
    market_cap_tier    Mega/Large/Mid/Small/Micro Cap -- assessed *relative
                        to that instrument's own market* (a JSE "Mega Cap"
                        and a US "Mega Cap" are not the same absolute size;
                        see README). "--" where the concept doesn't apply.
    market_cap_usd_bn  rough order-of-magnitude market cap in USD billions,
                        for sorting/"top N" features only. For equities this
                        is a best-effort approximation from general
                        knowledge (this build environment has no live route
                        to Yahoo Finance or any market-data API -- see
                        README's "How the data works" for the same caveat
                        the original JSE build carried) and MUST be treated
                        as indicative, not authoritative. Blank for
                        commodities/currencies/rates, where "market cap"
                        isn't a meaningful concept.

LIVE SCREENER (preferred) + CURATED FALLBACK (always available)
-----------------------------------------------------------------
For every equity market, this script first tries to pull a much larger,
live top-N-by-market-cap list straight from Yahoo Finance's own screener API
(`yfinance.screen()` + `EquityQuery('eq', ['region', <code>])`, which is the
same mechanism behind finance.yahoo.com/research-hub/screener/ -- Yahoo
publicly documents 10,000+ listings across 100+ exchanges and includes
region codes for all 10 markets this app tracks, see EQUITY_SCREENER_EQ_MAP
bundled in the yfinance package itself). Mutual funds use the same
mechanism via `FundQuery` and several of yfinance's predefined fund
screens. If the live call fails (no internet -- true of this build
sandbox -- or Yahoo changes something) or returns too few usable rows, it
falls back to the hand-curated list below for that market, so the app
always has a working universe out of the box, live internet or not.

CURATION NOTE (read before trusting the fallback equity lists below):
outside of South Africa (data/jse_universe.csv, ~259 names sourced from a
JSE screener), the fallback equity lists below are hand-curated lists of
well-known, liquid, large/mid-cap names per market -- not a live-scraped,
complete index membership list (e.g. the fallback "US Equities" list is a
representative ~120 names spanning all 11 GICS sectors, not the full
500-odd S&P 500 constituents). This keeps the app honest about coverage
even when running fully offline. Treat every list here as editable: add
rows, rerun this script. Sector/industry classification and market-cap
figures in the fallback lists are this author's general knowledge as of
Sept 2026, not a licensed classification feed -- once the live screener
path is working on your machine, it supersedes these for that market.
"""
import os
import sys
import warnings

import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, "data")
UNIVERSE_DIR = os.path.join(DATA_DIR, "universe")
os.makedirs(UNIVERSE_DIR, exist_ok=True)

COLUMNS = [
    "asset_class", "market", "symbol", "yf_ticker", "name",
    "gics_sector", "industry", "currency", "market_cap_tier", "market_cap_usd_bn",
]

# --------------------------------------------------------------------------
# Live screener support (Yahoo Finance's own screener API via yfinance).
# Every function here fails soft: on any error, or on too few usable
# results, it returns [] / None and the caller falls back to the curated
# list -- never raises, never blocks the offline build.
# --------------------------------------------------------------------------
MIN_LIVE_ROWS = 15  # below this, prefer the curated fallback for that market

# Yahoo's own EquityQuery region codes (from yfinance's bundled
# EQUITY_SCREENER_EQ_MAP -- these are real, documented codes, not guesses;
# this dict does NOT require network access to build, only the fetch itself
# does) for the 10 equity markets this app tracks.
REGION_CODES = {
    "South Africa": "za", "United States": "us", "United Kingdom": "gb",
    "Germany": "de", "Japan": "jp", "Canada": "ca", "Australia": "au",
    "India": "in", "Brazil": "br", "China/Hong Kong": "hk",
}

# Yahoo/Morningstar-style sector names (what the screener returns) -> this
# app's GICS-11 naming, so live and curated rows group identically.
YAHOO_SECTOR_TO_GICS = {
    "Technology": "Information Technology",
    "Financial Services": "Financials",
    "Healthcare": "Health Care",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Communication Services": "Communication Services",
    "Industrials": "Industrials",
    "Energy": "Energy",
    "Utilities": "Utilities",
    "Real Estate": "Real Estate",
    "Basic Materials": "Materials",
}

# Rough, static FX-to-USD rates, used only to convert a live screener's
# local-currency market cap into the same approximate USD-billions scale
# used everywhere else in this app (see market_cap_usd_bn above -- already
# an indicative figure, not authoritative). Update these occasionally;
# they don't need to be exact.
FX_PER_USD = {
    "USD": 1.0, "ZAR": 18.5, "GBP": 0.79, "EUR": 0.92, "JPY": 152.0,
    "CAD": 1.38, "AUD": 1.52, "INR": 84.0, "BRL": 5.4, "HKD": 7.8, "CNY": 7.1,
}


def _try_import_yfinance():
    try:
        import yfinance as yf
        return yf
    except ImportError:
        return None


def fetch_live_equities(market: str, target_count: int = 200):
    """Live top-N-by-market-cap equities for one market via Yahoo's
    screener API. Returns a list of row dicts (this module's COLUMNS
    shape) on success, or [] on any failure/insufficient data -- the
    caller falls back to the curated list in that case."""
    yf = _try_import_yfinance()
    region = REGION_CODES.get(market)
    if yf is None or region is None:
        return []
    try:
        query = yf.EquityQuery("eq", ["region", region])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            resp = yf.screen(query, count=min(target_count, 250), sortField="intradaymarketcap", sortAsc=False)
        quotes = resp.get("quotes", []) if isinstance(resp, dict) else []
    except Exception as e:
        print(f"[build_global_universe] live screener failed for {market} ({region}): {e}", file=sys.stderr)
        return []

    rows = []
    for q in quotes:
        symbol = q.get("symbol")
        name = q.get("longName") or q.get("shortName") or symbol
        if not symbol or not name:
            continue
        currency = q.get("currency", "USD")
        cap_local = q.get("marketCap") or q.get("intradaymarketcap")
        cap_usd_bn = None
        if cap_local:
            fx = FX_PER_USD.get(currency, 1.0)
            cap_usd_bn = round((cap_local / fx) / 1e9, 2)
        gics_sector = YAHOO_SECTOR_TO_GICS.get(q.get("sector"), q.get("sector") or "Diversified")
        rows.append({
            "asset_class": "Equity",
            "market": market,
            "symbol": symbol.split(".")[0],
            "yf_ticker": symbol,
            "name": name,
            "gics_sector": gics_sector,
            "industry": q.get("industry") or gics_sector,
            "currency": currency,
            "market_cap_tier": _tier(cap_usd_bn),
            "market_cap_usd_bn": cap_usd_bn,
        })
    return rows if len(rows) >= MIN_LIVE_ROWS else []


# Several of yfinance's predefined fund screens, merged and deduped, to
# give the Mutual Funds asset class some category diversity without
# hand-curating individual fund names (Yahoo doesn't expose a broad
# region-based FundQuery the way it does for equities).
FUND_PREDEFINED_QUERIES = [
    "top_mutual_funds", "solid_large_growth_funds", "solid_midcap_growth_funds",
    "conservative_foreign_funds", "portfolio_anchors", "high_yield_bond",
]

# Fallback mutual fund list (well-known US funds), used if the live
# predefined screens can't be reached.
MUTUAL_FUNDS_FALLBACK = [
    ("VFIAX", "VFIAX", "Vanguard 500 Index Fund Admiral Shares", "Large Blend", "Index Fund", None),
    ("FXAIX", "FXAIX", "Fidelity 500 Index Fund", "Large Blend", "Index Fund", None),
    ("VTSAX", "VTSAX", "Vanguard Total Stock Market Index Fund Admiral", "Total Market", "Index Fund", None),
    ("SWPPX", "SWPPX", "Schwab S&P 500 Index Fund", "Large Blend", "Index Fund", None),
    ("VBTLX", "VBTLX", "Vanguard Total Bond Market Index Fund Admiral", "Intermediate Bond", "Bond Fund", None),
    ("VTIAX", "VTIAX", "Vanguard Total International Stock Index Fund", "Foreign Large Blend", "Index Fund", None),
    ("VWELX", "VWELX", "Vanguard Wellington Fund Investor Shares", "Allocation", "Balanced Fund", None),
    ("FCNTX", "FCNTX", "Fidelity Contrafund", "Large Growth", "Actively Managed", None),
    ("DODGX", "DODGX", "Dodge & Cox Stock Fund", "Large Value", "Actively Managed", None),
    ("PTTRX", "PTTRX", "PIMCO Total Return Fund", "Intermediate Bond", "Bond Fund", None),
]


def fetch_live_funds(target_count: int = 80):
    """Live mutual fund list via several of Yahoo's predefined fund
    screens, merged and deduped. Returns [] on any failure/insufficient
    data -- caller falls back to MUTUAL_FUNDS_FALLBACK."""
    yf = _try_import_yfinance()
    if yf is None:
        return []
    seen = {}
    for q_name in FUND_PREDEFINED_QUERIES:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                resp = yf.screen(q_name, count=min(target_count, 100))
            quotes = resp.get("quotes", []) if isinstance(resp, dict) else []
        except Exception as e:
            print(f"[build_global_universe] live fund screen '{q_name}' failed: {e}", file=sys.stderr)
            continue
        for q in quotes:
            symbol = q.get("symbol")
            if not symbol or symbol in seen:
                continue
            seen[symbol] = {
                "asset_class": "Mutual Fund",
                "market": "United States",
                "symbol": symbol,
                "yf_ticker": symbol,
                "name": q.get("longName") or q.get("shortName") or symbol,
                "gics_sector": q.get("categoryName") or q_name.replace("_", " ").title(),
                "industry": q.get("categoryName") or "--",
                "currency": q.get("currency", "USD"),
                "market_cap_tier": "--",
                "market_cap_usd_bn": None,
            }
    return list(seen.values()) if len(seen) >= 10 else []


def _tier(cap):
    if cap is None:
        return "--"
    if cap >= 200:
        return "Mega Cap"
    if cap >= 50:
        return "Large Cap"
    if cap >= 10:
        return "Mid Cap"
    if cap >= 2:
        return "Small Cap"
    return "Micro Cap"


def _rows(asset_class, market, currency, items):
    """items: list of (symbol, yf_ticker, name, sector, industry, cap_usd_bn|None)"""
    out = []
    for symbol, yf_ticker, name, sector, industry, cap in items:
        out.append({
            "asset_class": asset_class,
            "market": market,
            "symbol": symbol,
            "yf_ticker": yf_ticker,
            "name": name,
            "gics_sector": sector,
            "industry": industry,
            "currency": currency,
            "market_cap_tier": _tier(cap) if asset_class == "Equity" else "--",
            "market_cap_usd_bn": cap,
        })
    return out


def _rows_per_currency(asset_class, market, items):
    """items: list of (symbol, yf_ticker, name, sector, industry, currency, cap_usd_bn|None)
    -- for asset classes (commodities/currencies/bonds) where each row can
    carry its own quote currency rather than one currency for the whole
    group."""
    out = []
    for symbol, yf_ticker, name, sector, industry, currency, cap in items:
        out.append({
            "asset_class": asset_class,
            "market": market,
            "symbol": symbol,
            "yf_ticker": yf_ticker,
            "name": name,
            "gics_sector": sector,
            "industry": industry,
            "currency": currency,
            "market_cap_tier": "--",
            "market_cap_usd_bn": cap,
        })
    return out


# ==========================================================================
# 1. South Africa (JSE) -- reuse the existing hand-built universe as-is.
# ==========================================================================
def load_jse_rows():
    df = pd.read_csv(os.path.join(DATA_DIR, "jse_universe.csv"))
    df["market_cap_zar"] = pd.to_numeric(df["market_cap_zar"], errors="coerce")
    ZAR_PER_USD = 18.5  # approximate, for cross-market ordering only
    rows = []
    for _, r in df.iterrows():
        cap_usd_bn = None
        if pd.notna(r["market_cap_zar"]):
            cap_usd_bn = round(r["market_cap_zar"] / ZAR_PER_USD / 1e9, 2)
        rows.append({
            "asset_class": "Equity",
            "market": "South Africa",
            "symbol": r["symbol"],
            "yf_ticker": r["yf_ticker"],
            "name": r["name"],
            "gics_sector": r["gics_sector"],
            "industry": r["industry"],
            "currency": "ZAR",
            "market_cap_tier": r["market_cap_tier"],  # keep original JSE-relative tiers
            "market_cap_usd_bn": cap_usd_bn,
        })
    return rows


# ==========================================================================
# 2. United States -- ~120 names spanning all 11 GICS sectors.
# ==========================================================================
US_EQUITIES = [
    ("AAPL", "AAPL", "Apple Inc.", "Information Technology", "Technology Hardware", 3400),
    ("MSFT", "MSFT", "Microsoft Corporation", "Information Technology", "Systems Software", 3200),
    ("NVDA", "NVDA", "NVIDIA Corporation", "Information Technology", "Semiconductors", 3600),
    ("GOOGL", "GOOGL", "Alphabet Inc.", "Communication Services", "Interactive Media", 2400),
    ("AMZN", "AMZN", "Amazon.com Inc.", "Consumer Discretionary", "Internet Retail", 2300),
    ("META", "META", "Meta Platforms Inc.", "Communication Services", "Interactive Media", 1600),
    ("AVGO", "AVGO", "Broadcom Inc.", "Information Technology", "Semiconductors", 1300),
    ("TSLA", "TSLA", "Tesla Inc.", "Consumer Discretionary", "Automobiles", 1100),
    ("ORCL", "ORCL", "Oracle Corporation", "Information Technology", "Software", 550),
    ("CRM", "CRM", "Salesforce Inc.", "Information Technology", "Software", 290),
    ("ADBE", "ADBE", "Adobe Inc.", "Information Technology", "Software", 220),
    ("AMD", "AMD", "Advanced Micro Devices", "Information Technology", "Semiconductors", 260),
    ("CSCO", "CSCO", "Cisco Systems Inc.", "Information Technology", "Communications Equipment", 250),
    ("IBM", "IBM", "International Business Machines", "Information Technology", "IT Services", 230),
    ("QCOM", "QCOM", "Qualcomm Inc.", "Information Technology", "Semiconductors", 190),
    ("TXN", "TXN", "Texas Instruments", "Information Technology", "Semiconductors", 180),
    ("INTC", "INTC", "Intel Corporation", "Information Technology", "Semiconductors", 110),
    ("NFLX", "NFLX", "Netflix Inc.", "Communication Services", "Entertainment", 400),
    ("DIS", "DIS", "Walt Disney Company", "Communication Services", "Entertainment", 210),
    ("CMCSA", "CMCSA", "Comcast Corporation", "Communication Services", "Media", 150),
    ("TMUS", "TMUS", "T-Mobile US Inc.", "Communication Services", "Wireless Telecom", 260),
    ("VZ", "VZ", "Verizon Communications", "Communication Services", "Telecom Services", 180),
    ("T", "T", "AT&T Inc.", "Communication Services", "Telecom Services", 190),
    ("JPM", "JPM", "JPMorgan Chase & Co.", "Financials", "Diversified Banks", 700),
    ("BAC", "BAC", "Bank of America Corp.", "Financials", "Diversified Banks", 330),
    ("WFC", "WFC", "Wells Fargo & Company", "Financials", "Diversified Banks", 240),
    ("GS", "GS", "Goldman Sachs Group", "Financials", "Investment Banking", 220),
    ("MS", "MS", "Morgan Stanley", "Financials", "Investment Banking", 210),
    ("C", "C", "Citigroup Inc.", "Financials", "Diversified Banks", 160),
    ("V", "V", "Visa Inc.", "Financials", "Payments", 650),
    ("MA", "MA", "Mastercard Inc.", "Financials", "Payments", 480),
    ("AXP", "AXP", "American Express Co.", "Financials", "Consumer Finance", 210),
    ("BLK", "BLK", "BlackRock Inc.", "Financials", "Asset Management", 150),
    ("SCHW", "SCHW", "Charles Schwab Corp.", "Financials", "Capital Markets", 160),
    ("BRK-B", "BRK-B", "Berkshire Hathaway Inc.", "Financials", "Multi-line Insurance", 1050),
    ("PGR", "PGR", "Progressive Corporation", "Financials", "Property & Casualty Insurance", 150),
    ("UNH", "UNH", "UnitedHealth Group Inc.", "Health Care", "Managed Health Care", 320),
    ("JNJ", "JNJ", "Johnson & Johnson", "Health Care", "Pharmaceuticals", 400),
    ("LLY", "LLY", "Eli Lilly and Company", "Health Care", "Pharmaceuticals", 800),
    ("ABBV", "ABBV", "AbbVie Inc.", "Health Care", "Biotechnology", 380),
    ("PFE", "PFE", "Pfizer Inc.", "Health Care", "Pharmaceuticals", 150),
    ("MRK", "MRK", "Merck & Co. Inc.", "Health Care", "Pharmaceuticals", 260),
    ("ABT", "ABT", "Abbott Laboratories", "Health Care", "Health Care Equipment", 220),
    ("TMO", "TMO", "Thermo Fisher Scientific", "Health Care", "Life Sciences Tools", 210),
    ("DHR", "DHR", "Danaher Corporation", "Health Care", "Life Sciences Tools", 170),
    ("AMGN", "AMGN", "Amgen Inc.", "Health Care", "Biotechnology", 160),
    ("ISRG", "ISRG", "Intuitive Surgical", "Health Care", "Health Care Equipment", 190),
    ("PG", "PG", "Procter & Gamble Co.", "Consumer Staples", "Household Products", 400),
    ("KO", "KO", "Coca-Cola Company", "Consumer Staples", "Soft Drinks", 300),
    ("PEP", "PEP", "PepsiCo Inc.", "Consumer Staples", "Soft Drinks", 220),
    ("COST", "COST", "Costco Wholesale Corp.", "Consumer Staples", "Food Retail", 450),
    ("WMT", "WMT", "Walmart Inc.", "Consumer Staples", "Food Retail", 800),
    ("PM", "PM", "Philip Morris International", "Consumer Staples", "Tobacco", 250),
    ("MO", "MO", "Altria Group Inc.", "Consumer Staples", "Tobacco", 90),
    ("MDLZ", "MDLZ", "Mondelez International", "Consumer Staples", "Packaged Foods", 90),
    ("CL", "CL", "Colgate-Palmolive Co.", "Consumer Staples", "Household Products", 75),
    ("HD", "HD", "Home Depot Inc.", "Consumer Discretionary", "Home Improvement Retail", 400),
    ("LOW", "LOW", "Lowe's Companies Inc.", "Consumer Discretionary", "Home Improvement Retail", 140),
    ("MCD", "MCD", "McDonald's Corporation", "Consumer Discretionary", "Restaurants", 220),
    ("SBUX", "SBUX", "Starbucks Corporation", "Consumer Discretionary", "Restaurants", 110),
    ("NKE", "NKE", "Nike Inc.", "Consumer Discretionary", "Apparel", 100),
    ("TJX", "TJX", "TJX Companies Inc.", "Consumer Discretionary", "Apparel Retail", 140),
    ("BKNG", "BKNG", "Booking Holdings Inc.", "Consumer Discretionary", "Travel Services", 170),
    ("XOM", "XOM", "Exxon Mobil Corporation", "Energy", "Integrated Oil & Gas", 500),
    ("CVX", "CVX", "Chevron Corporation", "Energy", "Integrated Oil & Gas", 290),
    ("COP", "COP", "ConocoPhillips", "Energy", "Oil & Gas E&P", 140),
    ("SLB", "SLB", "Schlumberger (SLB)", "Energy", "Oil & Gas Equipment", 60),
    ("EOG", "EOG", "EOG Resources Inc.", "Energy", "Oil & Gas E&P", 75),
    ("GE", "GE", "GE Aerospace", "Industrials", "Aerospace & Defense", 260),
    ("RTX", "RTX", "RTX Corporation", "Industrials", "Aerospace & Defense", 180),
    ("BA", "BA", "Boeing Company", "Industrials", "Aerospace & Defense", 120),
    ("HON", "HON", "Honeywell International", "Industrials", "Industrial Conglomerates", 140),
    ("CAT", "CAT", "Caterpillar Inc.", "Industrials", "Construction Machinery", 190),
    ("DE", "DE", "Deere & Company", "Industrials", "Agricultural Machinery", 130),
    ("UPS", "UPS", "United Parcel Service", "Industrials", "Air Freight & Logistics", 90),
    ("UNP", "UNP", "Union Pacific Corp.", "Industrials", "Rail Transportation", 150),
    ("LMT", "LMT", "Lockheed Martin Corp.", "Industrials", "Aerospace & Defense", 120),
    ("LIN", "LIN", "Linde plc", "Materials", "Industrial Gases", 220),
    ("SHW", "SHW", "Sherwin-Williams Co.", "Materials", "Specialty Chemicals", 90),
    ("FCX", "FCX", "Freeport-McMoRan Inc.", "Materials", "Copper", 65),
    ("NEM", "NEM", "Newmont Corporation", "Materials", "Gold Mining", 60),
    ("APD", "APD", "Air Products and Chemicals", "Materials", "Industrial Gases", 65),
    ("NEE", "NEE", "NextEra Energy Inc.", "Utilities", "Electric Utilities", 160),
    ("SO", "SO", "Southern Company", "Utilities", "Electric Utilities", 100),
    ("DUK", "DUK", "Duke Energy Corp.", "Utilities", "Electric Utilities", 95),
    ("AEP", "AEP", "American Electric Power", "Utilities", "Electric Utilities", 55),
    ("EXC", "EXC", "Exelon Corporation", "Utilities", "Electric Utilities", 45),
    ("PLD", "PLD", "Prologis Inc.", "Real Estate", "Industrial REITs", 110),
    ("AMT", "AMT", "American Tower Corp.", "Real Estate", "Specialized REITs", 100),
    ("EQIX", "EQIX", "Equinix Inc.", "Real Estate", "Specialized REITs", 90),
    ("SPG", "SPG", "Simon Property Group", "Real Estate", "Retail REITs", 65),
    ("O", "O", "Realty Income Corp.", "Real Estate", "Retail REITs", 50),
    ("PANW", "PANW", "Palo Alto Networks", "Information Technology", "Systems Software", 130),
    ("NOW", "NOW", "ServiceNow Inc.", "Information Technology", "Software", 210),
    ("INTU", "INTU", "Intuit Inc.", "Information Technology", "Software", 190),
    ("AMAT", "AMAT", "Applied Materials Inc.", "Information Technology", "Semiconductor Equipment", 170),
    ("MU", "MU", "Micron Technology Inc.", "Information Technology", "Semiconductors", 150),
    ("UBER", "UBER", "Uber Technologies Inc.", "Industrials", "Passenger Ground Transportation", 180),
    ("PYPL", "PYPL", "PayPal Holdings Inc.", "Financials", "Payments", 75),
    ("ADP", "ADP", "Automatic Data Processing", "Industrials", "Human Resource Services", 130),
    ("SPGI", "SPGI", "S&P Global Inc.", "Financials", "Financial Exchanges & Data", 160),
    ("ICE", "ICE", "Intercontinental Exchange", "Financials", "Financial Exchanges & Data", 100),
    ("CME", "CME", "CME Group Inc.", "Financials", "Financial Exchanges & Data", 90),
    ("ETN", "ETN", "Eaton Corporation plc", "Industrials", "Electrical Equipment", 140),
    ("EMR", "EMR", "Emerson Electric Co.", "Industrials", "Electrical Equipment", 75),
    ("ITW", "ITW", "Illinois Tool Works", "Industrials", "Industrial Machinery", 85),
    ("GD", "GD", "General Dynamics Corp.", "Industrials", "Aerospace & Defense", 85),
    ("NOC", "NOC", "Northrop Grumman Corp.", "Industrials", "Aerospace & Defense", 80),
    ("CB", "CB", "Chubb Limited", "Financials", "Property & Casualty Insurance", 115),
    ("MMC", "MMC", "Marsh McLennan", "Financials", "Insurance Brokers", 115),
    ("USB", "USB", "U.S. Bancorp", "Financials", "Regional Banks", 85),
    ("PNC", "PNC", "PNC Financial Services", "Financials", "Regional Banks", 80),
    ("CVS", "CVS", "CVS Health Corporation", "Health Care", "Health Care Services", 90),
    ("CI", "CI", "The Cigna Group", "Health Care", "Managed Health Care", 90),
    ("ELV", "ELV", "Elevance Health Inc.", "Health Care", "Managed Health Care", 100),
    ("SYK", "SYK", "Stryker Corporation", "Health Care", "Health Care Equipment", 150),
    ("BSX", "BSX", "Boston Scientific Corp.", "Health Care", "Health Care Equipment", 140),
    ("VRTX", "VRTX", "Vertex Pharmaceuticals", "Health Care", "Biotechnology", 130),
    ("REGN", "REGN", "Regeneron Pharmaceuticals", "Health Care", "Biotechnology", 90),
    ("GILD", "GILD", "Gilead Sciences Inc.", "Health Care", "Biotechnology", 130),
    ("F", "F", "Ford Motor Company", "Consumer Discretionary", "Automobiles", 45),
    ("GM", "GM", "General Motors Company", "Consumer Discretionary", "Automobiles", 55),
]

# The 11 SPDR Select Sector ETFs -- the *exact* instruments used for the
# US Sector Breadth page (matches the reference screenshot: sector ETF
# name/symbol/last/open/high/low/chg/chg%/vol table), plus SPY/QQQ as
# broad-market benchmarks.
US_SECTOR_ETFS = {
    "Technology Select Sector SPDR": "XLK",
    "Financial Select Sector SPDR": "XLF",
    "Health Care Select Sector SPDR": "XLV",
    "Consumer Discretionary Select Sector SPDR": "XLY",
    "Consumer Staples Select Sector SPDR": "XLP",
    "Energy Select Sector SPDR": "XLE",
    "Industrial Select Sector SPDR": "XLI",
    "Materials Select Sector SPDR": "XLB",
    "Utilities Select Sector SPDR": "XLU",
    "Real Estate Select Sector SPDR": "XLRE",
    "Communication Services Select Sector SPDR": "XLC",
}
US_BROAD_ETFS = {
    "SPDR S&P 500": "SPY",
    "Invesco QQQ Trust": "QQQ",
    "SPDR Dow Jones Industrial Average": "DIA",
    "iShares Russell 2000": "IWM",
}
# Map GICS sector name -> its SPDR ETF ticker, used to pair "real" sector
# ETF performance with "constructed" breadth computed from the constituent
# list above.
US_SECTOR_TO_ETF = {
    "Information Technology": "XLK", "Financials": "XLF", "Health Care": "XLV",
    "Consumer Discretionary": "XLY", "Consumer Staples": "XLP", "Energy": "XLE",
    "Industrials": "XLI", "Materials": "XLB", "Utilities": "XLU",
    "Real Estate": "XLRE", "Communication Services": "XLC",
}


# ==========================================================================
# 3. United Kingdom -- ~35 FTSE 100 names.
# ==========================================================================
UK_EQUITIES = [
    ("HSBA", "HSBA.L", "HSBC Holdings plc", "Financials", "Diversified Banks", 170),
    ("SHEL", "SHEL.L", "Shell plc", "Energy", "Integrated Oil & Gas", 220),
    ("AZN", "AZN.L", "AstraZeneca plc", "Health Care", "Pharmaceuticals", 240),
    ("BP", "BP.L", "BP plc", "Energy", "Integrated Oil & Gas", 90),
    ("ULVR", "ULVR.L", "Unilever plc", "Consumer Staples", "Household Products", 130),
    ("GSK", "GSK.L", "GSK plc", "Health Care", "Pharmaceuticals", 75),
    ("DGE", "DGE.L", "Diageo plc", "Consumer Staples", "Distillers & Vintners", 60),
    ("BATS", "BATS.L", "British American Tobacco plc", "Consumer Staples", "Tobacco", 85),
    ("RIO", "RIO.L", "Rio Tinto plc", "Materials", "Diversified Mining", 100),
    ("GLEN", "GLEN.L", "Glencore plc", "Materials", "Diversified Mining", 55),
    ("BARC", "BARC.L", "Barclays plc", "Financials", "Diversified Banks", 55),
    ("LLOY", "LLOY.L", "Lloyds Banking Group plc", "Financials", "Diversified Banks", 50),
    ("NWG", "NWG.L", "NatWest Group plc", "Financials", "Diversified Banks", 45),
    ("VOD", "VOD.L", "Vodafone Group plc", "Communication Services", "Wireless Telecom", 25),
    ("BT-A", "BT-A.L", "BT Group plc", "Communication Services", "Telecom Services", 18),
    ("TSCO", "TSCO.L", "Tesco plc", "Consumer Staples", "Food Retail", 30),
    ("NG", "NG.L", "National Grid plc", "Utilities", "Multi-Utilities", 55),
    ("SSE", "SSE.L", "SSE plc", "Utilities", "Electric Utilities", 25),
    ("REL", "REL.L", "RELX plc", "Industrials", "Research & Consulting", 90),
    ("RKT", "RKT.L", "Reckitt Benckiser Group plc", "Consumer Staples", "Household Products", 35),
    ("CPG", "CPG.L", "Compass Group plc", "Consumer Discretionary", "Restaurants", 55),
    ("RR", "RR.L", "Rolls-Royce Holdings plc", "Industrials", "Aerospace & Defense", 80),
    ("BA-L", "BA.L", "BAE Systems plc", "Industrials", "Aerospace & Defense", 65),
    ("PRU", "PRU.L", "Prudential plc", "Financials", "Life Insurance", 25),
    ("LGEN", "LGEN.L", "Legal & General Group plc", "Financials", "Life Insurance", 18),
    ("AV", "AV.L", "Aviva plc", "Financials", "Multi-line Insurance", 20),
    ("STAN", "STAN.L", "Standard Chartered plc", "Financials", "Diversified Banks", 30),
    ("AAL", "AAL.L", "Anglo American plc", "Materials", "Diversified Mining", 35),
    ("ANTO", "ANTO.L", "Antofagasta plc", "Materials", "Copper", 22),
    ("NXT", "NXT.L", "Next plc", "Consumer Discretionary", "Apparel Retail", 15),
    ("ABF", "ABF.L", "Associated British Foods plc", "Consumer Staples", "Packaged Foods", 22),
    ("EXPN", "EXPN.L", "Experian plc", "Industrials", "Research & Consulting", 40),
    ("HLMA", "HLMA.L", "Halma plc", "Industrials", "Electronic Equipment", 12),
    ("SN", "SN.L", "Smith & Nephew plc", "Health Care", "Health Care Equipment", 10),
    ("LSEG", "LSEG.L", "London Stock Exchange Group plc", "Financials", "Financial Exchanges & Data", 55),
]


# ==========================================================================
# 4. Germany -- ~35 DAX names.
# ==========================================================================
DE_EQUITIES = [
    ("SAP", "SAP.DE", "SAP SE", "Information Technology", "Software", 320),
    ("SIE", "SIE.DE", "Siemens AG", "Industrials", "Industrial Conglomerates", 160),
    ("ALV", "ALV.DE", "Allianz SE", "Financials", "Multi-line Insurance", 150),
    ("DTE", "DTE.DE", "Deutsche Telekom AG", "Communication Services", "Telecom Services", 140),
    ("MBG", "MBG.DE", "Mercedes-Benz Group AG", "Consumer Discretionary", "Automobiles", 60),
    ("BMW", "BMW.DE", "Bayerische Motoren Werke AG", "Consumer Discretionary", "Automobiles", 55),
    ("VOW3", "VOW3.DE", "Volkswagen AG", "Consumer Discretionary", "Automobiles", 55),
    ("BAS", "BAS.DE", "BASF SE", "Materials", "Diversified Chemicals", 45),
    ("BAYN", "BAYN.DE", "Bayer AG", "Health Care", "Pharmaceuticals", 30),
    ("DBK", "DBK.DE", "Deutsche Bank AG", "Financials", "Diversified Banks", 40),
    ("CBK", "CBK.DE", "Commerzbank AG", "Financials", "Diversified Banks", 20),
    ("MUV2", "MUV2.DE", "Munich Re", "Financials", "Reinsurance", 65),
    ("DB1", "DB1.DE", "Deutsche Boerse AG", "Financials", "Financial Exchanges & Data", 45),
    ("IFX", "IFX.DE", "Infineon Technologies AG", "Information Technology", "Semiconductors", 45),
    ("ADS", "ADS.DE", "Adidas AG", "Consumer Discretionary", "Apparel", 45),
    ("HEN3", "HEN3.DE", "Henkel AG & Co KGaA", "Consumer Staples", "Household Products", 22),
    ("BEI", "BEI.DE", "Beiersdorf AG", "Consumer Staples", "Personal Products", 30),
    ("FRE", "FRE.DE", "Fresenius SE & Co KGaA", "Health Care", "Health Care Services", 20),
    ("MRK-DE", "MRK.DE", "Merck KGaA", "Health Care", "Pharmaceuticals", 60),
    ("CON", "CON.DE", "Continental AG", "Consumer Discretionary", "Auto Parts", 8),
    ("DHL", "DHL.DE", "DHL Group", "Industrials", "Air Freight & Logistics", 45),
    ("HEI", "HEI.DE", "Heidelberg Materials AG", "Materials", "Construction Materials", 22),
    ("MTX", "MTX.DE", "MTU Aero Engines AG", "Industrials", "Aerospace & Defense", 25),
    ("RHM", "RHM.DE", "Rheinmetall AG", "Industrials", "Aerospace & Defense", 55),
    ("ZAL", "ZAL.DE", "Zalando SE", "Consumer Discretionary", "Internet Retail", 8),
    ("VNA", "VNA.DE", "Vonovia SE", "Real Estate", "Residential REITs", 25),
    ("SRT3", "SRT3.DE", "Sartorius AG", "Health Care", "Life Sciences Tools", 20),
    ("SY1", "SY1.DE", "Symrise AG", "Materials", "Specialty Chemicals", 15),
    ("BNR", "BNR.DE", "Brenntag SE", "Industrials", "Trading Companies", 8),
    ("HNR1", "HNR1.DE", "Hannover Rueck SE", "Financials", "Reinsurance", 35),
    ("QIA", "QIA.DE", "Qiagen NV", "Health Care", "Life Sciences Tools", 10),
    ("P911", "P911.DE", "Porsche AG", "Consumer Discretionary", "Automobiles", 20),
    ("EOAN", "EOAN.DE", "E.ON SE", "Utilities", "Multi-Utilities", 35),
    ("RWE", "RWE.DE", "RWE AG", "Utilities", "Electric Utilities", 25),
    ("AIR", "AIR.DE", "Airbus SE", "Industrials", "Aerospace & Defense", 150),
]


# ==========================================================================
# 5. Japan -- ~35 major TSE names.
# ==========================================================================
JP_EQUITIES = [
    ("7203", "7203.T", "Toyota Motor Corporation", "Consumer Discretionary", "Automobiles", 260),
    ("6758", "6758.T", "Sony Group Corporation", "Consumer Discretionary", "Consumer Electronics", 150),
    ("8306", "8306.T", "Mitsubishi UFJ Financial Group", "Financials", "Diversified Banks", 150),
    ("9984", "9984.T", "SoftBank Group Corp.", "Communication Services", "Telecom Services", 90),
    ("9434", "9434.T", "SoftBank Corp.", "Communication Services", "Wireless Telecom", 65),
    ("6861", "6861.T", "Keyence Corporation", "Information Technology", "Electronic Equipment", 130),
    ("7974", "7974.T", "Nintendo Co. Ltd.", "Communication Services", "Interactive Home Entertainment", 95),
    ("9983", "9983.T", "Fast Retailing Co. Ltd.", "Consumer Discretionary", "Apparel Retail", 95),
    ("8035", "8035.T", "Tokyo Electron Ltd.", "Information Technology", "Semiconductor Equipment", 130),
    ("6501", "6501.T", "Hitachi Ltd.", "Industrials", "Industrial Conglomerates", 130),
    ("7267", "7267.T", "Honda Motor Co. Ltd.", "Consumer Discretionary", "Automobiles", 55),
    ("7201", "7201.T", "Nissan Motor Co. Ltd.", "Consumer Discretionary", "Automobiles", 12),
    ("6752", "6752.T", "Panasonic Holdings Corp.", "Consumer Discretionary", "Consumer Electronics", 25),
    ("7751", "7751.T", "Canon Inc.", "Information Technology", "Technology Hardware", 40),
    ("5401", "5401.T", "Nippon Steel Corporation", "Materials", "Steel", 22),
    ("8058", "8058.T", "Mitsubishi Corporation", "Industrials", "Trading Companies", 90),
    ("8031", "8031.T", "Mitsui & Co. Ltd.", "Industrials", "Trading Companies", 65),
    ("8001", "8001.T", "Itochu Corporation", "Industrials", "Trading Companies", 85),
    ("9433", "9433.T", "KDDI Corporation", "Communication Services", "Wireless Telecom", 85),
    ("9432", "9432.T", "Nippon Telegraph and Telephone", "Communication Services", "Telecom Services", 90),
    ("4063", "4063.T", "Shin-Etsu Chemical Co.", "Materials", "Specialty Chemicals", 100),
    ("4568", "4568.T", "Daiichi Sankyo Co. Ltd.", "Health Care", "Pharmaceuticals", 90),
    ("4502", "4502.T", "Takeda Pharmaceutical Co.", "Health Care", "Pharmaceuticals", 55),
    ("6098", "6098.T", "Recruit Holdings Co. Ltd.", "Industrials", "Human Resource Services", 90),
    ("6902", "6902.T", "Denso Corporation", "Consumer Discretionary", "Auto Parts", 50),
    ("6981", "6981.T", "Murata Manufacturing Co.", "Information Technology", "Electronic Components", 45),
    ("5108", "5108.T", "Bridgestone Corporation", "Consumer Discretionary", "Auto Parts", 30),
    ("4452", "4452.T", "Kao Corporation", "Consumer Staples", "Personal Products", 25),
    ("3382", "3382.T", "Seven & I Holdings Co.", "Consumer Staples", "Food Retail", 35),
    ("8591", "8591.T", "ORIX Corporation", "Financials", "Diversified Financial Services", 30),
    ("8766", "8766.T", "Tokio Marine Holdings Inc.", "Financials", "Property & Casualty Insurance", 75),
    ("8725", "8725.T", "MS&AD Insurance Group", "Financials", "Property & Casualty Insurance", 30),
    ("6367", "6367.T", "Daikin Industries Ltd.", "Industrials", "Building Products", 45),
    ("6954", "6954.T", "Fanuc Corporation", "Industrials", "Industrial Machinery", 25),
    ("9020", "9020.T", "East Japan Railway Company", "Industrials", "Passenger Ground Transportation", 30),
]


# ==========================================================================
# 6. Canada -- ~28 major TSX names.
# ==========================================================================
CA_EQUITIES = [
    ("RY", "RY.TO", "Royal Bank of Canada", "Financials", "Diversified Banks", 200),
    ("TD", "TD.TO", "Toronto-Dominion Bank", "Financials", "Diversified Banks", 130),
    ("BNS", "BNS.TO", "Bank of Nova Scotia", "Financials", "Diversified Banks", 75),
    ("BMO", "BMO.TO", "Bank of Montreal", "Financials", "Diversified Banks", 90),
    ("CM", "CM.TO", "Canadian Imperial Bank of Commerce", "Financials", "Diversified Banks", 60),
    ("ENB", "ENB.TO", "Enbridge Inc.", "Energy", "Oil & Gas Storage & Transport", 110),
    ("TRP", "TRP.TO", "TC Energy Corporation", "Energy", "Oil & Gas Storage & Transport", 55),
    ("CNQ", "CNQ.TO", "Canadian Natural Resources", "Energy", "Oil & Gas E&P", 75),
    ("SU", "SU.TO", "Suncor Energy Inc.", "Energy", "Integrated Oil & Gas", 60),
    ("SHOP", "SHOP.TO", "Shopify Inc.", "Information Technology", "Software", 160),
    ("BN", "BN.TO", "Brookfield Corporation", "Financials", "Asset Management", 120),
    ("BAM", "BAM.TO", "Brookfield Asset Management", "Financials", "Asset Management", 25),
    ("CP", "CP.TO", "Canadian Pacific Kansas City", "Industrials", "Rail Transportation", 65),
    ("CNR", "CNR.TO", "Canadian National Railway", "Industrials", "Rail Transportation", 75),
    ("ABX", "ABX.TO", "Barrick Mining Corporation", "Materials", "Gold Mining", 35),
    ("MFC", "MFC.TO", "Manulife Financial Corp.", "Financials", "Life Insurance", 65),
    ("SLF", "SLF.TO", "Sun Life Financial Inc.", "Financials", "Life Insurance", 40),
    ("BCE", "BCE.TO", "BCE Inc.", "Communication Services", "Telecom Services", 25),
    ("T-CA", "T.TO", "TELUS Corporation", "Communication Services", "Telecom Services", 28),
    ("L", "L.TO", "Loblaw Companies Ltd.", "Consumer Staples", "Food Retail", 45),
    ("NTR", "NTR.TO", "Nutrien Ltd.", "Materials", "Fertilizers", 22),
    ("FNV", "FNV.TO", "Franco-Nevada Corporation", "Materials", "Gold Mining", 35),
    ("AEM", "AEM.TO", "Agnico Eagle Mines Ltd.", "Materials", "Gold Mining", 55),
    ("CSU", "CSU.TO", "Constellation Software Inc.", "Information Technology", "Software", 90),
    ("ATD", "ATD.TO", "Alimentation Couche-Tard", "Consumer Staples", "Food Retail", 55),
    ("WCN", "WCN.TO", "Waste Connections Inc.", "Industrials", "Environmental Services", 45),
    ("FFH", "FFH.TO", "Fairfax Financial Holdings", "Financials", "Property & Casualty Insurance", 45),
]


# ==========================================================================
# 7. Australia -- ~28 major ASX names.
# ==========================================================================
AU_EQUITIES = [
    ("BHP", "BHP.AX", "BHP Group Limited", "Materials", "Diversified Mining", 150),
    ("CBA", "CBA.AX", "Commonwealth Bank of Australia", "Financials", "Diversified Banks", 190),
    ("CSL", "CSL.AX", "CSL Limited", "Health Care", "Biotechnology", 90),
    ("NAB", "NAB.AX", "National Australia Bank", "Financials", "Diversified Banks", 95),
    ("WBC", "WBC.AX", "Westpac Banking Corporation", "Financials", "Diversified Banks", 90),
    ("ANZ", "ANZ.AX", "ANZ Group Holdings", "Financials", "Diversified Banks", 70),
    ("MQG", "MQG.AX", "Macquarie Group Limited", "Financials", "Investment Banking", 65),
    ("WES", "WES.AX", "Wesfarmers Limited", "Consumer Discretionary", "Diversified Retail", 65),
    ("WOW", "WOW.AX", "Woolworths Group Limited", "Consumer Staples", "Food Retail", 30),
    ("TLS", "TLS.AX", "Telstra Group Limited", "Communication Services", "Telecom Services", 35),
    ("RIO-AU", "RIO.AX", "Rio Tinto Limited", "Materials", "Diversified Mining", 100),
    ("FMG", "FMG.AX", "Fortescue Ltd.", "Materials", "Steel", 30),
    ("WDS", "WDS.AX", "Woodside Energy Group", "Energy", "Oil & Gas E&P", 30),
    ("GMG", "GMG.AX", "Goodman Group", "Real Estate", "Industrial REITs", 45),
    ("TCL", "TCL.AX", "Transurban Group", "Industrials", "Highways & Railtracks", 30),
    ("COL", "COL.AX", "Coles Group Limited", "Consumer Staples", "Food Retail", 22),
    ("ALL", "ALL.AX", "Aristocrat Leisure Limited", "Consumer Discretionary", "Casinos & Gaming", 35),
    ("JHX", "JHX.AX", "James Hardie Industries", "Industrials", "Building Products", 12),
    ("RMD", "RMD.AX", "ResMed Inc.", "Health Care", "Health Care Equipment", 35),
    ("COH", "COH.AX", "Cochlear Limited", "Health Care", "Health Care Equipment", 18),
    ("QBE", "QBE.AX", "QBE Insurance Group", "Financials", "Property & Casualty Insurance", 25),
    ("SUN", "SUN.AX", "Suncorp Group Limited", "Financials", "Multi-line Insurance", 20),
    ("S32", "S32.AX", "South32 Limited", "Materials", "Diversified Mining", 15),
    ("ORG", "ORG.AX", "Origin Energy Limited", "Utilities", "Multi-Utilities", 15),
    ("STO", "STO.AX", "Santos Limited", "Energy", "Oil & Gas E&P", 15),
    ("BXB", "BXB.AX", "Brambles Limited", "Industrials", "Trading Companies", 20),
    ("AMC", "AMC.AX", "Amcor plc", "Materials", "Packaging", 18),
]


# ==========================================================================
# 8. India -- ~35 major Nifty 50 names.
# ==========================================================================
IN_EQUITIES = [
    ("RELIANCE", "RELIANCE.NS", "Reliance Industries Ltd.", "Energy", "Integrated Oil & Gas", 210),
    ("TCS", "TCS.NS", "Tata Consultancy Services", "Information Technology", "IT Services", 160),
    ("HDFCBANK", "HDFCBANK.NS", "HDFC Bank Ltd.", "Financials", "Diversified Banks", 165),
    ("ICICIBANK", "ICICIBANK.NS", "ICICI Bank Ltd.", "Financials", "Diversified Banks", 115),
    ("INFY", "INFY.NS", "Infosys Ltd.", "Information Technology", "IT Services", 85),
    ("SBIN", "SBIN.NS", "State Bank of India", "Financials", "Diversified Banks", 75),
    ("BHARTIARTL", "BHARTIARTL.NS", "Bharti Airtel Ltd.", "Communication Services", "Wireless Telecom", 115),
    ("ITC", "ITC.NS", "ITC Ltd.", "Consumer Staples", "Tobacco", 55),
    ("HINDUNILVR", "HINDUNILVR.NS", "Hindustan Unilever Ltd.", "Consumer Staples", "Household Products", 65),
    ("LT", "LT.NS", "Larsen & Toubro Ltd.", "Industrials", "Construction & Engineering", 50),
    ("KOTAKBANK", "KOTAKBANK.NS", "Kotak Mahindra Bank Ltd.", "Financials", "Diversified Banks", 45),
    ("AXISBANK", "AXISBANK.NS", "Axis Bank Ltd.", "Financials", "Diversified Banks", 40),
    ("BAJFINANCE", "BAJFINANCE.NS", "Bajaj Finance Ltd.", "Financials", "Consumer Finance", 55),
    ("MARUTI", "MARUTI.NS", "Maruti Suzuki India Ltd.", "Consumer Discretionary", "Automobiles", 45),
    ("SUNPHARMA", "SUNPHARMA.NS", "Sun Pharmaceutical Industries", "Health Care", "Pharmaceuticals", 45),
    ("HCLTECH", "HCLTECH.NS", "HCL Technologies Ltd.", "Information Technology", "IT Services", 45),
    ("TITAN", "TITAN.NS", "Titan Company Ltd.", "Consumer Discretionary", "Apparel & Luxury Goods", 30),
    ("ASIANPAINT", "ASIANPAINT.NS", "Asian Paints Ltd.", "Materials", "Specialty Chemicals", 25),
    ("ULTRACEMCO", "ULTRACEMCO.NS", "UltraTech Cement Ltd.", "Materials", "Construction Materials", 35),
    ("WIPRO", "WIPRO.NS", "Wipro Ltd.", "Information Technology", "IT Services", 30),
    ("ADANIENT", "ADANIENT.NS", "Adani Enterprises Ltd.", "Industrials", "Industrial Conglomerates", 35),
    ("ADANIPORTS", "ADANIPORTS.NS", "Adani Ports and SEZ Ltd.", "Industrials", "Marine Ports & Services", 30),
    ("TATAMOTORS", "TATAMOTORS.NS", "Tata Motors Ltd.", "Consumer Discretionary", "Automobiles", 35),
    ("TATASTEEL", "TATASTEEL.NS", "Tata Steel Ltd.", "Materials", "Steel", 22),
    ("M&M", "M%26M.NS", "Mahindra & Mahindra Ltd.", "Consumer Discretionary", "Automobiles", 40),
    ("NTPC", "NTPC.NS", "NTPC Ltd.", "Utilities", "Electric Utilities", 40),
    ("POWERGRID", "POWERGRID.NS", "Power Grid Corp of India", "Utilities", "Electric Utilities", 30),
    ("COALINDIA", "COALINDIA.NS", "Coal India Ltd.", "Energy", "Coal", 25),
    ("JSWSTEEL", "JSWSTEEL.NS", "JSW Steel Ltd.", "Materials", "Steel", 25),
    ("NESTLEIND", "NESTLEIND.NS", "Nestle India Ltd.", "Consumer Staples", "Packaged Foods", 27),
    ("BAJAJFINSV", "BAJAJFINSV.NS", "Bajaj Finserv Ltd.", "Financials", "Diversified Financial Services", 30),
    ("INDUSINDBK", "INDUSINDBK.NS", "IndusInd Bank Ltd.", "Financials", "Diversified Banks", 10),
    ("HINDALCO", "HINDALCO.NS", "Hindalco Industries Ltd.", "Materials", "Aluminum", 18),
    ("DRREDDY", "DRREDDY.NS", "Dr. Reddy's Laboratories", "Health Care", "Pharmaceuticals", 15),
    ("CIPLA", "CIPLA.NS", "Cipla Ltd.", "Health Care", "Pharmaceuticals", 14),
]


# ==========================================================================
# 9. Brazil -- ~25 major B3 (Bovespa) names.
# ==========================================================================
BR_EQUITIES = [
    ("PETR4", "PETR4.SA", "Petroleo Brasileiro SA (Petrobras)", "Energy", "Integrated Oil & Gas", 90),
    ("VALE3", "VALE3.SA", "Vale SA", "Materials", "Diversified Mining", 55),
    ("ITUB4", "ITUB4.SA", "Itau Unibanco Holding SA", "Financials", "Diversified Banks", 65),
    ("BBDC4", "BBDC4.SA", "Banco Bradesco SA", "Financials", "Diversified Banks", 30),
    ("BBAS3", "BBAS3.SA", "Banco do Brasil SA", "Financials", "Diversified Banks", 25),
    ("B3SA3", "B3SA3.SA", "B3 SA - Brasil Bolsa Balcao", "Financials", "Financial Exchanges & Data", 12),
    ("ABEV3", "ABEV3.SA", "Ambev SA", "Consumer Staples", "Brewers", 40),
    ("WEGE3", "WEGE3.SA", "WEG SA", "Industrials", "Electrical Equipment", 25),
    ("RENT3", "RENT3.SA", "Localiza Rent a Car SA", "Industrials", "Commercial Services", 10),
    ("SUZB3", "SUZB3.SA", "Suzano SA", "Materials", "Paper Products", 15),
    ("JBSS3", "JBSS3.SA", "JBS SA", "Consumer Staples", "Packaged Foods", 15),
    ("ELET3", "ELET3.SA", "Centrais Eletricas Brasileiras (Eletrobras)", "Utilities", "Electric Utilities", 18),
    ("GGBR4", "GGBR4.SA", "Gerdau SA", "Materials", "Steel", 8),
    ("CSNA3", "CSNA3.SA", "Companhia Siderurgica Nacional", "Materials", "Steel", 4),
    ("HAPV3", "HAPV3.SA", "Hapvida Participacoes e Investimentos", "Health Care", "Managed Health Care", 8),
    ("EQTL3", "EQTL3.SA", "Equatorial Energia SA", "Utilities", "Electric Utilities", 12),
    ("CPFE3", "CPFE3.SA", "CPFL Energia SA", "Utilities", "Electric Utilities", 10),
    ("UGPA3", "UGPA3.SA", "Ultrapar Participacoes SA", "Energy", "Oil & Gas Refining & Marketing", 6),
    ("LREN3", "LREN3.SA", "Lojas Renner SA", "Consumer Discretionary", "Apparel Retail", 5),
    ("CSAN3", "CSAN3.SA", "Cosan SA", "Energy", "Oil & Gas Refining & Marketing", 6),
    ("TIMS3", "TIMS3.SA", "TIM SA", "Communication Services", "Wireless Telecom", 8),
    ("VIVT3", "VIVT3.SA", "Telefonica Brasil SA (Vivo)", "Communication Services", "Telecom Services", 10),
    ("RADL3", "RADL3.SA", "Raia Drogasil SA", "Consumer Staples", "Drug Retail", 10),
    ("KLBN11", "KLBN11.SA", "Klabin SA", "Materials", "Paper Products", 6),
]


# ==========================================================================
# 10. China / Hong Kong -- ~28 major HK-listed names.
# ==========================================================================
CN_HK_EQUITIES = [
    ("0700", "0700.HK", "Tencent Holdings Ltd.", "Communication Services", "Interactive Media", 500),
    ("9988", "9988.HK", "Alibaba Group Holding Ltd.", "Consumer Discretionary", "Internet Retail", 280),
    ("0005", "0005.HK", "HSBC Holdings plc", "Financials", "Diversified Banks", 170),
    ("1299", "1299.HK", "AIA Group Ltd.", "Financials", "Life Insurance", 85),
    ("3690", "3690.HK", "Meituan", "Consumer Discretionary", "Internet Retail", 85),
    ("0939", "0939.HK", "China Construction Bank Corp.", "Financials", "Diversified Banks", 190),
    ("1398", "1398.HK", "Industrial and Commercial Bank of China", "Financials", "Diversified Banks", 220),
    ("3988", "3988.HK", "Bank of China Ltd.", "Financials", "Diversified Banks", 150),
    ("0941", "0941.HK", "China Mobile Ltd.", "Communication Services", "Wireless Telecom", 210),
    ("0883", "0883.HK", "CNOOC Ltd.", "Energy", "Oil & Gas E&P", 90),
    ("0857", "0857.HK", "PetroChina Company Ltd.", "Energy", "Integrated Oil & Gas", 200),
    ("2318", "2318.HK", "Ping An Insurance Group", "Financials", "Life Insurance", 110),
    ("9618", "9618.HK", "JD.com Inc.", "Consumer Discretionary", "Internet Retail", 55),
    ("9999", "9999.HK", "NetEase Inc.", "Communication Services", "Interactive Home Entertainment", 65),
    ("1810", "1810.HK", "Xiaomi Corporation", "Information Technology", "Technology Hardware", 150),
    ("1211", "1211.HK", "BYD Company Ltd.", "Consumer Discretionary", "Automobiles", 130),
    ("2628", "2628.HK", "China Life Insurance Company", "Financials", "Life Insurance", 90),
    ("0386", "0386.HK", "China Petroleum & Chemical (Sinopec)", "Energy", "Integrated Oil & Gas", 60),
    ("0388", "0388.HK", "Hong Kong Exchanges and Clearing", "Financials", "Financial Exchanges & Data", 55),
    ("0016", "0016.HK", "Sun Hung Kai Properties Ltd.", "Real Estate", "Diversified Real Estate", 25),
    ("0001", "0001.HK", "CK Hutchison Holdings Ltd.", "Industrials", "Diversified Support Services", 20),
    ("0823", "0823.HK", "Link Real Estate Investment Trust", "Real Estate", "Diversified REITs", 12),
    ("0027", "0027.HK", "Galaxy Entertainment Group", "Consumer Discretionary", "Casinos & Gaming", 20),
    ("1928", "1928.HK", "Sands China Ltd.", "Consumer Discretionary", "Casinos & Gaming", 20),
    ("3968", "3968.HK", "China Merchants Bank", "Financials", "Diversified Banks", 130),
    ("0175", "0175.HK", "Geely Automobile Holdings", "Consumer Discretionary", "Automobiles", 22),
    ("2015", "2015.HK", "Li Auto Inc.", "Consumer Discretionary", "Automobiles", 25),
    ("1024", "1024.HK", "Kuaishou Technology", "Communication Services", "Interactive Media", 25),
    ("2020", "2020.HK", "Anta Sports Products Ltd.", "Consumer Discretionary", "Apparel", 20),
]


# ==========================================================================
# 11. Crypto -- top ~40 cryptocurrencies by category ("gics_sector" reused
#     as narrative/category).
# ==========================================================================
CRYPTO = [
    ("BTC", "BTC-USD", "Bitcoin", "Store of Value", "Layer 1", None),
    ("ETH", "ETH-USD", "Ethereum", "Smart Contract Platform", "Layer 1", None),
    ("USDT", "USDT-USD", "Tether", "Stablecoin", "Fiat-backed Stablecoin", None),
    ("BNB", "BNB-USD", "BNB", "Exchange Token", "Layer 1", None),
    ("SOL", "SOL-USD", "Solana", "Smart Contract Platform", "Layer 1", None),
    ("USDC", "USDC-USD", "USD Coin", "Stablecoin", "Fiat-backed Stablecoin", None),
    ("XRP", "XRP-USD", "XRP", "Payments", "Payments", None),
    ("DOGE", "DOGE-USD", "Dogecoin", "Meme", "Meme Coin", None),
    ("ADA", "ADA-USD", "Cardano", "Smart Contract Platform", "Layer 1", None),
    ("TON", "TON11419-USD", "Toncoin", "Smart Contract Platform", "Layer 1", None),
    ("AVAX", "AVAX-USD", "Avalanche", "Smart Contract Platform", "Layer 1", None),
    ("SHIB", "SHIB-USD", "Shiba Inu", "Meme", "Meme Coin", None),
    ("TRX", "TRX-USD", "TRON", "Smart Contract Platform", "Layer 1", None),
    ("DOT", "DOT-USD", "Polkadot", "Interoperability", "Layer 0", None),
    ("LINK", "LINK-USD", "Chainlink", "Oracle", "Oracle / Middleware", None),
    ("MATIC", "POL-USD", "Polygon (POL)", "Scaling", "Layer 2", None),
    ("BCH", "BCH-USD", "Bitcoin Cash", "Payments", "Layer 1", None),
    ("LTC", "LTC-USD", "Litecoin", "Payments", "Layer 1", None),
    ("NEAR", "NEAR-USD", "NEAR Protocol", "Smart Contract Platform", "Layer 1", None),
    ("ICP", "ICP-USD", "Internet Computer", "Smart Contract Platform", "Layer 1", None),
    ("UNI", "UNI7083-USD", "Uniswap", "DeFi", "Decentralized Exchange", None),
    ("APT", "APT21794-USD", "Aptos", "Smart Contract Platform", "Layer 1", None),
    ("ETC", "ETC-USD", "Ethereum Classic", "Smart Contract Platform", "Layer 1", None),
    ("XLM", "XLM-USD", "Stellar", "Payments", "Payments", None),
    ("ATOM", "ATOM-USD", "Cosmos Hub", "Interoperability", "Layer 0", None),
    ("HBAR", "HBAR-USD", "Hedera", "Smart Contract Platform", "Layer 1", None),
    ("FIL", "FIL-USD", "Filecoin", "Infrastructure", "Decentralized Storage", None),
    ("ARB", "ARB11841-USD", "Arbitrum", "Scaling", "Layer 2", None),
    ("OP", "OP-USD", "Optimism", "Scaling", "Layer 2", None),
    ("VET", "VET-USD", "VeChain", "Supply Chain", "Layer 1", None),
    ("MKR", "MKR-USD", "Maker", "DeFi", "Lending / Stablecoin Issuer", None),
    ("AAVE", "AAVE-USD", "Aave", "DeFi", "Lending", None),
    ("ALGO", "ALGO-USD", "Algorand", "Smart Contract Platform", "Layer 1", None),
    ("SAND", "SAND-USD", "The Sandbox", "Metaverse / Gaming", "Gaming Token", None),
    ("MANA", "MANA-USD", "Decentraland", "Metaverse / Gaming", "Gaming Token", None),
    ("GRT", "GRT6719-USD", "The Graph", "Infrastructure", "Indexing Protocol", None),
    ("INJ", "INJ-USD", "Injective", "DeFi", "Derivatives Chain", None),
    ("SUI", "SUI20947-USD", "Sui", "Smart Contract Platform", "Layer 1", None),
    ("RUNE", "RUNE-USD", "THORChain", "DeFi", "Cross-chain DEX", None),
    ("PEPE", "PEPE24478-USD", "Pepe", "Meme", "Meme Coin", None),
]


# ==========================================================================
# 12. Commodities -- futures + liquid ETF proxies.
# ==========================================================================
COMMODITIES = [
    ("GC", "GC=F", "Gold Futures", "Precious Metals", "Futures", "USD", None),
    ("SI", "SI=F", "Silver Futures", "Precious Metals", "Futures", "USD", None),
    ("PL", "PL=F", "Platinum Futures", "Precious Metals", "Futures", "USD", None),
    ("PA", "PA=F", "Palladium Futures", "Precious Metals", "Futures", "USD", None),
    ("HG", "HG=F", "Copper Futures", "Industrial Metals", "Futures", "USD", None),
    ("CL", "CL=F", "WTI Crude Oil Futures", "Energy", "Futures", "USD", None),
    ("BZ", "BZ=F", "Brent Crude Oil Futures", "Energy", "Futures", "USD", None),
    ("NG", "NG=F", "Natural Gas Futures", "Energy", "Futures", "USD", None),
    ("RB", "RB=F", "RBOB Gasoline Futures", "Energy", "Futures", "USD", None),
    ("HO", "HO=F", "Heating Oil Futures", "Energy", "Futures", "USD", None),
    ("ZC", "ZC=F", "Corn Futures", "Agriculture", "Futures", "USD", None),
    ("ZW", "ZW=F", "Wheat Futures", "Agriculture", "Futures", "USD", None),
    ("ZS", "ZS=F", "Soybean Futures", "Agriculture", "Futures", "USD", None),
    ("KC", "KC=F", "Coffee Futures", "Agriculture", "Futures", "USD", None),
    ("CT", "CT=F", "Cotton Futures", "Agriculture", "Futures", "USD", None),
    ("SB", "SB=F", "Sugar Futures", "Agriculture", "Futures", "USD", None),
    ("CC", "CC=F", "Cocoa Futures", "Agriculture", "Futures", "USD", None),
    ("LE", "LE=F", "Live Cattle Futures", "Agriculture", "Futures", "USD", None),
    ("GLD", "GLD", "SPDR Gold Shares", "Precious Metals", "ETF", "USD", None),
    ("SLV", "SLV", "iShares Silver Trust", "Precious Metals", "ETF", "USD", None),
    ("USO", "USO", "United States Oil Fund", "Energy", "ETF", "USD", None),
    ("UNG", "UNG", "United States Natural Gas Fund", "Energy", "ETF", "USD", None),
    ("DBC", "DBC", "Invesco DB Commodity Index Tracking", "Broad Commodities", "ETF", "USD", None),
    ("DBA", "DBA", "Invesco DB Agriculture Fund", "Agriculture", "ETF", "USD", None),
]


# ==========================================================================
# 13. Currencies (FX) -- major + a few EM pairs, plus the Dollar Index.
# ==========================================================================
CURRENCIES = [
    ("DXY", "DX-Y.NYB", "US Dollar Index", "Dollar Index", "Index", "USD", None),
    ("EURUSD", "EURUSD=X", "Euro / US Dollar", "Major FX", "Pair", "USD", None),
    ("GBPUSD", "GBPUSD=X", "British Pound / US Dollar", "Major FX", "Pair", "USD", None),
    ("USDJPY", "USDJPY=X", "US Dollar / Japanese Yen", "Major FX", "Pair", "JPY", None),
    ("USDCHF", "USDCHF=X", "US Dollar / Swiss Franc", "Major FX", "Pair", "CHF", None),
    ("AUDUSD", "AUDUSD=X", "Australian Dollar / US Dollar", "Major FX", "Pair", "USD", None),
    ("USDCAD", "USDCAD=X", "US Dollar / Canadian Dollar", "Major FX", "Pair", "CAD", None),
    ("NZDUSD", "NZDUSD=X", "New Zealand Dollar / US Dollar", "Major FX", "Pair", "USD", None),
    ("EURGBP", "EURGBP=X", "Euro / British Pound", "Major FX", "Cross", "GBP", None),
    ("EURJPY", "EURJPY=X", "Euro / Japanese Yen", "Major FX", "Cross", "JPY", None),
    ("USDCNY", "USDCNY=X", "US Dollar / Chinese Yuan", "EM FX", "Pair", "CNY", None),
    ("USDZAR", "USDZAR=X", "US Dollar / South African Rand", "EM FX", "Pair", "ZAR", None),
    ("USDINR", "USDINR=X", "US Dollar / Indian Rupee", "EM FX", "Pair", "INR", None),
    ("USDBRL", "USDBRL=X", "US Dollar / Brazilian Real", "EM FX", "Pair", "BRL", None),
    ("USDHKD", "USDHKD=X", "US Dollar / Hong Kong Dollar", "EM FX", "Pair", "HKD", None),
    ("USDMXN", "USDMXN=X", "US Dollar / Mexican Peso", "EM FX", "Pair", "MXN", None),
]


# ==========================================================================
# 14. Bonds & Rates -- US Treasury yield tickers + liquid bond ETFs.
# ==========================================================================
BONDS_RATES = [
    ("IRX", "^IRX", "13-Week Treasury Bill Yield", "Government Yields", "Short-term Rate", "USD", None),
    ("FVX", "^FVX", "5-Year Treasury Yield", "Government Yields", "Medium-term Rate", "USD", None),
    ("TNX", "^TNX", "10-Year Treasury Yield", "Government Yields", "Long-term Rate", "USD", None),
    ("TYX", "^TYX", "30-Year Treasury Yield", "Government Yields", "Long-term Rate", "USD", None),
    ("SHY", "SHY", "iShares 1-3 Year Treasury Bond ETF", "Government Bonds", "Short-term ETF", "USD", None),
    ("IEI", "IEI", "iShares 3-7 Year Treasury Bond ETF", "Government Bonds", "Medium-term ETF", "USD", None),
    ("IEF", "IEF", "iShares 7-10 Year Treasury Bond ETF", "Government Bonds", "Medium-term ETF", "USD", None),
    ("TLT", "TLT", "iShares 20+ Year Treasury Bond ETF", "Government Bonds", "Long-term ETF", "USD", None),
    ("AGG", "AGG", "iShares Core US Aggregate Bond ETF", "Aggregate Bonds", "Broad Market ETF", "USD", None),
    ("BND", "BND", "Vanguard Total Bond Market ETF", "Aggregate Bonds", "Broad Market ETF", "USD", None),
    ("LQD", "LQD", "iShares iBoxx Investment Grade Corp Bond ETF", "Corporate Bonds", "Investment Grade ETF", "USD", None),
    ("HYG", "HYG", "iShares iBoxx High Yield Corp Bond ETF", "Corporate Bonds", "High Yield ETF", "USD", None),
    ("MUB", "MUB", "iShares National Muni Bond ETF", "Municipal Bonds", "Muni ETF", "USD", None),
    ("TIP", "TIP", "iShares TIPS Bond ETF", "Inflation-Protected Bonds", "TIPS ETF", "USD", None),
    ("EMB", "EMB", "iShares JP Morgan EM Bond ETF", "Emerging Market Bonds", "EM Sovereign ETF", "USD", None),
    ("BNDX", "BNDX", "Vanguard Total International Bond ETF", "International Bonds", "Broad Market ETF", "USD", None),
]

# Yield-curve tickers used specifically to draw the US Treasury curve chart.
US_YIELD_CURVE = [
    ("3M", "^IRX"), ("5Y", "^FVX"), ("10Y", "^TNX"), ("30Y", "^TYX"),
]


# Curated fallback list + quote currency for every equity market besides
# South Africa (which has its own dedicated load_jse_rows() below).
EQUITY_FALLBACKS = {
    "United States": ("USD", US_EQUITIES),
    "United Kingdom": ("GBP", UK_EQUITIES),
    "Germany": ("EUR", DE_EQUITIES),
    "Japan": ("JPY", JP_EQUITIES),
    "Canada": ("CAD", CA_EQUITIES),
    "Australia": ("AUD", AU_EQUITIES),
    "India": ("INR", IN_EQUITIES),
    "Brazil": ("BRL", BR_EQUITIES),
    "China/Hong Kong": ("HKD", CN_HK_EQUITIES),
}


def build(use_live: bool = True):
    """use_live=True (default) tries Yahoo's live screener API first for
    every equity market and mutual funds, falling back to the curated
    lists in this file wherever the live call fails or comes back thin
    (no internet, rate-limited, Yahoo API shape changed, etc.) -- so this
    always produces a complete, working universe either way. Pass
    use_live=False to skip the live attempt entirely and build purely
    from the curated lists (fast, deterministic, useful for testing)."""
    rows = []
    source_log = []

    # --- South Africa: live screener (region='za'), else the existing
    # dedicated JSE universe (data/jse_universe.csv). ---
    za_live = fetch_live_equities("South Africa") if use_live else []
    if za_live:
        rows += za_live
        source_log.append(f"South Africa: LIVE ({len(za_live)} names)")
    else:
        jse_rows = load_jse_rows()
        rows += jse_rows
        source_log.append(f"South Africa: curated fallback ({len(jse_rows)} names)")

    # --- Every other equity market: same live-then-curated pattern. ---
    for market, (currency, curated) in EQUITY_FALLBACKS.items():
        live_rows = fetch_live_equities(market) if use_live else []
        if live_rows:
            rows += live_rows
            source_log.append(f"{market}: LIVE ({len(live_rows)} names)")
        else:
            curated_rows = _rows("Equity", market, currency, curated)
            rows += curated_rows
            source_log.append(f"{market}: curated fallback ({len(curated_rows)} names)")

    # --- Mutual funds: live predefined fund screens, else a small curated
    # fallback list of well-known US funds. ---
    fund_rows = fetch_live_funds() if use_live else []
    if fund_rows:
        rows += fund_rows
        source_log.append(f"Mutual Funds: LIVE ({len(fund_rows)} funds)")
    else:
        fallback_funds = _rows_per_currency(
            "Mutual Fund", "United States",
            [(s, t, n, cat, ind, "USD", cap) for s, t, n, cat, ind, cap in MUTUAL_FUNDS_FALLBACK],
        )
        rows += fallback_funds
        source_log.append(f"Mutual Funds: curated fallback ({len(fallback_funds)} funds)")

    # --- Asset classes with no live-screener equivalent: always curated. ---
    rows += _rows("Crypto", "Global", "USD", CRYPTO)
    rows += _rows_per_currency("Commodity", "Global", COMMODITIES)
    rows += _rows_per_currency("Currency", "Global", CURRENCIES)
    rows += _rows_per_currency("Bond/Rate", "United States", BONDS_RATES)

    df = pd.DataFrame(rows, columns=COLUMNS)
    df = df.drop_duplicates(subset=["yf_ticker"]).reset_index(drop=True)

    # Per-market/asset-class CSVs (editable, human-scannable) ...
    for (asset_class, market), sub in df.groupby(["asset_class", "market"]):
        safe = f"{asset_class}_{market}".lower().replace(" ", "_").replace("/", "_")
        sub.to_csv(os.path.join(UNIVERSE_DIR, f"{safe}.csv"), index=False)

    # ... and the single master file every page actually reads.
    master_path = os.path.join(UNIVERSE_DIR, "instruments.csv")
    df.to_csv(master_path, index=False)
    print(f"Wrote {len(df)} instruments to {master_path}")
    print("\nSource per market/asset class:")
    print("\n".join(f"  {line}" for line in source_log))
    print()
    print(df.groupby(["asset_class", "market"]).size().to_string())
    return df


if __name__ == "__main__":
    build(use_live="--no-live" not in sys.argv)
