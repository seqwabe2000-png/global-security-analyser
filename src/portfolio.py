"""
Portfolio modelling & risk engine.

Pure-python/pandas analytics used by the Portfolio pages (20-25). No
Streamlit calls live in here except for caching decorators on the data
loaders -- everything else is plain functions so it can be unit-tested and
re-used from a notebook.

Layout of this module
---------------------
1. Constants        -- frequencies, default benchmarks, name->ticker aliases,
                       historical stress windows, pseudo-tickers (CASH)
2. Paste parsing    -- turn a block copied from Excel into a holdings table
3. Storage          -- save / load named Live portfolios, Model portfolios
                       and Watchlists as JSON under data/portfolios/
4. Market data      -- price fetch, JSE cents/rand glitch cleaning, FX
                       conversion to a base currency, resampling, returns
5. Risk metrics     -- asset table, portfolio summary, risk contribution,
                       VaR/CVaR (parametric / historical / Cornish-Fisher /
                       Monte Carlo), beta, drawdowns, group roll-ups
6. Construction     -- equal, inverse-vol, inverse-beta, equal risk
                       contribution, min variance, max Sharpe, efficient
                       frontier, target-vol scaling, beta hedge, trade list
7. Scenarios        -- historical stress windows + factor-shock model
8. Monte Carlo      -- forward value projection fan chart
9. Formulas         -- LaTeX + plain-English definitions shown in the UI
"""
from __future__ import annotations

import difflib
import io
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd
from scipy import optimize, stats

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORTFOLIO_DIR = os.path.join(BASE, "data", "portfolios")
KINDS = ("live", "model", "watchlist")
for _k in KINDS:
    os.makedirs(os.path.join(PORTFOLIO_DIR, _k), exist_ok=True)

# ==========================================================================
# 1. Constants
# ==========================================================================
PERIODS_PER_YEAR = {"Daily": 252, "Weekly": 52, "Monthly": 12}
RESAMPLE_RULE = {"Daily": None, "Weekly": "W-FRI", "Monthly": "ME"}

DEFAULT_BENCHMARKS = {"S&P 500": "^GSPC", "JSE Top 40": "^J200.JO"}
# If Yahoo has no data for the JSE index itself, fall back to a tradable
# proxy that tracks it (flagged in the UI whenever this happens).
BENCHMARK_PROXIES = {"^J200.JO": "STX40.JO", "^J203.JO": "STX40.JO", "^GSPC": "SPY"}
EXTRA_BENCHMARKS = {
    "JSE All Share": "^J203.JO",
    "Nasdaq 100": "^NDX",
    "MSCI Emerging Markets (EEM)": "EEM",
    "MSCI ACWI (ACWI)": "ACWI",
    "Gold (GLD)": "GLD",
    "Bitcoin": "BTC-USD",
}

CASH_TICKER = "CASH"  # pseudo-asset: zero volatility, earns the risk-free rate

SUFFIX_CCY = {
    ".JO": "ZAR", ".L": "GBP", ".DE": "EUR", ".PA": "EUR", ".AS": "EUR", ".MI": "EUR",
    ".T": "JPY", ".TO": "CAD", ".AX": "AUD", ".NS": "INR", ".SA": "BRL", ".HK": "HKD",
    ".SW": "CHF",
}

# Names as they appear on Easy Equities statements / the user's workbooks ->
# Yahoo Finance tickers. Anything not here is matched against the global
# universe (exact symbol, then fuzzy name). Edit freely.
NAME_ALIASES = {
    # --- JSE equities / ETNs (EE_ZAR_Acc)
    "afrimat limited": "AFT.JO", "afrimat": "AFT.JO",
    "anglogold ashanti plc": "ANG.JO", "anglo gold ashanti": "ANG.JO", "anglogold ashanti": "ANG.JO",
    "astral foods limited": "ARL.JO", "astral foods": "ARL.JO",
    "bhp group limited": "BHG.JO", "bhp group": "BHG.JO",
    "boxer retail limited": "BOX.JO", "boxer": "BOX.JO",
    "capitec": "CPI.JO", "capitec bank": "CPI.JO", "capitec limited": "CPI.JO",
    "copper 360 limited": "CPR.JO", "copper 360": "CPR.JO",
    "discovery limited": "DSY.JO", "discovery": "DSY.JO",
    "lewis group limited": "LEW.JO", "lewis group": "LEW.JO",
    "labat africa limited": "LAB.JO",
    "mtn": "MTN.JO", "mtn group": "MTN.JO", "mtn group limited": "MTN.JO",
    "pan african resource plc": "PAN.JO", "pan african resources": "PAN.JO",
    "ppc limited": "PPC.JO", "ppc": "PPC.JO",
    "premier": "PMR.JO", "premier group": "PMR.JO",
    "purple group limited": "PPE.JO", "purple group": "PPE.JO",
    "raubex": "RBX.JO", "reunert": "RLO.JO",
    "sasol limited": "SOL.JO", "sasol": "SOL.JO",
    "standard bank copper etn": "SBCOP.JO",
    "shoprite": "SHP.JO", "shoprite holdings": "SHP.JO",
    "sibanye stillwater limited": "SSW.JO", "sibanye stillwater": "SSW.JO",
    "stefanutti stocks holdings limited": "SSK.JO", "stefanutti stocks holdings": "SSK.JO",
    "valterra platinum limited": "VAL.JO", "valterra platinum": "VAL.JO",
    "vodacom group limited": "VOD.JO", "vodacom": "VOD.JO",
    # --- JSE ETFs (EE_TSFA_Acc)
    "satrix 40 etf": "STX40.JO", "satrix 40": "STX40.JO",
    "satrix msci emerging markets etf": "STXEMG.JO",
    "satrix nasdaq 100 etf": "STXNDQ.JO", "satrix nasdaq 100": "STXNDQ.JO",
    "satrix resi etf": "STXRES.JO", "satrix resi": "STXRES.JO",
    "satrix s&p 500 etf": "STX500.JO", "satrix s&p 500": "STX500.JO",
    "sygnia itrix eurostoxx50": "SYGEU.JO", "sygnia itrix eurostoxx 50": "SYGEU.JO",
    "sygnia itrix global prop etf": "SYGP.JO",
    "sygnia itrix msci emerging markets 50 etf": "SYGEMF.JO",
    "portfoliometrix active income prescient ametf": "PMXINC.JO",
    # --- US equities & ETFs (EE_USD_Acc)
    "advanced micro devices inc": "AMD", "advanced micro devices": "AMD",
    "alphabet inc - cl a": "GOOGL", "alphabet inc cl a": "GOOGL", "alphabet": "GOOGL",
    "amazon": "AMZN", "apple inc": "AAPL", "apple": "AAPL", "asml": "ASML",
    "bloom energy corp": "BE", "broadcom inc": "AVGO", "broadcom": "AVGO",
    "the coca-cola company": "KO", "coca-cola": "KO",
    "coherent corp": "COHR", "crowdstrike holdings inc": "CRWD",
    "energy etf vanguard": "VDE", "vanguard energy etf": "VDE",
    "etfmg prime cyber security etf": "HACK",
    "freeport-mcmoran inc": "FCX", "ge vernova inc.": "GEV", "ge vernova inc": "GEV", "ge vernova": "GEV",
    "intel": "INTC", "invesco solar etf": "TAN",
    "ishares expanded tech-software sector etf": "IGV",
    "msci south korea": "EWY", "ishares msci south korea etf": "EWY", "msci south korea etf": "EWY",
    "ishares semiconductor (soxx)": "SOXX", "ishares semiconductor etf": "SOXX",
    "lam research corp": "LRCX", "lumentum holdings inc.": "LITE", "lumentum holdings inc": "LITE",
    "marvell": "MRVL", "meta": "META", "micron": "MU", "microsoft": "MSFT",
    "monster beverage corp": "MNST", "mp materials": "MP",
    "nebius group nv class a": "NBIS", "nvdia": "NVDA", "nvidia": "NVDA", "ondas inc": "ONDS",
    "palo alto networks inc": "PANW", "poet technologies inc.": "POET",
    "sandisk": "SNDK", "southern copper corp": "SCCO",
    "spdr gold shares (gld)": "GLD", "spdr gold shares": "GLD",
    "super group sghc ltd": "SGHC", "synopsys inc": "SNPS",
    "taiwan semiconductor manufacturing company limited": "TSM", "taiwan semiconductor": "TSM",
    "vaneck vector gold miners (gldx)": "GDX", "vaneck gold miners": "GDX",
    "vertiv holdings co": "VRT",
    # --- Crypto (EE_Crypto_Acc)
    "ethereum": "ETH-USD", "solana": "SOL-USD", "bitcoin": "BTC-USD",
    "cardano": "ADA-USD", "tether": "USDT-USD",
    # --- Cash
    "cash": CASH_TICKER, "aggregate cash in all accounts": CASH_TICKER, "cash (zar)": CASH_TICKER,
}

# Historical stress windows (start = pre-shock peak, end = trough).
STRESS_SCENARIOS = {
    "GFC 2008 (Sep-08 → Mar-09)": ("2008-09-01", "2009-03-09"),
    "Nenegate rand shock (Dec-15)": ("2015-12-08", "2015-12-14"),
    "COVID crash (Feb-20 → Mar-20)": ("2020-02-19", "2020-03-23"),
    "2022 rates bear (Jan-22 → Oct-22)": ("2022-01-03", "2022-10-12"),
    "Yen carry unwind (Jul-24 → Aug-24)": ("2024-07-16", "2024-08-05"),
    "Tariff shock (Apr-25)": ("2025-04-02", "2025-04-08"),
    "DeepSeek AI selloff (Jan-25)": ("2025-01-24", "2025-01-27"),
}

