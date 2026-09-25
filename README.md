# Global Security Analyser

A Koyfin-style screener and charting tool covering **every major asset class**, built in Python with
Streamlit. This started as a JSE-only stock analyser and has been expanded into a global, multi-asset
tool: equities across 10 countries, crypto, commodities, currencies, bonds/rates, and mutual funds --
all via free Yahoo Finance data, with the original JSE-specific analysis (SENS announcements, event
studies) kept exactly where it still applies.

**Live data first, curated fallback always available**: for every equity market and for mutual funds,
`scripts/build_global_universe.py` first tries to pull a live list straight from **Yahoo Finance's own
screener API** (the same mechanism behind finance.yahoo.com/research-hub/screener/, which Yahoo
documents as covering 10,000+ listings across 100+ exchanges) -- and only falls back to a smaller
hand-curated list for that market if the live call fails or comes back thin. This means the app ships
working out of the box (curated lists, since this build sandbox has no internet access -- see below),
and automatically upgrades itself to a much larger, live universe the moment you run the build script
on a machine with real internet access. No code changes needed on your end -- just rerun
`python3 scripts/build_global_universe.py`.

## What's built

### Cross-asset overview
1. **World Markets** (`pages/01_World_Markets.py`) -- a single cross-asset snapshot: asset-class tiles,
   major world equity indices (S&P 500, FTSE 100, DAX, Nikkei 225, Hang Seng, JSE All Share, and more),
   equity-market coverage summary, and quick top-mover snapshots for crypto, commodities/currencies,
   and US rates.
2. **US Sector Breadth** (`pages/02_US_Sector_Breadth.py`) -- the 11 real SPDR Select Sector ETFs
   (XLK, XLF, XLV, ...) in the same Name/Symbol/Last/Open/High/Low/Chg/Chg%/Vol table style as a
   market-data terminal, paired with **breadth**: what share of that sector's actual constituent US
   stocks are trading above a chosen moving average right now.

### Core analysis (works across every asset class and market)
Every page below now starts with a universe picker -- **Asset Class** (Equity / Crypto / Commodity /
Currency / Bond-Rate / Mutual Fund) and **Market** -- instead of being hard-wired to JSE stocks. Pick
your slice of the global universe, and the rest of the page works exactly as it did for JSE-only stocks.

3. **Screener** (`pages/03_Screener.py`) -- filter and group any slice of the universe by market-cap
   tier, sector/category, and industry.
4. **Charts** (`pages/04_Charts.py`) -- candlestick charts with SMAs, Bollinger Bands, RSI, MACD,
   support/resistance zones, trend lines, and period-return pills -- works for a JSE stock, a US ETF,
   Bitcoin, gold futures, a currency pair, a Treasury yield, or a mutual fund, identically.
5. **Market Breadth** (`pages/05_Market_Breadth.py`) -- % of instruments above a chosen SMA for any
   selected equity market(s), plus the Cyclical vs. Defensive sector-rotation gauge.
6. **Crypto** (`pages/06_Crypto.py`) -- live snapshot and category-level (Layer 1 / DeFi / Meme / ...)
   breadth for the ~40 tracked cryptocurrencies.
7. **Commodities & Currencies** (`pages/07_Commodities_Currencies.py`) -- futures + ETF-proxy quotes for
   metals/energy/agriculture, and major/EM FX pairs plus the US Dollar Index.
8. **Bonds & Rates** (`pages/08_Bonds_Rates.py`) -- the US Treasury yield curve (3M/5Y/10Y/30Y),
   historical 10-year yield, and bond ETF performance across the maturity/credit spectrum.
9. **Mutual Funds** (`pages/09_Mutual_Funds.py`) -- live snapshot and category-level breadth for
   well-known US mutual funds, sourced from Yahoo's fund screener (or a small curated fallback list).
10. **Distribution of Returns** (`pages/10_Distribution_of_Returns.py`) -- reproduces
    `DoR_Template.xlsx`: C-C / H-L / O-C return distributions with the same descriptive-statistics block
    and histogram bins.
11. **ATR %** (`pages/11_ATR_Percent.py`) -- reproduces `ATRP_Template.xlsx`'s True Range % over the
    same trading-horizon windows.
12. **News** (`pages/12_News.py`) -- general news (via Google News) for **any** instrument in the
    universe; the **SENS Announcements** tab appears only for JSE-listed South African equities, since
    that's the only market this app has a regulatory-announcement feed for (see below).
