from __future__ import annotations
"""
Scraper: KC Live 411 — Johnson County Live Music
==================================================
Parses live music events for Johnson County KS, filtered to
Overland Park, Leawood, Lenexa, Olathe, and Shawnee only.

Structure: each event is a div.frm12 containing:
  - span[data-date]       date "09/11/26"
  - text                  time range "7:30pm-???"
  - span[data-performer]  artist name
  - span[data-venue]      venue name
  - span[data-city]       city name
"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz

from .base import BaseScraper, Event

CENTRAL = pytz.timezone("America/Chicago")
URL = "https://kclive411.com/live-music-by-geographic-area/live-music-in-the-johnson-county-kansas-area/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}

ALLOWED_CITIES = {
    "overland park", "leawood", "lenexa", "olathe", "shawnee"
}

_TIME_RE = re.compile(r'(\d{1,2}(?::\d{2})?(?:am|pm))', re.IGNORECASE)


def _parse_dt(date_str: str, time_str: str) -> datetime | None:
    """Parse date '09/11/26' and time '7:30pm' into Central datetime."""
    try:
        dt = datetime.strptime(date_str, "%m/%d/%y")
    except ValueError:
        return None

    m = _TIME_RE.search(time_str)
    if m:
        raw = m.group(1)
        period = 'pm' if 'pm' in raw.lower() else 'am'
        raw_digits = re.sub(r'[apm]+', '', raw, flags=re.IGNORECASE)
        parts = raw_digits.split(':')
        h = int(parts[0])
        mn = int(parts[1]) if len(parts) > 1 else 0
        if period == 'pm' and h != 12:
            h += 12
        elif period == 'am' and h == 12:
            h = 0
        dt = dt.replace(hour=h, minute=mn)
    else:
        dt = dt.replace(hour=20, minute=0)  # default 8 PM

    return CENTRAL.localize(dt)


class KCLiveMusicScraper(BaseScraper):
    name = "KC Live Music"

    def fetch(self) -> list[Event]:
        try:
            resp = requests.get(URL, headers=HEADERS, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            self.logger.error(f"Fetch failed: {e}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        events: list[Event] = []
        now = datetime.now(CENTRAL)

        for div in soup.find_all("div", class_="frm12"):
            try:
                date_span = div.find("span", attrs={"data-date": True})
                city_span = div.find("span", attrs={"data-city": True})
                if not date_span or not city_span:
                    continue

                city = city_span.get_text(strip=True)
                if city.lower() not in ALLOWED_CITIES:
                    continue

                date_str = date_span["data-date"]  # "09/11/26"
                div_text = div.get_text(" ", strip=True)

                # Extract time from text between date and performer
                time_match = re.search(r'\d{1,2}(?::\d{2})?(?:am|pm)', div_text, re.IGNORECASE)
                time_str = time_match.group(0) if time_match else ""

                start = _parse_dt(date_str, time_str)
                if not start or start < now:
                    continue

                performer_span = div.find("span", attrs={"data-performer": True})
                venue_span = div.find("span", attrs={"data-venue": True})

                performer = performer_span.get_text(strip=True) if performer_span else "Live Music"
                venue = venue_span.get_text(strip=True) if venue_span else "Local Venue"

                # Skip open mics and jam sessions
                if re.search(r'open\s*mic|jam\s*(or|session|night)', performer, re.IGNORECASE):
                    continue

                # Skip "Unknown performer"
                if "unknown" in performer.lower():
                    continue

                title = f"{performer} @ {venue}"
                location = f"{venue}, {city}, KS"

                # Get description/genre from remaining text
                desc_parts = div_text.split('|')
                description = desc_parts[-1].strip() if len(desc_parts) > 1 else ""
                description = re.sub(r'(Map|Phone|Details|Directions)', '', description).strip()

                events.append(Event(
                    title=title,
                    start_date=start,
                    end_date=None,
                    location=location,
                    city=city,
                    description=description[:200],
                    url=URL,
                    source="KC Live Music",
                    image_url=None,
                    cost=None,
                    category="Music & Entertainment",
                ))
            except Exception as e:
                self.logger.warning(f"Parse error: {e}")

        self.logger.info(f"Fetched {len(events)} KC Live Music events in target cities")
        return events