HOLDING_COLUMNS = ["ticker", "name", "account", "category", "value", "weight"]


# ==========================================================================
# 2. Paste parsing
# ==========================================================================
_TICKER_RE = re.compile(r"^\^?[A-Z0-9][A-Z0-9.\-=^]{0,14}$")
_NUM_CLEAN_RE = re.compile(r"[R$€£\s,]|ZAR|USD", re.IGNORECASE)


def _norm_name(s: str) -> str:
    s = str(s).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def to_number(x):
    """'R 1 234,56' / '$1,234.56' / '12.5%' / '(3.2)' -> float (percent strings -> fraction)."""
    if x is None:
        return np.nan
    if isinstance(x, (int, float, np.number)):
        return float(x)
    s = str(x).strip()
    if s in ("", "-", "—", "#N/A", "N/A", "nan", "None"):
        return np.nan
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    pct = s.endswith("%")
    s = _NUM_CLEAN_RE.sub("", s.rstrip("%"))
    # European decimal comma "1234,56" (only when no dot present)
    if s.count(",") == 1 and "." not in s:
        s = s.replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return np.nan
    v = -v if neg else v
    return v / 100 if pct else v


def looks_like_ticker(s) -> bool:
    return bool(_TICKER_RE.match(str(s).strip())) and len(str(s).strip()) <= 15


def _read_table(text: str) -> pd.DataFrame:
    text = text.strip("\n")
    if not text.strip():
        return pd.DataFrame()
    first = text.splitlines()[0]
    sep = "\t" if "\t" in text else (";" if first.count(";") > first.count(",") else ",")
    df = pd.read_csv(io.StringIO(text), sep=sep, header=None, dtype=str, skip_blank_lines=True,
                     engine="python", on_bad_lines="skip")
    df = df.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)
    df = df.apply(lambda c: c.str.strip() if c.dtype == object else c)
    return df


_HEADER_WORDS = ("ticker", "symbol", "weight", "value", "name", "account", "category", "asset",
                 "company", "holding", "instrument", "%", "exposure", "amount", "price", "shares", "units")


def _is_header_row(row) -> bool:
    cells = [str(c).lower() for c in row if isinstance(c, str) and c]
    if not cells:
        return False
    hits = sum(any(w in c for w in _HEADER_WORDS) for c in cells)
    nums = sum(not np.isnan(to_number(c)) for c in row if isinstance(c, str))
    return (hits >= 2 and nums == 0) or (hits >= 3 and nums <= 1)


def _block_label(row) -> str:
    """First non-empty, non-numeric cell of a header row that is not itself a
    column title -- e.g. 'EE_ZAR_Acc' -> used as the account for that block."""
    for c in row:
        if isinstance(c, str) and c and np.isnan(to_number(c)):
            return "" if any(w in c.lower() for w in _HEADER_WORDS) else c
    return ""


@dataclass
class ParsedPaste:
    raw: pd.DataFrame
    columns: list
    mapping: dict           # role -> column label (or None)
    accounts: list          # per-row account label from section headers
    notes: list = field(default_factory=list)


def parse_paste(text: str) -> ParsedPaste | None:
    """Read a block copied from Excel (tab separated, or CSV). Handles:
    * a header row (or none -- roles are inferred from content)
    * several stacked blocks, each starting with its own header row whose
      first cell is an account name (the Easy Equities layout: "EE_ZAR_Acc |
      Symbols | Asset Category | ...") -> becomes the `account` column
    * "Total" rows and blank separator rows (dropped)
    * R / $ / % / thousands separators in numbers
    Returns the raw table plus an auto-detected column mapping that the UI
    lets the user override."""
    df = _read_table(text)
    if df.empty:
        return None
    notes = []

    header_idx = [i for i, row in df.iterrows() if _is_header_row(row.tolist())]
    if header_idx:
        hdr = df.iloc[header_idx[0]].fillna("").tolist()
        cols = []
        for j, h in enumerate(hdr):
            h = str(h) or f"col{j + 1}"
            cols.append(h if h not in cols else f"{h}_{j}")
    else:
        cols = [f"col{j + 1}" for j in range(df.shape[1])]

    body_rows, accounts = [], []
    current_acc = ""
    if header_idx:
        current_acc = _block_label(df.iloc[header_idx[0]].tolist())
    start = header_idx[0] + 1 if header_idx else 0
    for i in range(start, len(df)):
        row = df.iloc[i].tolist()
        if i in header_idx:
            current_acc = _block_label(row) or current_acc
            continue
        texts = [c for c in row if isinstance(c, str) and c and np.isnan(to_number(c))]
        nums = [c for c in row if isinstance(c, str) and not np.isnan(to_number(c))]
        if any(t.lower().startswith("total") for t in texts):
            continue
        if len(texts) == 1 and not nums and len(row) > 2:  # section label row
            current_acc = texts[0]
            continue
        if not texts and not nums:
            continue
        body_rows.append(row)
        accounts.append(current_acc)
    body = pd.DataFrame(body_rows) if body_rows else pd.DataFrame(columns=range(df.shape[1]))
    body.columns = (cols + [f"col{j + 1}" for j in range(len(cols), body.shape[1])])[: body.shape[1]]

    mapping = infer_mapping(body)
    if not header_idx:
        notes.append("No header row detected -- columns were identified from their contents.")
    return ParsedPaste(raw=body, columns=list(body.columns), mapping=mapping, accounts=accounts, notes=notes)


def infer_mapping(body: pd.DataFrame) -> dict:
    """Guess which column is the ticker, name, weight, value, account and category."""
    mapping = {"ticker": None, "name": None, "weight": None, "value": None, "account": None, "category": None}
    lower = {c: str(c).lower() for c in body.columns}
    numeric_cols, text_cols = [], []
    for c in body.columns:
        vals = body[c].dropna()
        vals = vals[vals.astype(str) != ""]
        if len(vals) < 0.5 * len(body):
            continue
        share_num = np.mean([not np.isnan(to_number(v)) for v in vals])
        (numeric_cols if share_num >= 0.7 else text_cols).append(c)

    # ticker: text column where most values look like Yahoo tickers
    best, best_share = None, 0
    for c in text_cols:
        vals = body[c].dropna().astype(str)
        vals = vals[vals != ""]
        if len(vals) < 0.5 * len(body):
            continue
        share = np.mean([looks_like_ticker(v) and not v.isdigit() for v in vals]) if len(vals) else 0
        if any(k in lower[c] for k in ("yahoo", "ticker")):
            share += 0.3
        if share > best_share:
            best, best_share = c, share
    if best is not None and best_share >= 0.6:
        mapping["ticker"] = best

    for c in text_cols:
        if c == mapping["ticker"]:
            continue
        l = lower[c]
        if mapping["account"] is None and "account" in l:
            mapping["account"] = c
        elif mapping["category"] is None and any(k in l for k in ("category", "sector", "asset class", "type")):
            mapping["category"] = c
    # name: the longest-average-text remaining column
    remaining = [c for c in text_cols if c not in mapping.values()]
    if remaining:
        mapping["name"] = max(remaining, key=lambda c: body[c].dropna().astype(str).str.len().mean())

    def pick(keys, avoid=()):
        for k in keys:
            for c in numeric_cols:
                if k in lower[c] and not any(a in lower[c] for a in avoid) and c not in mapping.values():
                    return c
        return None

    mapping["weight"] = pick(["weight", "%", "alloc"], avoid=("roi", "return", "chg", "change"))
    mapping["value"] = pick(["current_value", "current value", "market value", "net exposure", "value (zar)",
                             "current", "value", "exposure", "amount", "allocation"],
                            avoid=("purchase", "cost", "usd", "roi"))
    if mapping["value"] is None:
        mapping["value"] = pick(["value", "amount"], avoid=("purchase", "cost", "roi"))
    if mapping["weight"] is None and mapping["value"] is None and numeric_cols:
        mapping["value"] = numeric_cols[0]
    return mapping


def build_holdings(parsed: ParsedPaste, mapping: dict, instruments: pd.DataFrame | None = None) -> pd.DataFrame:
    """Apply a (possibly user-edited) column mapping and resolve tickers."""
    body = parsed.raw
    out = pd.DataFrame(index=body.index)
    get = lambda role: body[mapping[role]] if mapping.get(role) in body.columns else pd.Series([None] * len(body), index=body.index)
    out["name"] = get("name").fillna("").astype(str)
    out["ticker"] = get("ticker").fillna("").astype(str).str.strip().str.upper()
    acc = get("account")
    out["account"] = acc.fillna("").astype(str) if mapping.get("account") else pd.Series(parsed.accounts, index=body.index)
    out["category"] = get("category").fillna("").astype(str)
    out["value"] = get("value").map(to_number)
    w = get("weight").map(to_number)
    if w.notna().any() and w.sum() > 1.5:   # "12.3" style percentages
        w = w / 100
    out["weight"] = w

    # Resolve tickers from names where missing
    for i, r in out.iterrows():
        if not r["ticker"] or r["ticker"] in ("NAN", "NONE"):
            t, _ = resolve_ticker(r["name"], instruments)
            out.at[i, "ticker"] = t or ""
        if not r["name"] and r["ticker"]:
            out.at[i, "name"] = lookup_name(r["ticker"], instruments)
        if out.at[i, "ticker"] == CASH_TICKER and not mapping.get("account"):
            out.at[i, "account"] = "Cash"
    out = out[(out["ticker"] != "") | (out["name"] != "")]
    return normalise_holdings(out.reset_index(drop=True))


