"""
Best-effort SENS announcements + news fetching.

There is no free official JSE SENS API, so SENS headlines are scraped from
Sharenet's public (no-login) SENS pages, and news is pulled from Google
News' public RSS search feed. Both are wrapped so a layout change or a
network hiccup degrades to an empty result with a message, never a crash.

NOTE: like src/data.py, this was written in a sandboxed dev environment
with no route to either sharenet.co.za or news.google.com, so it could not
be exercised against live traffic during development -- the HTML/RSS
parsing logic follows the structure observed via web research at build
time (September 2026). Run `python3 scripts/test_sens_connection.py` on
your machine to confirm both sources still work, and see that script's
docstring for what to do if Sharenet's markup has since changed.
"""
import re
from datetime import datetime, timedelta
from urllib.parse import quote, urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

try:
    import feedparser
except ImportError:  # pragma: no cover
    feedparser = None

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
REQUEST_TIMEOUT = 12

SENS_URL = "https://www.sharenet.co.za/v3/sens.php"
DATE_RE = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})")
MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    )
}


def _parse_sens_datetime(text: str):
    m = DATE_RE.search(text or "")
    if not m:
        return None
    hh, mm, dd, mon, yyyy = m.groups()
    month = MONTHS.get(mon[:3].title())
    if month is None:
        return None
    try:
        return datetime(int(yyyy), month, int(dd), int(hh), int(mm))
    except ValueError:
        return None


def _parse_number(text: str):
    if not text:
        return None
    cleaned = text.replace(",", "").replace("%", "").replace("+", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def fetch_sens(symbol: str = None, days: int = 60, max_rows: int = 200) -> pd.DataFrame:
    """SENS headlines for a specific JSE share code (e.g. "NPN"), or the
    market-wide feed if symbol is None. Returns an empty DataFrame (never
    raises) if the page can't be reached or parsed."""
    cols = ["datetime", "code", "headline", "url", "price", "move", "pct_move"]
    params = {}
    if symbol:
        params["sharecode"] = symbol

    try:
        resp = requests.get(SENS_URL, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        print(f"[sens_news] SENS fetch failed: {e}")
        return pd.DataFrame(columns=cols)

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        rows = []
        cutoff = datetime.now() - timedelta(days=days)

        for tr in soup.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue

            # Find the date cell by content, not position -- don't assume it's tds[0].
            dt = None
            date_idx = None
            for i, td in enumerate(tds):
                dt = _parse_sens_datetime(td.get_text(strip=True))
                if dt is not None:
                    date_idx = i
                    break
            if dt is None:
                continue  # not an announcement row (e.g. a header/footer row)
            if dt < cutoff:
                continue

            # The headline link is the one thing we're confident is stable:
            # it points at sens_display.php. Find it by href, not by column
            # index, since the exact column layout wasn't verified live.
            headline_link = tr.find("a", href=lambda h: h and "sens_display" in h)
            if headline_link is not None:
                headline = headline_link.get_text(strip=True)
                href = headline_link.get("href")
                url = urljoin(SENS_URL, href) if href else None
                headline_cell = headline_link.find_parent("td")
                headline_idx = tds.index(headline_cell) if headline_cell in tds else None
                # If the link only wraps part of the headline (e.g. just the
                # company name, with " - Announcement title" as plain text
                # alongside it), prefer the full cell text when it's longer.
                if headline_cell is not None:
                    cell_text = headline_cell.get_text(strip=True)
                    if len(cell_text) > len(headline) + 3:
                        headline = cell_text
            else:
                # Fallback: assume it's the longest-text cell after the date column
                # (headlines are long; code/price cells are short).
                candidates = [(i, td.get_text(strip=True)) for i, td in enumerate(tds) if i != date_idx]
                candidates = [c for c in candidates if c[1]]
                headline_idx, headline = max(candidates, key=lambda c: len(c[1]), default=(None, ""))
                url = None

            # Ticker code: a link to quickshare.php, or the short cell right after the date.
            code_link = tr.find("a", href=lambda h: h and "quickshare" in h)
            if code_link is not None:
                code = code_link.get_text(strip=True)
            elif date_idx is not None and date_idx + 1 < len(tds) and (date_idx + 1) != headline_idx:
                code = tds[date_idx + 1].get_text(strip=True)
            else:
                code = ""

            # Price / move / % move: numeric-looking cells that come after the headline.
            numeric_texts = []
            if headline_idx is not None:
                numeric_texts = [td.get_text(strip=True) for td in tds[headline_idx + 1 :]]
            numeric_texts = [t for t in numeric_texts if t]
            price = _parse_number(numeric_texts[0]) if len(numeric_texts) > 0 else None
            move = _parse_number(numeric_texts[1]) if len(numeric_texts) > 1 else None
            pct_move = _parse_number(numeric_texts[2]) if len(numeric_texts) > 2 else None

            if not headline:
                continue  # nothing useful to show

            rows.append(
                {
                    "datetime": dt,
                    "code": code,
                    "headline": headline,
                    "url": url,
                    "price": price,
                    "move": move,
                    "pct_move": pct_move,
                }
            )
            if len(rows) >= max_rows:
                break

        df = pd.DataFrame(rows, columns=cols)
        if not df.empty:
            df = df.sort_values("datetime", ascending=False).reset_index(drop=True)
        return df
    except Exception as e:
        print(f"[sens_news] SENS parse failed: {e}")
        return pd.DataFrame(columns=cols)


def fetch_news(query: str, days: int = 30, max_items: int = 25) -> pd.DataFrame:
    """Recent news headlines via Google News RSS search. `query` should
    already be specific (e.g. '"Naspers" JSE' or '"MTN Group"')."""
    cols = ["published", "title", "source", "link"]
    if feedparser is None:
        print("[sens_news] feedparser not installed")
        return pd.DataFrame(columns=cols)

    q = quote(f"{query} when:{days}d")
    url = f"https://news.google.com/rss/search?q={q}&hl=en-ZA&gl=ZA&ceid=ZA:en"

    try:
        feed = feedparser.parse(url)
    except Exception as e:
        print(f"[sens_news] news fetch failed: {e}")
        return pd.DataFrame(columns=cols)

    rows = []
    for entry in feed.entries[:max_items]:
        title = entry.get("title", "")
        source = None
        if "source" in entry and isinstance(entry["source"], dict):
            source = entry["source"].get("title")
        if source is None and " - " in title:
            title, source = title.rsplit(" - ", 1)
        published = None
        if getattr(entry, "published_parsed", None):
            published = datetime(*entry.published_parsed[:6])
        rows.append({"published": published, "title": title, "source": source, "link": entry.get("link")})

    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df = df.sort_values("published", ascending=False, na_position="last").reset_index(drop=True)
    return df