13. **Event Study** (`pages/13_Event_Study.py`) -- JSE-only by design (it's built on SENS announcement
    history): pulls a JSE stock's SENS history, computes its actual reaction-day return, and ranks/plots
    the price path around each announcement.
14. **Rolling Stats & Beta** (`pages/14_Rolling_Stats_Beta.py`) -- rolling volatility, beta, and
    correlation against a sensible default benchmark for the instrument's own asset class/market (its
    market's broad index for equities, Bitcoin for crypto, the Dollar Index for commodities/FX, US
    Aggregate Bonds for bonds/rates, the S&P 500 for mutual funds).
15. **Relative Performance** (`pages/15_Relative_Performance.py`) -- Koyfin-style normalized performance
    comparison: whole sectors against each other, industries within a sector, or individual instruments
    within an industry -- with every equity market's own broad benchmark index available as an overlay.
16. **Pairs Trade** (`pages/16_Pairs_Trade.py`) -- pick any two instruments, even across asset classes
    (gold vs. a gold miner, Bitcoin vs. a tech stock), for a full pairs-trade workup.
17. **Stops & Targets** (`pages/17_Stops_and_Targets.py`) -- DoR-percentile and ATRP-volatility based
    stop-loss/take-profit levels, for a single instrument or a pairs spread.
18. **Business Analysis** (`pages/18_Business_Analysis.py`) -- builds a 28-question deep-research prompt
    for any publicly listed company worldwide, automatically pointing the research at the right
    regulatory venue (SEC filings for the US, SENS for the JSE, RNS for the LSE, TDnet for Japan, etc.).
19. **Seasonality** (`pages/19_Seasonality.py`) -- monthly/day-of-week/trading-year historical
    tendencies for any instrument or world index.

The **Home** page shows asset-class tiles, a per-market "largest names" snapshot, and an always-on
breadth summary for whichever equity market you pick.

## Scope: what's covered

| Asset class | Coverage |
|---|---|
| **Equities** | South Africa (JSE), United States, United Kingdom, Germany, Japan, Canada, Australia, India, Brazil, China/Hong Kong -- live top-N-by-market-cap per market via Yahoo's screener API (up to 250 names each) when you have internet access, else a curated fallback of 25-260 well-known large/mid-caps per market (see table below) |
| **Crypto** | ~40 top cryptocurrencies by category (Layer 1, DeFi, Meme, Payments, Scaling, ...) -- curated only, no live screener equivalent |
| **Commodities** | Precious/industrial metals, energy, agriculture -- futures contracts (`=F` tickers) and liquid ETF proxies (GLD, SLV, USO, UNG, DBC, DBA) -- curated only |
| **Currencies** | Major and EM FX pairs, plus the US Dollar Index -- curated only |
| **Bonds & Rates** | US Treasury yield curve (3M/5Y/10Y/30Y) and bond ETFs across govt/corporate/muni/TIPS/EM/international -- curated only |
| **Mutual Funds** | Live via several of Yahoo's predefined fund screens (top-rated, growth, foreign, high-yield bond) merged and deduped, else a small curated fallback of well-known US funds |

### How the live screener + curated fallback works

For every equity market and for mutual funds, `scripts/build_global_universe.py` calls Yahoo's own
screener API first (`yfinance.screen()` + `EquityQuery('eq', ['region', <code>])` for equities,
several predefined `FundQuery` screens for funds -- the region codes and predefined screens are
bundled inside the `yfinance` package itself, not something this build had to guess at). If that call
fails (no internet, rate-limited, Yahoo changes something) or returns fewer than 15 usable rows, it
falls back to the hand-curated list for that market below. **Crypto, commodities, currencies, and
bonds/rates have no live-screener equivalent in Yahoo's API** (there's no "region" or "category"
concept for a futures contract or an FX pair), so those four stay curated-only regardless.

Run `python3 scripts/build_global_universe.py` (or `python3 scripts/build_global_universe.py
--no-live` to skip the live attempt entirely and build purely from the curated lists) any time you want
to refresh the universe; it prints exactly which source (LIVE or curated fallback) was used for each
market so you always know what you're looking at.

### Curation note (read this before trusting the fallback equity lists)