def resolve_ticker(text: str, instruments: pd.DataFrame | None = None):
    """Name or symbol -> (yahoo_ticker, how). `how` in {alias, ticker,
    universe-symbol, universe-name, fuzzy, None}."""
    if not text:
        return None, None
    raw = str(text).strip()
    key = _norm_name(raw)
    if key in NAME_ALIASES:
        return NAME_ALIASES[key], "alias"
    if instruments is not None and not instruments.empty:
        yf_set = set(instruments["yf_ticker"].astype(str))
        if raw.upper() in yf_set:
            return raw.upper(), "ticker"
        names = instruments["name"].astype(str).map(_norm_name)
        hit = instruments[names == key]
        if not hit.empty:
            return hit.iloc[0]["yf_ticker"], "universe-name"
        sym = instruments[instruments["symbol"].astype(str).str.upper() == raw.upper()]
        if len(sym) == 1:
            return sym.iloc[0]["yf_ticker"], "universe-symbol"
    if looks_like_ticker(raw) and raw == raw.upper():
        return raw.upper(), "ticker"
    candidates = list(NAME_ALIASES.keys())
    if instruments is not None and not instruments.empty:
        candidates += list(instruments["name"].astype(str).map(_norm_name))
    m = difflib.get_close_matches(key, candidates, n=1, cutoff=0.86)
    if m:
        if m[0] in NAME_ALIASES:
            return NAME_ALIASES[m[0]], "fuzzy"
        row = instruments[instruments["name"].astype(str).map(_norm_name) == m[0]].iloc[0]
        return row["yf_ticker"], "fuzzy"
    return None, None


def lookup_name(ticker: str, instruments: pd.DataFrame | None = None) -> str:
    if ticker == CASH_TICKER:
        return "Cash"
    if instruments is not None and not instruments.empty:
        hit = instruments[instruments["yf_ticker"] == ticker]
        if not hit.empty:
            return str(hit.iloc[0]["name"])
    rev = {v: k.title() for k, v in NAME_ALIASES.items()}
    return rev.get(ticker, ticker)


def normalise_holdings(h: pd.DataFrame) -> pd.DataFrame:
    """Ensure schema; merge duplicate tickers (same ticker in two accounts is
    kept as two rows so the account roll-up stays right); weights from values
    when values are present, else rescale supplied weights to sum to 1."""
    h = h.copy()
    for c in HOLDING_COLUMNS:
        if c not in h.columns:
            h[c] = np.nan if c in ("value", "weight") else ""
    h = h[HOLDING_COLUMNS]
    h["ticker"] = h["ticker"].fillna("").astype(str).str.strip().str.upper()
    for c in ("name", "account", "category"):
        h[c] = h[c].fillna("").astype(str)
    h["value"] = pd.to_numeric(h["value"], errors="coerce")
    h["weight"] = pd.to_numeric(h["weight"], errors="coerce")
    if h["value"].notna().any() and h["value"].fillna(0).abs().sum() > 0:
        tot = h["value"].fillna(0).sum()
        h["weight"] = h["value"].fillna(0) / tot if tot else h["weight"]
    else:
        s = h["weight"].fillna(0).sum()
        if s:
            h["weight"] = h["weight"].fillna(0) / s
    return h.reset_index(drop=True)


def aggregate_by_ticker(h: pd.DataFrame) -> pd.Series:
    """Holdings (possibly repeated tickers across accounts) -> weight per ticker."""
    return h.groupby("ticker")["weight"].sum()


# ==========================================================================
# 3. Storage
# ==========================================================================
def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-. ]", "_", name).strip() or "untitled"


def list_saved(kind: str) -> list:
    d = os.path.join(PORTFOLIO_DIR, kind)
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json"))


