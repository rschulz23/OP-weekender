from __future__ import annotations
"""
Scraper: Guitars & Cadillacs Weekly Bands (guitarsandcadillacs.com/weekly-bands/)
==================================================================================
Schedule is listed as h2/h3 headings in the format:
  "Band Name - Fri & Sat - September 11th & 12th"
Creates two events per entry (Friday and Saturday night).
"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz

from .base import BaseScraper, Event

CENTRAL = pytz.timezone("America/Chicago")
URL = "https://www.guitarsandcadillacs.com/weekly-bands/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}

_MONTHS = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
}

# Matches "September 11th & 12th" or "September 11th"
_DATE_RE = re.compile(
    r'(January|February|March|April|May|June|July|August|September|October|November|December)'
    r'\s+(\d{1,2})(?:st|nd|rd|th)?'
    r'(?:\s*&\s*(\d{1,2})(?:st|nd|rd|th)?)?',
    re.IGNORECASE,
)


def _make_dt(month: int, day: int) -> datetime | None:
    now = datetime.now()
    year = now.year
    try:
        dt = datetime(year, month, day, 21, 0)  # default 9 PM show time
        if dt < now:
            dt = dt.replace(year=year + 1)
        return CENTRAL.localize(dt)
    except ValueError:
        return None


class GuitarsCadillacsScraper(BaseScraper):
    name = "Guitars & Cadillacs"

    def fetch(self) -> list[Event]:
        try:
            resp = requests.get(URL, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            self.logger.error(f"Fetch failed: {e}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        events: list[Event] = []
        now = datetime.now(CENTRAL)

        for heading in soup.find_all(['h2', 'h3', 'h4']):
            text = heading.get_text(strip=True)
            m = _DATE_RE.search(text)
            if not m:
                continue

            month_num = _MONTHS.get(m.group(1).lower())
            if not month_num:
                continue

            # Band name is everything before the first " - "
            band = re.split(r'\s*[-–]\s*', text)[0].strip()
            if not band or 'email' in band.lower():
                continue

            fri_day = int(m.group(2))
            sat_day = int(m.group(3)) if m.group(3) else fri_day + 1

            for day in (fri_day, sat_day):
                start = _make_dt(month_num, day)
                if not start or start < now:
                    continue
                events.append(Event(
                    title=f"Live Music: {band}",
                    start_date=start,
                    end_date=None,
                    location="Guitars & Cadillacs, 8601 W 135th St, Overland Park, KS",
                    city="Overland Park",
                    description="Live music at Guitars & Cadillacs",
                    url=URL,
                    source="Guitars & Cadillacs",
                    image_url=None,
                    cost=None,
                    category="Music & Entertainment",
                ))

        self.logger.info(f"Fetched {len(events)} Guitars & Cadillacs events")
        return events