The **fallback** lists (used whenever live access isn't available -- true of this build sandbox, and
the default state of the zip you're reading this in) are hand-curated lists of well-known, liquid
large/mid-cap names -- not a live-scraped, complete index membership list. The fallback "US Equities"
list is a representative ~120 names spanning all 11 GICS sectors, not the full 500-odd S&P 500
constituents; similarly for the other markets. This keeps breadth/screener stats meaningful even
offline. Every fallback list lives in `scripts/build_global_universe.py` and is meant to be edited: add
a row, rerun the script. Sector/industry classification in the fallback lists is this author's general
knowledge, not a licensed GICS feed. Market-cap figures (`market_cap_usd_bn`) are rough,
order-of-magnitude approximations for sorting/tiering only, whichever source they came from.

**This app was built in a network-sandboxed dev environment with no route to Yahoo Finance**, so the
live-screener path above has never actually round-tripped to Yahoo during development -- it was
verified by (a) confirming the region codes, sector names, and predefined fund-screen names against
the real, bundled `EQUITY_SCREENER_EQ_MAP`/`PREDEFINED_SCREENER_QUERIES` data structures inside the
installed `yfinance` package (no network needed for that, just introspection) and (b) confirming that
every live call fails soft and cleanly falls back to the curated list, which is exactly what happened
when this was run in this sandbox (network blocked) -- the build produced a complete, working
~734-instrument universe entirely from fallback data, with the source log to prove it. The very first
time you run `build_global_universe.py` on a machine with real internet access will be the first live
test of the screener calls themselves -- if Yahoo's API shape has changed since, the fallback keeps the
app working either way. Every UI flow was checked with `streamlit.testing.v1.AppTest` against synthetic
mocked price data (`scripts/smoke_test_pages.py` runs all 20 pages; `scripts/smoke_test_cross_asset.py`
additionally exercises non-default Asset Class/Market picks including Crypto, US equities, commodities,
currencies, bonds, and mutual funds), and the quant logic (SMA/RSI/MACD/ATR%/returns/rolling
stats/pairs stats) is asset-class-agnostic by construction -- it just operates on OHLCV data, so it
never needed to change. **Run `scripts/test_data_connection.py` first thing** on a machine with real
internet access to see exactly which tickers resolve and which don't; the app skips (never crashes on)
any ticker Yahoo doesn't recognise or has no data for.

## Setup

```bash
cd jse-stock-analyser
pip install -r requirements.txt

# rebuild the global instrument universe -- tries Yahoo's live screener API
# first for every equity market + mutual funds, falls back to the curated
# lists otherwise. Already generated (from curated fallback, since this
# build sandbox has no internet), so this is optional -- but running it on
# YOUR machine is how you get the much larger live universe instead.
python3 scripts/build_global_universe.py
# python3 scripts/build_global_universe.py --no-live   # curated-only, faster

# confirm your machine can reach Yahoo Finance across every asset class
python3 scripts/test_data_connection.py

# confirm SENS scraping (Sharenet, JSE-only) and news (Google News RSS) work too
python3 scripts/test_sens_connection.py

# offline sanity checks (no internet needed -- uses synthetic mocked data)
python3 scripts/smoke_test_pages.py
python3 scripts/smoke_test_cross_asset.py

# set your own login password (do this before using the app for real)
python3 scripts/set_password.py admin "YourNewPassword"

streamlit run app.py
```

The app opens at `http://localhost:8501`. Log in, then use the sidebar to move between pages.

## How the data works

- **Prices**: pulled from Yahoo Finance via `yfinance`, using the standard ticker for each market/asset
  class (`.JO` for JSE, `.L` for London, `.DE` for Germany, `.T` for Japan, `.TO` for Canada, `.AX` for
  Australia, `.NS` for India, `.SA` for Brazil, `.HK` for Hong Kong, `-USD` for crypto, `=F` for
  commodity futures, `=X` for currency pairs, `^` for indices/yields). The app skips (never crashes on)
  tickers with no data.
- **Caching**: every price series fetched is cached to `data/cache/*.parquet` for 6 hours, keyed by
  ticker (asset-class-agnostic), and batch requests are chunked to avoid rate limits. The cache always
  stores the fullest available history per ticker regardless of which page asked for it. Delete
  `data/cache/` any time to force a clean refetch.
- **Universe**: `data/universe/instruments.csv` is the single master file every page reads, built by
  `scripts/build_global_universe.py` from the JSE's existing `data/jse_universe.csv`, live pulls from
  Yahoo's screener API for every other equity market and for mutual funds, and hand-curated fallback
  lists (for those same slots, plus crypto/commodities/currencies/bonds-rates, which are curated only)
  embedded in that script. Per-market/asset-class CSVs are also written to `data/universe/` for easy
  scanning. See "How the live screener + curated fallback works" and "Curation note" above.
- **Sector / Category column**: every instrument has a `gics_sector` column -- true GICS sectors for
  equities, Morningstar-style categories for mutual funds (Large Blend, Foreign Large Blend, Intermediate
  Bond, ...), and a comparable category grouping for everything else (crypto narrative, commodity group,
  FX major/EM, bond government/corporate/etc.). This is deliberate: it lets every existing
  sector-filter/breadth/relative-performance function work unmodified across every asset class. The UI
  always labels this control "Sector / Category" so it reads sensibly regardless of what's selected.
- **Market-cap tiers**: Mega/Large/Mid/Small/Micro, assessed *relative to that instrument's own market*
  -- a JSE "Mega Cap" and a US "Mega Cap" are not the same absolute size. `market_cap_usd_bn` is a rough
  USD approximation used only for sorting/"top N" features.
- **SENS**: scraped from `https://www.sharenet.co.za/v3/sens.php`, JSE-listed shares only -- there's no
  equivalent free feed for any other market covered here, so the SENS tab on the News page only appears
  for South African equities. This is inherently fragile (see `src/sens_news.py:fetch_sens`); it fails
  soft (empty result) rather than crashing.
- **News**: Google News RSS search (`news.google.com/rss/search`), which works for any instrument in
  any market -- no API key needed, not an official Google API.
- **World/benchmark indices**: `src/universe.py`'s `WORLD_INDICES` and `MARKET_BENCHMARK` dicts hold the
  Yahoo tickers for major world indices and each equity market's own benchmark; `relative_performance.py`
  falls back to a cap-weighted (or, for non-equity asset classes, equal-weighted) constructed index from
  this app's own universe if a real index ticker isn't reachable -- every line in the app is labeled
  with which kind it is.

## Roadmap

Natural next steps: confirm the live screener calls actually round-trip on a machine with real internet
access, and tune `MIN_LIVE_ROWS`/target counts once you can see real result sizes; extend the
live-screener approach to funds further (e.g. more `FundQuery`/predefined screens, or an `ETFQuery` pass
for a proper ETF asset class) since Yahoo's screener already supports it; find or build a live-screener
equivalent for crypto/commodities/currencies/bonds where none exists today, or at least grow those
curated lists; swap the free yfinance/Sharenet/Google-News data sources for a paid vendor if coverage or
reliability becomes a problem; expand the hand-curated equity fallback universes toward fuller index
membership (e.g. the complete S&P 500/FTSE 100/Nikkei 225) as you confirm names and sectors; grow the
curated mutual-fund fallback list beyond its current ~10 names; add more equity markets (France,
Eurozone-wide, South Korea, Mexico, ...); add a scheduled background refresh so the app doesn't re-fetch
on every page load; add portfolio/watchlist tracking; find a free (or paid) sovereign-yield-curve feed
for markets beyond the US.

## Project layout

```
app.py                          Home page (login gate lives here + on every page)
pages/                          Streamlit auto-discovers these as sidebar nav (zero-padded prefixes
                                 keep the sidebar order correct now that there are 19 pages)
  01_World_Markets.py
  02_US_Sector_Breadth.py
  03_Screener.py
  04_Charts.py
  05_Market_Breadth.py
  06_Crypto.py
  07_Commodities_Currencies.py
  08_Bonds_Rates.py
  09_Mutual_Funds.py
  10_Distribution_of_Returns.py
  11_ATR_Percent.py
  12_News.py
  13_Event_Study.py             (JSE-only -- see caveats above)
  14_Rolling_Stats_Beta.py
  15_Relative_Performance.py
  16_Pairs_Trade.py
  17_Stops_and_Targets.py
  18_Business_Analysis.py
  19_Seasonality.py
src/
  auth.py                       Login gate + password hashing
  common.py                     Shared page bootstrap (theme, login, sidebar)
  data.py                       yfinance fetch + disk caching (asset-class-agnostic)
  universe.py                   Global multi-asset-class, multi-market universe loader + filters +
                                 the sidebar/inline "Asset Class / Market / Sector" picker widget +
                                 world indices / US sector ETF / benchmark metadata
  quotes.py                     Shared Name/Symbol/Last/Open/High/Low/Chg/Chg%/Vol snapshot-table
                                 builder used by World Markets, US Sector Breadth, Crypto, etc.
  indicators.py                 SMA/RSI/MACD/Bollinger + ATR%/returns/distribution/event-study/period-
                                 return stats -- unchanged from the JSE-only build (already generic)
  relative_performance.py       Sector/industry/index normalized-performance lines (real + constructed),
                                 now with every equity market's own benchmark index available
  pairs.py                      Pairs-trade stats: spread, rolling correlation/z-score, cointegration,
                                 half-life -- unchanged (already generic)
  sens_news.py                  SENS scraping (Sharenet, JSE-only) + news (Google News RSS, any market)
  business_analysis.py          28-question research-prompt builder, market-aware regulatory-filing note
  theme.py                      Dark Koyfin-style CSS + Plotly template
data/
  universe/
    instruments.csv             <- the single master file every page reads (~700 instruments)
    <asset_class>_<market>.csv  Per-market/asset-class CSVs (human-scannable, editable)
  jse_universe.csv               JSE-specific universe (unchanged; source for the SA equity slice)
  jse_universe_raw.csv / jse_sector_map.csv   (unchanged; see scripts/build_universe.py)
  cache/                        (gitignored -- price history cache)
scripts/
  build_global_universe.py      Rebuild data/universe/instruments.csv (run after editing its curated lists)
  build_universe.py             Rebuild data/jse_universe.csv (unchanged, JSE-only)
  set_password.py               Change login credentials
  test_data_connection.py       Sanity-check yfinance connectivity from your machine
  test_sens_connection.py       Sanity-check SENS scraping + news RSS from your machine
  smoke_test_pages.py           Offline: run every page with mocked data, catch crashes without internet
  smoke_test_cross_asset.py     Offline: same, but exercising non-default Asset Class/Market picks
  debug_sens_html.py            Diagnostic: dumps the raw SENS page structure if headlines look wrong/blank
```

## Known limitations

- Built and tested in a network-sandboxed environment: every page's Streamlit logic was verified with
  `streamlit.testing.v1.AppTest` against mocked price/SENS/news data (including non-default Asset
  Class/Market selections), and the quant math was checked against synthetic data -- but no call has
  actually round-tripped to Yahoo Finance, Sharenet, or Google News from this build environment. Run
  `scripts/test_data_connection.py` and `scripts/test_sens_connection.py` first thing on a machine with
  real internet access.
- The live-screener path (`yf.screen()` / `EquityQuery` / `FundQuery` in `build_global_universe.py`) has
  never actually round-tripped to Yahoo either, for the same reason -- it was only verified by
  introspecting the real, bundled `yfinance` query-map/predefined-screen data structures and by
  confirming the fail-soft-to-curated behaviour actually fires (which it did, for every market, when run
  in this sandbox). The very first real test of the screener calls themselves happens the first time you
  run the build script with internet access; if Yahoo's screener response shape has changed, the app
  still works from the curated fallback either way.
- Non-JSE equity universes fall back to curated representative lists (see "Curation note" above) when
  live access isn't available or comes back thin, not complete index membership -- breadth/screener
  percentages for, say, "US Equities" are relative to whatever list is actually loaded (curated ~120
  names, or however many the live screener returned), not necessarily the full S&P 500.
- Mutual Funds has no curated-vs-live middle ground the way equities do for individual markets: it's
  either Yahoo's live fund screens (several predefined screens merged and deduped) or a single small
  curated fallback list of ~10 well-known funds -- there's no per-region curated fund list to fall back
  to sector-by-sector.
- Market-cap figures for non-JSE equities are rough approximations for sorting only, not live data.
- SENS announcements and the Event Study page are JSE-only by nature of the data source; every other
  market gets general news instead (see the News page).
- There's no free, broad sovereign-yield-curve feed for any country besides the US, so Bonds & Rates is
  US-focused (international bond *ETF* exposure like BNDX/EMB is still included).
- Single/multi-user password login only -- not intended as hardened security. Fine for a locally-run
  personal tool.
