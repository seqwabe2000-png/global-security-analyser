"""
Diagnostic-only: dumps the raw HTML structure of a few SENS announcement
rows from Sharenet so the parsing logic in src/sens_news.py can be fixed to
match reality. The dev sandbox this app was built in has no route to
sharenet.co.za, so the parser was written from a secondhand description of
the page's markup -- if SENS headlines are showing up blank in the app,
this script tells us exactly what's actually there.

Usage:
    python3 scripts/debug_sens_html.py

Then share the output -- it doesn't contain anything sensitive, just public
SENS listing markup.
"""
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

url = "https://www.sharenet.co.za/v3/sens.php"
resp = requests.get(url, params={"sharecode": "NPN"}, headers=HEADERS, timeout=12)
print(f"HTTP {resp.status_code}, {len(resp.text)} bytes\n")

soup = BeautifulSoup(resp.text, "html.parser")

print("=" * 70)
print("All <table> elements found and their row counts:")
tables = soup.find_all("table")
for i, t in enumerate(tables):
    rows = t.find_all("tr")
    print(f"  table[{i}]: {len(rows)} rows, classes={t.get('class')}, id={t.get('id')}")

print()
print("=" * 70)
print("First 5 <tr> that contain a link to sens_display.php (the likely announcement rows):")
count = 0
for tr in soup.find_all("tr"):
    if tr.find("a", href=lambda h: h and "sens_display" in h):
        count += 1
        print(f"\n--- row {count} ---")
        print(tr.prettify()[:2000])
        if count >= 5:
            break

if count == 0:
    print("No rows with a sens_display.php link found at all.")
    print("\nFirst 3000 characters of the raw page body, for a manual look:")
    body = soup.find("body")
    print(str(body)[:3000] if body else resp.text[:3000])