def save_portfolio(kind: str, name: str, holdings: pd.DataFrame, notes: str = "", meta: dict | None = None) -> str:
    path = os.path.join(PORTFOLIO_DIR, kind, _safe(name) + ".json")
    payload = {
        "name": name, "kind": kind, "saved_at": datetime.now().isoformat(timespec="seconds"),
        "notes": notes, "meta": meta or {},
        "holdings": holdings[[c for c in HOLDING_COLUMNS if c in holdings.columns]].replace({np.nan: None}).to_dict("records"),
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return path


def load_portfolio(kind: str, name: str) -> tuple[pd.DataFrame, dict]:
    path = os.path.join(PORTFOLIO_DIR, kind, _safe(name) + ".json")
    with open(path) as f:
        payload = json.load(f)
    h = pd.DataFrame(payload.get("holdings", []))
    return normalise_holdings(h) if not h.empty else pd.DataFrame(columns=HOLDING_COLUMNS), payload


def delete_portfolio(kind: str, name: str):
    path = os.path.join(PORTFOLIO_DIR, kind, _safe(name) + ".json")
    if os.path.exists(path):
        os.remove(path)


# ==========================================================================
# 4. Market data
# ==========================================================================
def asset_currency(ticker: str, instruments: pd.DataFrame | None = None) -> str:
    if ticker == CASH_TICKER:
        return "BASE"
    if instruments is not None and not instruments.empty:
        hit = instruments[instruments["yf_ticker"] == ticker]
        if not hit.empty and isinstance(hit.iloc[0].get("currency"), str) and hit.iloc[0]["currency"]:
            c = hit.iloc[0]["currency"].upper()
            return "GBP" if c in ("GBX", "GBP") else c
    if ticker.startswith("^"):
        return "ZAR" if ticker.endswith(".JO") else ("USD" if "." not in ticker else SUFFIX_CCY.get("." + ticker.split(".")[-1], "USD"))
    for suf, ccy in SUFFIX_CCY.items():
        if ticker.endswith(suf):
            return ccy
    if ticker.endswith("=X"):
        return ticker[3:6] if len(ticker) >= 8 else "USD"
    return "USD"


def clean_price_series(s: pd.Series) -> tuple[pd.Series, list]:
    """Remove data glitches that wreck volatility estimates.

    1. Unit flips (JSE shares are quoted in cents on Yahoo, but some days come
       back in rands, i.e. a x100 / /100 jump -- this is exactly what produced
       the 7,094% "volatility" on STX40.JO in the old risk report). Any bar
       with |log10(P_t / P_{t-1})| > 1.5 is treated as a units change of
       100^k and the rest of the series is rescaled.
    2. One-bar spikes: a move of more than +150% or -60% that fully reverses
       on the next bar is replaced by the prior price.
    Returns (clean_series, list_of_notes)."""
    notes = []
    s = pd.to_numeric(s, errors="coerce").dropna()
    s = s[s > 0]
    if len(s) < 3:
        return s, notes
    lr = np.log10(s / s.shift(1))
    k = np.where(lr.abs() > 1.5, np.round(lr / 2), 0)
    if np.any(k != 0):
        cum = np.cumsum(k)
        raw_last = s.iloc[-1]
        s = s / (100.0 ** cum)
        s = s * (raw_last / s.iloc[-1])  # keep the latest quote's units (only returns matter for risk)
        notes.append(f"{int(np.sum(k != 0))} cents/rands unit jump(s) corrected")
    r = s.pct_change()
    spike = ((r > 1.5) | (r < -0.6)) & ((r.shift(-1) < -0.55) | (r.shift(-1) > 1.2))
    if spike.any():
        s = s.mask(spike).ffill()
        notes.append(f"{int(spike.sum())} one-bar spike(s) removed")
    return s, notes


def fx_ticker(ccy: str, base: str) -> str:
    return f"{ccy}{base}=X"


def to_base_currency(prices: pd.DataFrame, currencies: dict, base: str, fx: dict) -> pd.DataFrame:
    """Multiply each local-currency price series by the FX rate (ccy->base).
    `fx` maps ccy -> Series of ccy/base rates."""
    out = {}
    for t in prices.columns:
        ccy = currencies.get(t, base)
        if ccy in (base, "BASE") or base == "LOCAL":
            out[t] = prices[t]
            continue
        rate = fx.get(ccy)
        if rate is None or rate.empty:
            out[t] = prices[t]  # best effort: left in local ccy (flagged by caller)
            continue
        rate = rate.reindex(prices.index.union(rate.index)).ffill().reindex(prices.index)
        out[t] = prices[t] * rate
    return pd.DataFrame(out, index=prices.index)


def resample_prices(prices: pd.DataFrame, frequency: str) -> pd.DataFrame:
    """Daily -> business-day grid (crypto weekends dropped, holidays ffilled
    up to 5 days); Weekly -> Friday close; Monthly -> month-end close."""
    prices = prices.sort_index()
    if frequency == "Daily":
        p = prices.ffill(limit=5)
        return p[p.index.dayofweek < 5]
    rule = RESAMPLE_RULE[frequency]
    return prices.resample(rule).last()


def simple_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pct_change(fill_method=None).iloc[1:]


def slice_lookback(df: pd.DataFrame, years: float | None) -> pd.DataFrame:
    if years is None or df.empty:
        return df
    cutoff = df.index.max() - pd.DateOffset(months=int(round(years * 12)))
    return df[df.index > cutoff]


@dataclass
class MarketData:
    """Everything the metrics need, already in base currency and frequency."""
    prices_local: pd.DataFrame          # cleaned daily local-ccy prices (full history)
    prices_base: pd.DataFrame           # cleaned daily base-ccy prices (full history)
    returns: pd.DataFrame               # base-ccy returns at chosen frequency, lookback applied
    bench_returns: pd.DataFrame         # same, for benchmarks
    fx_returns: pd.DataFrame            # ccy/base FX returns at chosen frequency
    frequency: str
    base: str
    rf_annual: float
    currencies: dict
    notes: dict                          # ticker -> list of data-quality notes
    missing: list                        # tickers with no data at all
    bench_used: dict                     # label -> actual ticker used (proxy aware)
    ohlc: dict                           # ticker -> daily OHLC DataFrame (local ccy)
    fx_levels: dict = field(default_factory=dict)   # ccy -> daily ccy/base rate

    def fx_last(self, ccy: str) -> float:
        """Latest ccy->base rate (1.0 if same currency or unknown)."""
        if ccy in (self.base, "BASE", "", None) or self.base == "LOCAL":
            return 1.0
        s = self.fx_levels.get(ccy)
        return float(s.dropna().iloc[-1]) if s is not None and not s.dropna().empty else float("nan")

    @property
    def ppy(self) -> int:
        return PERIODS_PER_YEAR[self.frequency]


def build_market_data(tickers: list, benchmarks: dict, *, base: str, frequency: str, lookback_years,
                      rf_annual: float, history_fn, instruments: pd.DataFrame | None = None,
                      extra_ccy: tuple = ("ZAR", "USD")) -> MarketData:
    """history_fn(list_of_tickers) -> {ticker: OHLCV DataFrame} (the app passes
    data.get_history_bulk). Cash is synthesised from the risk-free rate."""
    tickers = [t for t in dict.fromkeys(tickers) if t]
    real = [t for t in tickers if t != CASH_TICKER]
    bench_t = list(benchmarks.values())
    proxy_t = [BENCHMARK_PROXIES[b] for b in bench_t if b in BENCHMARK_PROXIES]
    currencies = {t: asset_currency(t, instruments) for t in real + bench_t + proxy_t}
    fx_needed = sorted({c for c in list(currencies.values()) + list(extra_ccy) if c not in (base, "BASE")}) if base != "LOCAL" else []
    fx_t = [fx_ticker(c, base) for c in fx_needed]

    hist = history_fn(list(dict.fromkeys(real + bench_t + proxy_t + fx_t)))

    notes, closes, ohlc = {}, {}, {}
    for t in real + bench_t + proxy_t:
        df = hist.get(t)
        if df is None or df.empty:
            continue
        col = "Adj Close" if "Adj Close" in df.columns and df["Adj Close"].notna().any() else "Close"
        s, n = clean_price_series(df[col])
        if n:
            notes[t] = n
        if len(s) >= 3:
            closes[t] = s
            ohlc[t] = df
    missing = [t for t in real if t not in closes]

    fx = {}
    for c, ft in zip(fx_needed, fx_t):
        df = hist.get(ft)
        if df is not None and not df.empty:
            fx[c] = clean_price_series(df["Close"])[0]
        else:
            for t in real:
                if currencies.get(t) == c:
                    notes.setdefault(t, []).append(f"no {ft} FX data -- left in {c}")

    prices_local = pd.DataFrame(closes).sort_index()
    if prices_local.empty:
        idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=10)
        prices_local = pd.DataFrame(index=idx)
    prices_base = to_base_currency(prices_local, currencies, base, fx)

    # benchmarks (with proxy fallback)
    bench_used, bench_cols = {}, {}
    for label, t in benchmarks.items():
        use = t if t in prices_base.columns else BENCHMARK_PROXIES.get(t)
        if use and use in prices_base.columns:
            bench_used[label] = use
            bench_cols[label] = prices_base[use]

    ppy = PERIODS_PER_YEAR[frequency]
    grid = resample_prices(prices_base, frequency)
    rets = simple_returns(grid)
    rets = slice_lookback(rets, lookback_years)
    asset_rets = rets[[t for t in real if t in rets.columns]].copy()
    if CASH_TICKER in tickers:
        asset_rets[CASH_TICKER] = (1 + rf_annual) ** (1 / ppy) - 1
    asset_rets = asset_rets[[t for t in tickers if t in asset_rets.columns]]
    # drop rows where every asset is NaN (e.g. before anything listed)
    non_cash = [c for c in asset_rets.columns if c != CASH_TICKER]
    if non_cash:
        asset_rets = asset_rets[asset_rets[non_cash].notna().any(axis=1)]

    b = pd.DataFrame(bench_cols)
    bench_rets = slice_lookback(simple_returns(resample_prices(b, frequency)), lookback_years) if not b.empty else pd.DataFrame(index=asset_rets.index)
    bench_rets = bench_rets.reindex(asset_rets.index)

    fxdf = pd.DataFrame(fx)
    fx_rets = slice_lookback(simple_returns(resample_prices(fxdf, frequency)), lookback_years).reindex(asset_rets.index) if not fxdf.empty else pd.DataFrame(index=asset_rets.index)

    return MarketData(prices_local=prices_local, prices_base=prices_base, returns=asset_rets,
                      bench_returns=bench_rets, fx_returns=fx_rets, frequency=frequency, base=base,
                      rf_annual=rf_annual, currencies=currencies, notes=notes, missing=missing,
                      bench_used=bench_used, ohlc=ohlc, fx_levels=fx)


# ==========================================================================
# 5. Risk metrics
# ==========================================================================
def nearest_psd(cov: pd.DataFrame) -> pd.DataFrame:
    """Pairwise covariances (assets with different history lengths) can be
    slightly non-positive-semi-definite; clip negative eigenvalues to 0."""
    a = cov.values
    a = (a + a.T) / 2
    vals, vecs = np.linalg.eigh(a)
    if vals.min() >= -1e-12:
        return cov
    vals = np.clip(vals, 0, None)
    fixed = vecs @ np.diag(vals) @ vecs.T
    return pd.DataFrame(fixed, index=cov.index, columns=cov.columns)


def cov_matrix(returns: pd.DataFrame, ppy: int, method: str = "pairwise", min_periods: int = 12) -> pd.DataFrame:
    """Annualised covariance matrix Σ = cov(r) × P.
    method='pairwise' uses the maximum overlapping history for each pair;
    'common' uses only dates where every asset has data."""
    r = returns.dropna() if method == "common" else returns
    c = r.cov(min_periods=min_periods) * ppy
    c = c.fillna(0.0)
    return nearest_psd(c)


def ann_mean(returns: pd.DataFrame | pd.Series, ppy: int):
    return returns.mean() * ppy


def cagr(r: pd.Series, ppy: int) -> float:
    r = r.dropna()
    if len(r) < 2:
        return np.nan
    growth = (1 + r).prod()
    return growth ** (ppy / len(r)) - 1 if growth > 0 else -1.0


def downside_deviation(r: pd.Series, ppy: int, mar_annual: float = 0.0) -> float:
    r = r.dropna()
    if r.empty:
        return np.nan
    mar = (1 + mar_annual) ** (1 / ppy) - 1
    d = np.minimum(r - mar, 0)
    return float(np.sqrt((d ** 2).mean()) * np.sqrt(ppy))


def drawdown_series(r: pd.Series) -> pd.Series:
    r = r.dropna()
    wealth = (1 + r).cumprod()
    return wealth / wealth.cummax() - 1


def max_drawdown(r: pd.Series) -> float:
    dd = drawdown_series(r)
    return float(dd.min()) if not dd.empty else np.nan


def beta_to(r: pd.Series, b: pd.Series, min_obs: int = 12):
    x = pd.concat([r, b], axis=1).dropna()
    if len(x) < min_obs or x.iloc[:, 1].var() == 0:
        return np.nan, np.nan
    cov = np.cov(x.iloc[:, 0], x.iloc[:, 1], ddof=1)
    beta = cov[0, 1] / cov[1, 1]
    corr = cov[0, 1] / np.sqrt(cov[0, 0] * cov[1, 1]) if cov[0, 0] > 0 else np.nan
    return float(beta), float(corr)


def horizon_periods(days: int, ppy: int) -> float:
    """Convert a trading-day horizon to periods of the chosen frequency."""
    return days * ppy / 252.0


def var_parametric(mu_ann: float, sigma_ann: float, conf: float, h_days: int) -> float:
    """Gaussian VaR as a positive loss fraction over h trading days."""
    z = stats.norm.ppf(conf)
    mu_h, sig_h = mu_ann * h_days / 252, sigma_ann * np.sqrt(h_days / 252)
    return float(z * sig_h - mu_h)


def cvar_parametric(mu_ann: float, sigma_ann: float, conf: float, h_days: int) -> float:
    z = stats.norm.ppf(conf)
    mu_h, sig_h = mu_ann * h_days / 252, sigma_ann * np.sqrt(h_days / 252)
    return float(sig_h * stats.norm.pdf(z) / (1 - conf) - mu_h)


