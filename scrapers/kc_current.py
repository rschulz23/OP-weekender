from __future__ import annotations
"""
Scraper: Kansas City Current (kansascitycurrent.com/schedule)
=============================================================
The schedule page is JS-rendered. Uses Playwright to load the page,
then parses match-wrap elements. Opponent name comes from the team logo
img alt attribute. Skips finished matches (class="match-finished").
"""

import re
from bs4 import BeautifulSoup
from datetime import datetime
import pytz

from .base import BaseScraper, Event

CENTRAL = pytz.timezone("America/Chicago")
URL = "https://www.kansascitycurrent.com/schedule"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Strips trailing " Logo" (but not " FC Logo") from img alt text
_LOGO_SUFFIX = re.compile(r'\s+Logo$', re.IGNORECASE)

# Maps abbreviated month names (from the site) to month numbers
_MONTHS = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}

# Parses "SEP 11" or "Sep 4" → (month_num, day)
_DATE_RE = re.compile(r'([A-Za-z]{3})\s+(\d{1,2})', re.IGNORECASE)
# Parses "9:00 PM CT" → time tuple
_TIME_RE = re.compile(r'(\d{1,2}):(\d{2})\s*(AM|PM)', re.IGNORECASE)


def _parse_match_date(date_text: str, time_text: str) -> datetime | None:
    dm = _DATE_RE.search(date_text)
    if not dm:
        return None
    month = _MONTHS.get(dm.group(1).lower())
    day = int(dm.group(2))
    if not month:
        return None

    # Determine year: if month is before current month, it's next year
    now = datetime.now(CENTRAL)
    year = now.year
    if month < now.month or (month == now.month and day < now.day):
        year += 1

    hour, minute = 12, 0
    tm = _TIME_RE.search(time_text)
    if tm:
        hour = int(tm.group(1))
        minute = int(tm.group(2))
        if tm.group(3).upper() == 'PM' and hour != 12:
            hour += 12
        elif tm.group(3).upper() == 'AM' and hour == 12:
            hour = 0

    try:
        dt = datetime(year, month, day, hour, minute)
        return CENTRAL.localize(dt)
    except ValueError:
        return None


class KCCurrentScraperNew(BaseScraper):
    name = "KC Current"

    def fetch(self) -> list[Event]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.logger.warning("Playwright not installed — skipping KC Current")
            return []

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_context(user_agent=UA).new_page()
                page.goto(URL, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(5000)
                html = page.content()
                browser.close()
        except Exception as e:
            self.logger.error(f"Playwright load failed: {e}")
            return []

        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []
        now = datetime.now(CENTRAL)

        for match in soup.find_all(class_="match-wrap"):
            # Skip already-finished games
            if "match-finished" in (match.get("class") or []):
                continue

            date_tag = match.find("p", class_="match-date")
            time_tag = match.find("p", class_="match-time")
            if not date_tag:
                continue

            date_text = date_tag.get_text(" ", strip=True)
            time_text = time_tag.get_text(strip=True) if time_tag else ""

            # Skip multi-day playoff windows (e.g. "Nov 6-8") — no specific game date yet
            if re.search(r'\d+-\d+', date_text):
                continue

            start = _parse_match_date(date_text, time_text)
            if not start or start < now:
                continue

            # Opponent from team logo img alt
            img = match.find("img", alt=True)
            opp_raw = img["alt"] if img else "TBD"
            opponent = _LOGO_SUFFIX.sub("", opp_raw).strip()
            if not opponent or opponent == "TBD":
                continue

            comp_tag = match.find("p", class_="match-competition")
            comp = comp_tag.get_text(strip=True) if comp_tag else "NWSL"

            loc_tag = match.find(class_="match-interaction-location")
            if loc_tag:
                # The tag contains two text nodes (venue and city) separated by a newline/child.
                # Using '|' as separator gives us "PayPal Park|San Jose, CA" cleanly.
                parts = [p.strip() for p in loc_tag.get_text("|", strip=True).replace("\xa0", " ").split("|") if p.strip()]
                loc_text = ", ".join(parts) if len(parts) > 1 else parts[0] if parts else "CPKC Stadium, Kansas City, MO"
            else:
                loc_text = "CPKC Stadium, Kansas City, MO"

            title = f"KC Current vs {opponent}"

            events.append(Event(
                title=title,
                start_date=start,
                end_date=None,
                location=loc_text,
                city="Kansas City",
                description=comp,
                url=URL,
                source="KC Current",
                image_url=None,
                cost=None,
                category="Sports & Fitness",
            ))

        self.logger.info(f"Fetched {len(events)} KC Current games")
        return events
