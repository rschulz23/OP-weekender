from __future__ import annotations
"""
Scraper: The Truman (thetrumankc.com/events)
=============================================
The Truman sells exclusively through AXS, so it never appears in the
Ticketmaster feed. Its own listing page is static HTML — each show is a
``.event_list .entry`` block carrying title, tour, support, date and time.
"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz

from .base import BaseScraper, Event, HEADERS

CENTRAL = pytz.timezone("America/Chicago")
URL = "https://www.thetrumankc.com/events"

_TIME_RE = re.compile(r'(\d{1,2}:\d{2}\s*[AP]M)', re.IGNORECASE)


class TrumanScraper(BaseScraper):
    name = "The Truman"

    def fetch(self) -> list[Event]:
        try:
            resp = requests.get(URL, headers=HEADERS, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            self.logger.error(f"Fetch failed: {e}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        events: list[Event] = []
        now = datetime.now(CENTRAL)

        for entry in soup.select(".event_list .entry"):
            try:
                title_tag = entry.select_one(".title h3 a") or entry.select_one(".title h3")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)

                date_tag = entry.select_one(".date-time-container .date")
                if not date_tag:
                    continue
                # e.g. "Fri, Sep 11, 2026"
                date_str = date_tag.get_text(strip=True)
                try:
                    dt = datetime.strptime(date_str, "%a, %b %d, %Y")
                except ValueError:
                    self.logger.warning(f"Unparsed date {date_str!r} for {title!r}")
                    continue

                time_tag = entry.select_one(".date-time-container .time")
                m = _TIME_RE.search(time_tag.get_text(" ", strip=True)) if time_tag else None
                if m:
                    t = datetime.strptime(m.group(1).upper().replace(" ", ""), "%I:%M%p")
                    dt = dt.replace(hour=t.hour, minute=t.minute)
                else:
                    dt = dt.replace(hour=20, minute=0)

                start_date = CENTRAL.localize(dt)
                if start_date < now:
                    continue

                # Tour name and supporting acts flesh out the listing
                parts = []
                for sel in (".title .tour", ".title .supporting"):
                    tag = entry.select_one(sel)
                    if tag and tag.get_text(strip=True):
                        parts.append(tag.get_text(strip=True))
                description = " — ".join(parts)

                link = entry.select_one(".title h3 a[href]")
                img = entry.select_one(".thumb img[src]")

                events.append(Event(
                    title=title,
                    start_date=start_date,
                    end_date=None,
                    location="The Truman, 601 E Truman Rd, Kansas City, MO",
                    city="Kansas City",
                    description=description,
                    url=link["href"] if link else URL,
                    source="The Truman",
                    image_url=img["src"] if img else None,
                    cost=None,
                    category="Music & Entertainment",
                ))
            except Exception as e:
                self.logger.warning(f"Parse error: {e}")

        events.sort(key=lambda e: e.start_date)
        self.logger.info(f"Fetched {len(events)} The Truman events")
        return events