def var_cornish_fisher(r: pd.Series, ppy: int, conf: float, h_days: int) -> float:
    """Modified VaR adjusting the normal quantile for skew S and excess kurtosis K."""
    r = r.dropna()
    if len(r) < 20 or r.std() == 0:
        return np.nan
    z = stats.norm.ppf(1 - conf)  # negative
    S, K = stats.skew(r), stats.kurtosis(r)  # K = excess kurtosis
    z_cf = z + (z ** 2 - 1) * S / 6 + (z ** 3 - 3 * z) * K / 24 - (2 * z ** 3 - 5 * z) * S ** 2 / 36
    h = horizon_periods(h_days, ppy)
    mu, sd = r.mean(), r.std(ddof=1)
    return float(-(mu * h + z_cf * sd * np.sqrt(h)))


def var_historical(r: pd.Series, ppy: int, conf: float, h_days: int) -> tuple[float, float]:
    """Historical VaR & CVaR (Expected Shortfall). If the horizon is at least
    one period, uses overlapping h-period compounded returns; otherwise scales
    the one-period quantile by sqrt(h)."""
    r = r.dropna()
    if len(r) < 20:
        return np.nan, np.nan
    h = horizon_periods(h_days, ppy)
    if h >= 1:
        n = max(1, int(round(h)))
        agg = np.exp(np.log1p(r).rolling(n).sum()) - 1 if n > 1 else r
        agg = agg.dropna()
        q = np.quantile(agg, 1 - conf)
        tail = agg[agg <= q]
        return float(-q), float(-tail.mean()) if len(tail) else float(-q)
    q = np.quantile(r, 1 - conf)
    tail = r[r <= q]
    scale = np.sqrt(h)
    return float(-q * scale), float(-tail.mean() * scale)


def var_monte_carlo(weights: pd.Series, mu_ann: pd.Series, cov_ann: pd.DataFrame, conf: float, h_days: int,
                    n_sims: int = 20000, seed: int = 7) -> tuple[float, float, np.ndarray]:
    """Simulate correlated normal asset returns over h days, value the portfolio."""
    rng = np.random.default_rng(seed)
    t = h_days / 252
    w = weights.values
    L = np.linalg.cholesky(cov_ann.values * t + np.eye(len(w)) * 1e-14)
    z = rng.standard_normal((n_sims, len(w)))
    sims = mu_ann.values * t + z @ L.T
    port = sims @ w
    q = np.quantile(port, 1 - conf)
    return float(-q), float(-port[port <= q].mean()), port


