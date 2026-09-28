"""
Sanity check that SENS scraping (Sharenet) and news fetching (Google News
RSS) work from wherever you're running this. Both were built without a live
connection to test against (the dev sandbox has no route to either site),
so this is the first thing to run after installing requirements.

Usage:
    python3 scripts/test_sens_connection.py

If SENS returns 0 rows: open https://www.sharenet.co.za/v3/sens.php in a
browser and compare its HTML structure (right-click -> Inspect on a
headline row) against the parsing logic in src/sens_news.py:fetch_sens --
Sharenet is under no obligation to keep their markup stable, and this
scraper will need a small patch if they change it (the row-detection logic
keys off finding "HH:MM - DD Mon YYYY" text in the first <td> of a <tr>,
so a restructure that moves the date elsewhere will need that regex/index
updated).
"""
import sys

sys.path.insert(0, ".")

from src import sens_news

print("Testing SENS scraping (Sharenet, no login)...")
sens = sens_news.fetch_sens("NPN", days=90)
if sens.empty:
    print("  0 rows returned -- either no announcements in the window, or the scraper needs")
    print("  updating for a markup change. See this script's docstring.")
else:
    print(f"  OK: {len(sens)} SENS rows for NPN in the last 90 days. Most recent:")
    for _, r in sens.head(3).iterrows():
        print(f"    {r['datetime']}  {r['code']}  {r['headline'][:70]}")

print("\nTesting news RSS (Google News)...")
news = sens_news.fetch_news('"Naspers" JSE', days=30)
if news.empty:
    print("  0 articles returned -- check your internet connection, or that")
    print("  news.google.com is reachable from this network.")
else:
    print(f"  OK: {len(news)} articles. Most recent:")
    for _, r in news.head(3).iterrows():
        print(f"    {r['published']}  {r['title'][:70]}  ({r['source']})")

print("\nDone. Both sources are best-effort scrapes (see README) -- partial")
print("results (one working, one not) are still useful; fix or report the failing one.")
