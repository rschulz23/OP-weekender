from __future__ import annotations
"""
Scraper: Serendipity Farm & Vine (serendipityfarmandvine.com/events/)
======================================================================
Uses The Events Calendar (tribe) plugin format — static HTML, no Playwright.
"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz

from .base import BaseScraper, Event

CENTRAL = pytz.timezone("America/Chicago")
URL = "https://www.serendipityfarmandvine.com/events/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}

_TIME_RE = re.compile(r'(\d+:\d+\s*(?:am|pm))', re.IGNORECASE)


def _parse_time(time_str: str) -> tuple[int, int]:
    """Parse '6:00 pm' → (hour, minute) in 24h."""
    m = re.match(r'(\d+):(\d+)\s*(am|pm)', time_str.strip(), re.IGNORECASE)
    if not m:
        return 12, 0
    h, mn, period = int(m.group(1)), int(m.group(2)), m.group(3).lower()
    if period == 'pm' and h != 12:
        h += 12
    elif period == 'am' and h == 12:
        h = 0
    return h, mn


class SerendipityFarmScraper(BaseScraper):
    name = "Serendipity Farm & Vine"

    def fetch(self) -> list[Event]:
        try:
            resp = requests.get(URL, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            self.logger.error(f"Fetch failed: {e}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        events: list[Event] = []

        for article in soup.find_all("article", class_=re.compile(r"tribe-events-calendar-list__event")):
            try:
                title_tag = article.find(class_=re.compile(r"tribe-events-calendar-list__event-title"))
                title = title_tag.get_text(strip=True) if title_tag else "Event"

                # Date from <time datetime="YYYY-MM-DD">
                time_tag = article.find("time", attrs={"datetime": True})
                if not time_tag:
                    continue
                date_str = time_tag["datetime"]  # "2026-09-10"
                dt = datetime.strptime(date_str, "%Y-%m-%d")

                # Time from text e.g. "September 10 @ 6:00 pm-8:00 pm"
                full_text = time_tag.get_text(strip=True)
                times = _TIME_RE.findall(full_text)
                if times:
                    h, mn = _parse_time(times[0])
                    dt = dt.replace(hour=h, minute=mn)
                else:
                    dt = dt.replace(hour=12, minute=0)

                start_date = CENTRAL.localize(dt)

                link_tag = article.find("a", href=True)
                url = link_tag["href"] if link_tag else URL

                img = article.find("img")
                image_url = img.get("src") if img else None

                events.append(Event(
                    title=title,
                    start_date=start_date,
                    end_date=None,
                    location="Serendipity Farm & Vine, 4674 W 183rd St, Stilwell, KS",
                    city="Stilwell",
                    description="",
                    url=url,
                    source="Serendipity Farm & Vine",
                    image_url=image_url,
                    cost=None,
                    category="Food & Drink",
                ))
            except Exception as e:
                self.logger.warning(f"Parse error: {e}")

        self.logger.info(f"Fetched {len(events)} Serendipity Farm events")
        return events