def portfolio_series(returns: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """Historical portfolio return series with CONSTANT weights (rebalanced
    each period). Where an asset has no data yet (listed later), the weights
    of the assets that do have data are re-scaled to sum to the same total."""
    w = weights.reindex(returns.columns).fillna(0)
    avail = returns.notna()
    wa = avail.mul(w, axis=1)
    denom = wa.sum(axis=1)
    scale = (w.sum() / denom).replace([np.inf, -np.inf], np.nan)
    port = (returns.fillna(0) * wa).sum(axis=1) * scale
    return port[denom > 0]


def risk_contributions(weights: pd.Series, cov: pd.DataFrame) -> pd.DataFrame:
    w = weights.reindex(cov.index).fillna(0)
    sig_p = float(np.sqrt(w @ cov @ w))
    mctr = (cov @ w) / sig_p if sig_p > 0 else cov @ w * 0
    ctr = w * mctr
    pct = ctr / sig_p if sig_p > 0 else ctr * 0
    return pd.DataFrame({"weight": w, "MCTR": mctr, "CTR": ctr, "% risk": pct})


def asset_table(md: MarketData, weights: pd.Series, conf: float, h_days: int) -> pd.DataFrame:
    """One row per asset: stand-alone stats + beta + contribution to portfolio risk."""
    R, ppy, rf = md.returns, md.ppy, md.rf_annual
    cov = cov_matrix(R, ppy)
    rc = risk_contributions(weights.reindex(R.columns).fillna(0), cov)
    rows = []
    for t in R.columns:
        r = R[t].dropna()
        mu = r.mean() * ppy if len(r) else np.nan
        sd = r.std(ddof=1) * np.sqrt(ppy) if len(r) > 1 else np.nan
        dd = downside_deviation(r, ppy, rf)
        row = {
            "ticker": t, "weight": weights.get(t, 0.0), "obs": len(r),
            "since": r.index.min().date() if len(r) else None,
            "ann_return": mu, "cagr": cagr(r, ppy), "ann_vol": sd,
            "sharpe": (mu - rf) / sd if sd and sd > 0 else np.nan,
            "sortino": (mu - rf) / dd if dd and dd > 0 else np.nan,
            "max_dd": max_drawdown(r),
            "var_param": var_parametric(mu, sd, conf, h_days) if sd == sd else np.nan,
            "var_hist": var_historical(r, ppy, conf, h_days)[0],
            "MCTR": rc.loc[t, "MCTR"], "CTR": rc.loc[t, "CTR"], "pct_risk": rc.loc[t, "% risk"],
        }
        for label in md.bench_returns.columns:
            b, c = beta_to(r, md.bench_returns[label])
            row[f"beta_{label}"] = b
            row[f"corr_{label}"] = c
        rows.append(row)
    df = pd.DataFrame(rows).set_index("ticker")
    return df


def weighted_avg_correlation(weights: pd.Series, cov: pd.DataFrame) -> float:
    w = weights.reindex(cov.index).fillna(0).values
    sd = np.sqrt(np.clip(np.diag(cov.values), 0, None))
    ws = w * sd
    num = w @ cov.values @ w - np.sum(ws ** 2)
    den = ws.sum() ** 2 - np.sum(ws ** 2)
    return float(num / den) if den > 0 else np.nan


def portfolio_summary(md: MarketData, weights: pd.Series, conf: float = 0.95, h_days: int = 10,
                      value: float | None = None, mc_sims: int = 20000) -> dict:
    """Headline portfolio numbers. `weights` indexed by ticker, summing to 1
    (anything outside md.returns -- e.g. a ticker with no data -- is dropped
    and the rest rescaled; the caller is told via 'dropped')."""
    R, ppy, rf = md.returns, md.ppy, md.rf_annual
    w_in = weights[weights != 0]
    dropped = [t for t in w_in.index if t not in R.columns]
    w = w_in[[t for t in w_in.index if t in R.columns]]
    w = w[w > 0]
    if w.sum() == 0:
        return {"error": "No holdings with price data."}
    w = w / w.sum()
    R = R[w.index]
    cov = cov_matrix(R, ppy)
    mu = ann_mean(R, ppy).fillna(0)
    sig = float(np.sqrt(w @ cov @ w))
    mu_p = float(w @ mu)
    port = portfolio_series(R, w)
    dd_dev = downside_deviation(port, ppy, rf)
    sd_i = np.sqrt(np.clip(np.diag(cov.values), 0, None))
    out = {
        "weights": w, "cov": cov, "mu": mu, "series": port, "dropped": dropped,
        "n_assets": int((w > 0).sum()), "obs": len(port),
        "start": port.index.min(), "end": port.index.max(),
        "variance": sig ** 2, "vol": sig, "exp_return": mu_p,
        "cagr": cagr(port, ppy), "realised_vol": float(port.std(ddof=1) * np.sqrt(ppy)),
        "sharpe": (mu_p - rf) / sig if sig > 0 else np.nan,
        "sortino": (mu_p - rf) / dd_dev if dd_dev and dd_dev > 0 else np.nan,
        "downside_dev": dd_dev, "max_dd": max_drawdown(port),
        "skew": float(stats.skew(port.dropna())) if len(port) > 3 and port.std() > 0 else np.nan,
        "excess_kurt": float(stats.kurtosis(port.dropna())) if len(port) > 3 and port.std() > 0 else np.nan,
        "var_param": var_parametric(mu_p, sig, conf, h_days),
        "cvar_param": cvar_parametric(mu_p, sig, conf, h_days),
        "var_cf": var_cornish_fisher(port, ppy, conf, h_days),
        "div_ratio": float((w.values @ sd_i) / sig) if sig > 0 else np.nan,
        "eff_n": float(1 / np.sum(w.values ** 2)),
        "avg_corr_equal": avg_pairwise_corr(R),
        "avg_corr_weighted": weighted_avg_correlation(w, cov),
        "risk": risk_contributions(w, cov),
        "conf": conf, "h_days": h_days,
    }
    out["var_hist"], out["cvar_hist"] = var_historical(port, ppy, conf, h_days)
    out["var_mc"], out["cvar_mc"], out["mc_dist"] = var_monte_carlo(w, mu, cov, conf, h_days, n_sims=mc_sims)
    out["calmar"] = out["cagr"] / abs(out["max_dd"]) if out["max_dd"] and out["max_dd"] < 0 else np.nan
    bench = {}
    for label in md.bench_returns.columns:
        b = md.bench_returns[label]
        beta_reg, corr = beta_to(port, b)
        betas_i = pd.Series({t: beta_to(R[t], b)[0] for t in R.columns}).fillna(0)
        beta_sum = float((w * betas_i).sum())
        x = pd.concat([port, b], axis=1).dropna()
        te = float((x.iloc[:, 0] - x.iloc[:, 1]).std(ddof=1) * np.sqrt(ppy)) if len(x) > 2 else np.nan
        b_mu = float(x.iloc[:, 1].mean() * ppy) if len(x) else np.nan
        p_mu = float(x.iloc[:, 0].mean() * ppy) if len(x) else np.nan
        # up / down capture
        up, dn = x[x.iloc[:, 1] > 0], x[x.iloc[:, 1] < 0]
        bench[label] = {
            "beta_weighted": beta_sum, "beta_regression": beta_reg, "correlation": corr,
            "r2": corr ** 2 if corr == corr else np.nan, "tracking_error": te,
            "info_ratio": (p_mu - b_mu) / te if te and te > 0 else np.nan,
            "treynor": (mu_p - rf) / beta_sum if beta_sum else np.nan,
            "alpha_jensen": p_mu - (rf + beta_reg * (b_mu - rf)) if beta_reg == beta_reg else np.nan,
            "bench_vol": float(x.iloc[:, 1].std(ddof=1) * np.sqrt(ppy)) if len(x) > 2 else np.nan,
            "bench_return": b_mu,
            "up_capture": float(up.iloc[:, 0].mean() / up.iloc[:, 1].mean()) if len(up) else np.nan,
            "down_capture": float(dn.iloc[:, 0].mean() / dn.iloc[:, 1].mean()) if len(dn) else np.nan,
            "betas_i": betas_i,
        }
    out["bench"] = bench
    if value:
        out["value"] = value
    return out


def avg_pairwise_corr(R: pd.DataFrame) -> float:
    cols = [c for c in R.columns if c != CASH_TICKER and R[c].std() > 0]
    if len(cols) < 2:
        return np.nan
    c = R[cols].corr(min_periods=12).values
    iu = np.triu_indices_from(c, k=1)
    return float(np.nanmean(c[iu]))


def group_rollup(holdings: pd.DataFrame, md: MarketData, by: str, conf: float, h_days: int) -> pd.DataFrame:
    """Per account / category: weight, contribution to total risk, and the
    group's stand-alone vol / beta / VaR as if it were its own portfolio."""
    h = holdings[holdings["ticker"].isin(md.returns.columns)].copy()
    if h.empty:
        return pd.DataFrame()
    h[by] = h[by].replace("", "(none)")
    w_tot = h.groupby("ticker")["weight"].sum()
    w_tot = w_tot / w_tot.sum()
    cov = cov_matrix(md.returns[w_tot.index], md.ppy)
    rc = risk_contributions(w_tot, cov)
    rows = []
    for g, sub in h.groupby(by):
        wg = sub.groupby("ticker")["weight"].sum()
        share = wg.sum() / h["weight"].sum()
        # CTR of group = sum over its holdings of (its weight in total) * MCTR
        ctr = float(((wg / h["weight"].sum()) * rc["MCTR"].reindex(wg.index)).sum())
        s = portfolio_summary(md, wg / wg.sum(), conf, h_days, mc_sims=2000)
        row = {by: g, "holdings": len(sub), "weight": share, "value": sub["value"].sum(min_count=1),
               "% of total risk": ctr / rc["CTR"].sum() if rc["CTR"].sum() else np.nan,
               "stand-alone vol": s.get("vol"), "exp return": s.get("exp_return"),
               "sharpe": s.get("sharpe"), "max DD": s.get("max_dd"),
               "VaR (param)": s.get("var_param")}
        for label, b in s.get("bench", {}).items():
            row[f"beta {label}"] = b["beta_weighted"]
        rows.append(row)
    return pd.DataFrame(rows).sort_values("weight", ascending=False)


def rolling_portfolio_stats(port: pd.Series, bench: pd.DataFrame, window: int, ppy: int) -> pd.DataFrame:
    out = pd.DataFrame(index=port.index)
    out["rolling vol"] = port.rolling(window).std() * np.sqrt(ppy)
    for label in bench.columns:
        b = bench[label].reindex(port.index)
        out[f"beta {label}"] = port.rolling(window).cov(b) / b.rolling(window).var()
        out[f"corr {label}"] = port.rolling(window).corr(b)
    return out


def marginal_impact(md: MarketData, base_weights: pd.Series, candidate: str, add_weight: float,
                    conf: float, h_days: int) -> dict:
    """Effect of adding `add_weight` of `candidate`, funded pro-rata from the
    existing holdings: w_new = (1-a)·w + a·e_candidate."""
    w0 = base_weights / base_weights.sum()
    w1 = w0 * (1 - add_weight)
    w1[candidate] = w1.get(candidate, 0) + add_weight
    s0 = portfolio_summary(md, w0, conf, h_days, mc_sims=2000)
    s1 = portfolio_summary(md, w1, conf, h_days, mc_sims=2000)
    out = {"Δ vol": s1["vol"] - s0["vol"], "Δ exp return": s1["exp_return"] - s0["exp_return"],
           "Δ Sharpe": s1["sharpe"] - s0["sharpe"], "Δ VaR": s1["var_param"] - s0["var_param"],
           "Δ max DD": s1["max_dd"] - s0["max_dd"]}
    for label in s0["bench"]:
        out[f"Δ beta {label}"] = s1["bench"][label]["beta_weighted"] - s0["bench"][label]["beta_weighted"]
    port = portfolio_series(md.returns[w0.index.intersection(md.returns.columns)], w0)
    out["corr to portfolio"] = beta_to(md.returns[candidate], port)[1] if candidate in md.returns else np.nan
    return out


# ==========================================================================
# 6. Construction / weighting schemes
# ==========================================================================
def _bounds(n, max_w, min_w=0.0):
    return [(min_w, max_w)] * n


def w_equal(tickers) -> pd.Series:
    return pd.Series(1 / len(tickers), index=tickers)


def w_inverse_vol(cov: pd.DataFrame) -> pd.Series:
    sd = np.sqrt(np.diag(cov.values))
    iv = np.where(sd > 0, 1 / sd, 0)
    return pd.Series(iv / iv.sum(), index=cov.index)


def w_inverse_beta(betas: pd.Series) -> pd.Series:
    """Beta parity (the PORT_BETA sheet's 'risk parity' column): w ∝ 1/β."""
    b = betas.where(betas > 0.05)
    iv = (1 / b).fillna(0)
    return iv / iv.sum() if iv.sum() else iv


def w_equal_risk(cov: pd.DataFrame, max_w: float = 1.0) -> pd.Series:
    """Equal Risk Contribution: minimise Σ (RC_i − σ_p/n)²."""
    n = len(cov)
    C = cov.values

    def obj(w):
        sig = np.sqrt(w @ C @ w)
        rc = w * (C @ w) / sig
        return np.sum((rc - sig / n) ** 2) * 1e4

    x0 = w_inverse_vol(cov).values
    res = optimize.minimize(obj, x0, method="SLSQP", bounds=_bounds(n, max_w),
                            constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1}],
                            options={"maxiter": 500, "ftol": 1e-12})
    w = np.clip(res.x, 0, None)
    return pd.Series(w / w.sum(), index=cov.index)


def w_min_variance(cov: pd.DataFrame, max_w: float = 1.0) -> pd.Series:
    n = len(cov)
    C = cov.values
    res = optimize.minimize(lambda w: w @ C @ w, np.ones(n) / n, method="SLSQP", bounds=_bounds(n, max_w),
                            constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1}], options={"maxiter": 500})
    w = np.clip(res.x, 0, None)
    return pd.Series(w / w.sum(), index=cov.index)


def w_max_sharpe(mu: pd.Series, cov: pd.DataFrame, rf: float, max_w: float = 1.0) -> pd.Series:
    n = len(cov)
    C, m = cov.values, mu.reindex(cov.index).fillna(0).values

    def neg_sharpe(w):
        s = np.sqrt(w @ C @ w)
        return -(w @ m - rf) / s if s > 0 else 0

    res = optimize.minimize(neg_sharpe, np.ones(n) / n, method="SLSQP", bounds=_bounds(n, max_w),
                            constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1}], options={"maxiter": 500})
    w = np.clip(res.x, 0, None)
    return pd.Series(w / w.sum(), index=cov.index)


def efficient_frontier(mu: pd.Series, cov: pd.DataFrame, max_w: float = 1.0, points: int = 25) -> pd.DataFrame:
    n = len(cov)
    C, m = cov.values, mu.reindex(cov.index).fillna(0).values
    wmin = w_min_variance(cov, max_w).values
    lo = wmin @ m
    # highest attainable return under the cap: fill best assets up to max_w
    order = np.argsort(-m)
    w_hi, left = np.zeros(n), 1.0
    for i in order:
        take = min(max_w, left)
        w_hi[i] = take
        left -= take
        if left <= 1e-12:
            break
    hi = w_hi @ m
    rows = []
    for target in np.linspace(lo, hi, points):
        res = optimize.minimize(lambda w: w @ C @ w, wmin, method="SLSQP", bounds=_bounds(n, max_w),
                                constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1},
                                             {"type": "eq", "fun": lambda w, t=target: w @ m - t}],
                                options={"maxiter": 300})
        if res.success:
            rows.append({"return": float(res.x @ m), "vol": float(np.sqrt(res.x @ C @ res.x))})
    return pd.DataFrame(rows)


def random_portfolios(mu: pd.Series, cov: pd.DataFrame, n: int = 2000, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    k = len(cov)
    W = rng.dirichlet(np.ones(k) * 0.5, size=n)
    m = mu.reindex(cov.index).fillna(0).values
    vol = np.sqrt(np.einsum("ij,jk,ik->i", W, cov.values, W))
    return pd.DataFrame({"return": W @ m, "vol": vol})


def scale_to_target_vol(weights: pd.Series, cov: pd.DataFrame, target_vol: float) -> tuple[pd.Series, float]:
    """Blend the risky portfolio with cash: k = σ_target/σ_p (capped at 1, no leverage)."""
    w = weights.reindex(cov.index).fillna(0)
    sig = float(np.sqrt(w @ cov @ w))
    k = min(1.0, target_vol / sig) if sig > 0 else 1.0
    return w * k, 1 - k


def beta_hedge(portfolio_value: float, beta_p: float, beta_target: float, hedge_beta: float = 1.0) -> float:
    """Notional to SHORT (positive) or buy (negative) in an instrument with
    beta `hedge_beta` to move the portfolio beta to `beta_target`."""
    return (beta_p - beta_target) * portfolio_value / hedge_beta


def trade_list(current_w: pd.Series, target_w: pd.Series, capital: float, last_price_base: pd.Series,
               lot_divisor: pd.Series | None = None) -> pd.DataFrame:
    idx = current_w.index.union(target_w.index)
    cw, tw = current_w.reindex(idx).fillna(0), target_w.reindex(idx).fillna(0)
    df = pd.DataFrame({"current weight": cw, "target weight": tw, "Δ weight": tw - cw})
    df["current value"] = cw * capital
    df["target value"] = tw * capital
    df["trade value"] = df["target value"] - df["current value"]
    px = last_price_base.reindex(idx)
    if lot_divisor is not None:
        px = px / lot_divisor.reindex(idx).fillna(1)
    df["last price (base)"] = px
    df["approx units to trade"] = (df["trade value"] / px).round(2)
    df["target units"] = (df["target value"] / px).round(2)
    return df.sort_values("trade value")


# ==========================================================================
# 7. Scenarios
# ==========================================================================
def stress_test(md: MarketData, weights: pd.Series, start: str, end: str, bench_label: str | None = None) -> pd.DataFrame:
    """Apply each asset's actual base-currency return between `start` and
    `end` to today's weights. Assets without data in the window are proxied
    by beta × benchmark return (flagged)."""
    P = md.prices_base
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    rows = []
    bench_ret = np.nan
    bench_t = md.bench_used.get(bench_label) if bench_label else None
    if bench_t and bench_t in P:
        bp = P[bench_t].dropna()
        b0, b1 = bp[bp.index <= s], bp[bp.index <= e]
        if len(b0) and len(b1) and b0.index[-1] >= s - pd.Timedelta(days=7):
            bench_ret = b1.iloc[-1] / b0.iloc[-1] - 1
    for t, w in weights.items():
        if w == 0:
            continue
        if t == CASH_TICKER:
            rows.append({"ticker": t, "weight": w, "return": 0.0, "source": "cash"})
            continue
        ret, src = np.nan, "actual"
        if t in P:
            p = P[t].dropna()
            p0, p1 = p[p.index <= s], p[p.index <= e]
            if len(p0) and len(p1) and p0.index[-1] >= s - pd.Timedelta(days=7):
                ret = p1.iloc[-1] / p0.iloc[-1] - 1
        if ret != ret and bench_label and bench_ret == bench_ret and t in md.returns:
            b, _ = beta_to(md.returns[t], md.bench_returns[bench_label])
            if b == b:
                ret, src = b * bench_ret, f"beta proxy ({b:.2f}×{bench_label})"
        if ret != ret:
            src = "no data"
        rows.append({"ticker": t, "weight": w, "return": ret, "source": src})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    covered = df["return"].notna()
    cov_w = df.loc[covered, "weight"].sum()
    tot_w = df["weight"].sum()
    # holdings with no data (and no proxy) are assumed to move like the covered part of the portfolio
    scale = tot_w / cov_w if cov_w > 0 else np.nan
    df["contribution"] = df["weight"] * df["return"].fillna(0) * scale
    df.attrs["coverage"] = float(cov_w / tot_w) if tot_w else np.nan
    df.attrs["portfolio_return"] = float(df["contribution"].sum()) if cov_w > 0 else np.nan
    df.attrs["benchmark_return"] = float(bench_ret) if bench_ret == bench_ret else np.nan
    return df.sort_values("contribution")


def factor_model(md: MarketData, factors: pd.DataFrame) -> pd.DataFrame:
    """OLS of each asset's base-ccy return on factor returns.
    Returns loadings (rows = assets, cols = factors + 'alpha', 'R²')."""
    rows = {}
    for t in md.returns.columns:
        if t == CASH_TICKER:
            rows[t] = {**{f: 0.0 for f in factors.columns}, "alpha": 0.0, "R²": np.nan}
            continue
        x = pd.concat([md.returns[t], factors], axis=1).dropna()
        if len(x) < max(12, factors.shape[1] + 5):
            rows[t] = {**{f: np.nan for f in factors.columns}, "alpha": np.nan, "R²": np.nan}
            continue
        y = x.iloc[:, 0].values
        X = np.column_stack([np.ones(len(x)), x.iloc[:, 1:].values])
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ coef
        r2 = 1 - resid.var() / y.var() if y.var() > 0 else np.nan
        rows[t] = {**dict(zip(factors.columns, coef[1:])), "alpha": coef[0], "R²": r2}
    return pd.DataFrame(rows).T


def factor_shock(loadings: pd.DataFrame, weights: pd.Series, shocks: dict) -> pd.DataFrame:
    f = [k for k in shocks if k in loadings.columns]
    L = loadings[f].reindex(weights.index)
    imp = (L * pd.Series(shocks)[f]).sum(axis=1, min_count=1)
    df = pd.DataFrame({"weight": weights, "est. return": imp})
    df["contribution"] = df["weight"] * df["est. return"].fillna(0)
    df.attrs["portfolio_return"] = float(df["contribution"].sum())
    return df.sort_values("contribution")


# ==========================================================================
# 8. Monte Carlo projection
# ==========================================================================
def project_value(port_returns: pd.Series, ppy: int, years: float, start_value: float,
                  contrib_per_period: float = 0.0, method: str = "Bootstrap", n_sims: int = 5000,
                  mu_ann: float | None = None, vol_ann: float | None = None, seed: int = 11) -> dict:
    rng = np.random.default_rng(seed)
    n = int(round(years * ppy))
    r = port_returns.dropna().values
    if method == "Bootstrap" and len(r) > 10:
        sims = rng.choice(r, size=(n_sims, n), replace=True)
    else:
        mu = (mu_ann if mu_ann is not None else r.mean() * ppy) / ppy
        sd = (vol_ann if vol_ann is not None else r.std(ddof=1) * np.sqrt(ppy)) / np.sqrt(ppy)
        sims = rng.normal(mu, sd, size=(n_sims, n))
    vals = np.empty((n_sims, n + 1))
    vals[:, 0] = start_value
    for i in range(n):
        vals[:, i + 1] = vals[:, i] * (1 + sims[:, i]) + contrib_per_period
    pct = np.percentile(vals, [5, 25, 50, 75, 95], axis=0)
    invested = start_value + contrib_per_period * np.arange(n + 1)
    return {"paths_pct": pd.DataFrame(pct.T, columns=["p5", "p25", "p50", "p75", "p95"]),
            "final": vals[:, -1], "invested": invested,
            "prob_loss": float(np.mean(vals[:, -1] < invested[-1])),
            "sample": vals[: min(60, n_sims)]}


# ==========================================================================
# 9. Formulas (LaTeX, explanation) -- rendered on the pages and on the
#    Risk Formulas page so every number on screen can be traced.
# ==========================================================================
FORMULAS = {
    "Returns": (
        r"r_{i,t} = \frac{P_{i,t}\,X_{t}}{P_{i,t-1}\,X_{t-1}} - 1",
        "Simple return of asset i in the base currency: local price P times the FX rate X (local→base). "
        "Prices are adjusted closes resampled to the chosen frequency (Friday close for weekly, month-end for monthly).",
    ),
    "Annualised return": (
        r"\mu_i = \bar r_i \times P \qquad \text{CAGR}_i = \Big(\prod_t (1+r_{i,t})\Big)^{P/N} - 1",
        "P = periods per year (252 daily, 52 weekly, 12 monthly). μ is the arithmetic mean used in the optimiser; "
        "CAGR is the geometric (compound) growth rate actually earned.",
    ),
    "Annualised volatility": (
        r"\sigma_i = s(r_i)\sqrt{P}, \qquad s(r)=\sqrt{\tfrac{1}{N-1}\sum_t (r_t-\bar r)^2}",
        "Sample standard deviation of periodic returns, scaled by √P (Excel: STDEV.S(...)*SQRT(52) for weekly).",
    ),
    "Covariance matrix": (
        r"\Sigma_{ij} = P \cdot \frac{1}{N-1}\sum_t (r_{i,t}-\bar r_i)(r_{j,t}-\bar r_j) = \rho_{ij}\,\sigma_i\,\sigma_j",
        "Annualised sample covariance (Excel COVARIANCE.S × P). Uses the maximum overlapping history for each pair; "
        "any tiny negative eigenvalues (from uneven histories) are clipped so Σ is positive semi-definite.",
    ),
    "Portfolio variance & volatility": (
        r"\sigma_p^2 = \mathbf{w}^\top \Sigma\, \mathbf{w} = \sum_i\sum_j w_i w_j \Sigma_{ij}, \qquad \sigma_p = \sqrt{\mathbf{w}^\top\Sigma\mathbf{w}}",
        "Excel: =MMULT(MMULT(TRANSPOSE(w),Σ),w). This is the ex-ante (forward-looking) volatility of today's weights.",
    ),
    "Expected portfolio return": (
        r"\mu_p = \mathbf{w}^\top \boldsymbol\mu = \sum_i w_i \mu_i",
        "Weighted average of historical annualised mean returns -- a backward-looking estimate, not a forecast.",
    ),
    "Sharpe ratio": (
        r"\text{Sharpe} = \frac{\mu_p - r_f}{\sigma_p}",
        "Excess return per unit of total risk. r_f = 3-month T-bill in the base currency (SA T-bill for ZAR, US T-bill for USD).",
    ),
    "Sortino ratio": (
        r"\text{Sortino} = \frac{\mu_p - r_f}{\sigma_D}, \quad \sigma_D = \sqrt{P}\sqrt{\tfrac1N\sum_t \min(r_{p,t} - r_f/P,\,0)^2}",
        "Like Sharpe but only penalises returns below the risk-free hurdle (downside deviation σ_D).",
    ),
    "Beta": (
        r"\beta_i = \frac{\operatorname{Cov}(r_i, r_m)}{\operatorname{Var}(r_m)}, \qquad \beta_p = \sum_i w_i\beta_i",
        "Sensitivity to the benchmark m (S&P 500, JSE Top 40...). Benchmarks are converted into the base currency too, "
        "so a USD stock's beta to the S&P in ZAR terms includes the rand. Also shown: β from regressing the portfolio's own return series.",
    ),
    "Correlation": (
        r"\rho_{ij} = \frac{\Sigma_{ij}}{\sigma_i\sigma_j}, \quad \bar\rho_{w} = \frac{\sigma_p^2 - \sum_i w_i^2\sigma_i^2}{(\sum_i w_i\sigma_i)^2 - \sum_i w_i^2\sigma_i^2}",
        "Average correlation: simple average of all pairs (as in the TFSA sheet, ignores weights) and the weight-implied average ρ̄_w.",
    ),
    "Risk contribution": (
        r"\text{MCTR}_i = \frac{(\Sigma\mathbf w)_i}{\sigma_p}, \quad \text{CTR}_i = w_i\,\text{MCTR}_i, \quad \%\text{Risk}_i = \frac{\text{CTR}_i}{\sigma_p}, \quad \sum_i \text{CTR}_i = \sigma_p",
        "Marginal contribution (how much σ_p rises per unit more of i) and total contribution. %Risk sums to 100%; "
        "a holding whose %Risk is far above its weight is a risk concentration.",
    ),
    "Parametric VaR": (
        r"\text{VaR}_{c,h} = z_c\,\sigma_p\sqrt{h/252} - \mu_p\,h/252",
        "Gaussian (variance-covariance) Value at Risk: the loss not exceeded with confidence c over h trading days. "
        "z_{95%}=1.645, z_{99%}=2.326. Money VaR = VaR% × portfolio value.",
    ),
    "Historical VaR": (
        r"\text{VaR}_{c,h} = -\,Q_{1-c}\big(R^{(h)}_p\big), \quad R^{(h)}_{p,t} = \prod_{k=0}^{h-1}(1+r_{p,t-k}) - 1",
        "Empirical (1-c) quantile of the portfolio's actual overlapping h-period returns -- no normality assumption. "
        "If h is shorter than one period (e.g. 10 days on monthly data), the one-period quantile is scaled by √h.",
    ),
    "Expected Shortfall (CVaR)": (
        r"\text{ES}_{c} = -\,\mathbb E\big[R_p \mid R_p \le -\text{VaR}_c\big], \quad \text{ES}^{\text{normal}} = \sigma_h\frac{\varphi(z_c)}{1-c} - \mu_h",
        "Average loss in the worst (1-c) of outcomes -- what a bad day looks like once VaR is breached.",
    ),
    "Cornish-Fisher VaR": (
        r"z_{cf} = z + \tfrac{(z^2-1)S}{6} + \tfrac{(z^3-3z)K}{24} - \tfrac{(2z^3-5z)S^2}{36}, \quad \text{VaR} = -(\bar r\,h + z_{cf}\,s\sqrt h)",
        "Modified VaR: the normal quantile z (=Φ⁻¹(1-c), negative) is adjusted for the portfolio's skew S and excess kurtosis K (fat tails).",
    ),
    "Monte Carlo VaR": (
        r"\mathbf r^{(k)} \sim \mathcal N\!\big(\boldsymbol\mu\,\tfrac{h}{252},\ \Sigma\,\tfrac{h}{252}\big),\quad R^{(k)}_p = \mathbf w^\top \mathbf r^{(k)},\quad \text{VaR} = -Q_{1-c}(R^{(k)}_p)",
        "20,000 correlated scenarios drawn via the Cholesky factor of Σ; VaR/ES read off the simulated distribution.",
    ),
    "Maximum drawdown": (
        r"W_t = \prod_{s\le t}(1+r_{p,s}), \quad \text{DD}_t = \frac{W_t}{\max_{s\le t}W_s} - 1, \quad \text{MDD} = \min_t \text{DD}_t",
        "Worst peak-to-trough fall of the constant-weight portfolio over the lookback. Calmar = CAGR / |MDD|.",
    ),
    "Diversification": (
        r"\text{DR} = \frac{\sum_i w_i\sigma_i}{\sigma_p}, \qquad N_{\text{eff}} = \frac{1}{\sum_i w_i^2}",
        "Diversification ratio (>1 means correlations are reducing risk) and effective number of holdings.",
    ),
    "Tracking error & information ratio": (
        r"\text{TE} = s(r_p - r_m)\sqrt P, \quad \text{IR} = \frac{\mu_p - \mu_m}{\text{TE}}, \quad \alpha_J = \mu_p - [r_f + \beta(\mu_m - r_f)], \quad \text{Treynor} = \frac{\mu_p-r_f}{\beta_p}",
        "Active risk vs a benchmark, return per unit of active risk, Jensen's alpha and Treynor ratio.",
    ),
    "Weighting schemes": (
        r"w^{EW}_i=\tfrac1n,\ \ w^{IV}_i \propto \tfrac1{\sigma_i},\ \ w^{IB}_i \propto \tfrac1{\beta_i},\ \ w^{ERC}:\ \text{CTR}_i=\tfrac{\sigma_p}{n},\ \ w^{MV}=\arg\min \mathbf w^\top\Sigma\mathbf w,\ \ w^{MS}=\arg\max\tfrac{\mathbf w^\top\boldsymbol\mu-r_f}{\sqrt{\mathbf w^\top\Sigma\mathbf w}}",
        "Equal weight, inverse volatility, inverse beta (the 'beta parity' column of the PORT_BETA sheet), equal risk contribution, "
        "minimum variance and maximum Sharpe (long-only, Σw=1, optional max weight per asset).",
    ),
    "Target volatility & beta hedge": (
        r"k = \min\!\Big(1, \tfrac{\sigma^*}{\sigma_p}\Big),\ \ w' = k\,\mathbf w,\ \ \text{cash} = 1-k \qquad H = \frac{(\beta_p - \beta^*)\,V}{\beta_H}",
        "Scale risky holdings to hit a target volatility σ* (rest in cash), and the notional H to short in a hedge instrument with beta β_H to reach target beta β*.",
    ),
    "Stress test": (
        r"R_p^{\text{stress}} = \frac{\sum_{i \in C} w_i R_i}{\sum_{i \in C} w_i}, \quad R_i = \frac{P_{i,\text{end}}X_{\text{end}}}{P_{i,\text{start}}X_{\text{start}}} - 1, \quad \text{fallback: } \hat R_i = \beta_i R_m",
        "Today's weights × what each holding actually did (in base currency) during the historical window. Assets that did not exist use β × benchmark move; "
        "any still without data are assumed to behave like the covered set C (coverage % is shown).",
    ),
    "Factor shock": (
        r"r_{i,t} = \alpha_i + \sum_k b_{ik} f_{k,t} + \varepsilon_{i,t}, \qquad \hat R_p = \sum_i w_i \sum_k b_{ik}\,\Delta f_k",
        "OLS loadings of each holding on factor returns (e.g. S&P 500 in USD, JSE Top 40, USD/ZAR); a hypothetical shock Δf is pushed through the loadings.",
    ),
    "Monte Carlo projection": (
        r"V_{t+1} = V_t (1 + \tilde r_{t+1}) + C, \quad \tilde r \sim \text{bootstrap}\{r_{p}\}\ \text{or}\ \mathcal N(\mu_p/P,\ \sigma_p^2/P)",
        "Forward value paths with optional regular contributions C; percentiles (5/25/50/75/95) form the fan chart.",
    ),
    "Marginal impact of a new position": (
        r"\mathbf w' = (1-a)\,\mathbf w + a\,\mathbf e_c, \qquad \Delta\sigma = \sigma(\mathbf w') - \sigma(\mathbf w)",
        "Watchlist: adding a% of candidate c, funded pro-rata from existing holdings, and the resulting change in vol, VaR, beta, Sharpe.",
    ),
}
