from __future__ import annotations
"""
Scraper: City of Shawnee event calendar (CivicEngage)
======================================================
Shawnee is the only Johnson County city left with a calendar that can be read
without defeating bot protection:

  - Overland Park and Leawood have their own scrapers, which handle the JS
    rendering and Cloudflare blocking those sites now require.
  - Olathe serves a bot challenge on both olatheks.gov and olathe.org that a
    real browser does not clear.
  - Lenexa blocks scripted requests and its own calendar URL 404s.

Events are read from schema.org microdata (itemprop="startDate"), which is
more stable than the surrounding markup.
"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from dateutil import parser as dateparser
import pytz

from .base import BaseScraper, Event, HEADERS

CENTRAL = pytz.timezone("America/Chicago")

SHAWNEE_CONFIG = {
    "name": "Shawnee",
    "url": "https://www.cityofshawnee.org/calendar",
    "base_url": "https://www.cityofshawnee.org",
    "city": "Shawnee",
}


def _parse_civicengage(soup: BeautifulSoup, config: dict) -> list[Event]:
    """
    Parser for CivicEngage city websites.
    Uses schema.org itemprop="startDate" for reliable date parsing.

    Handles two CivicEngage layouts:
    - List view (JCPRD): events are in <li> elements
    - Month/calendar view (Shawnee, Leawood): events are in <div class="monthItem">
    """
    events = []
    city = config["city"]
    base_url = config["base_url"]
    source = f"City of {city}"

    # Detect layout: prefer monthItem divs, fall back to li
    containers = soup.find_all("div", class_="monthItem") or soup.find_all("li")

    for li in containers:
        try:
            # Title — CivicEngage: <h3 id="eventTitle_*"> or <span itemprop="name">
            title_h = li.find(["h3", "h2"], id=lambda x: x and x.startswith("eventTitle_"))
            title_span = li.find("span", itemprop="name")
            title_tag = title_h or title_span
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            if len(title) < 3:
                continue

            # URL — CivicEngage: <a id="calendarEvent_*"> or first <a>
            link_tag = li.find("a", id=lambda x: x and x.startswith("calendarEvent")) or li.find("a", href=True)
            href = link_tag.get("href", "") if link_tag else ""
            url = (base_url + href) if href.startswith("/") else (href or config["url"])

            # Date — schema.org startDate (most reliable)
            start_span = li.find("span", itemprop="startDate")
            if start_span:
                date_str = start_span.get_text(strip=True)
                start_date = dateparser.parse(date_str)
                if start_date and start_date.tzinfo is None:
                    start_date = CENTRAL.localize(start_date)
            else:
                date_div = li.find("div", class_="date") or li.find(class_=re.compile(r"date|when", re.I))
                date_str = date_div.get_text(strip=True) if date_div else ""
                start_date = dateparser.parse(date_str, fuzzy=True) if date_str else datetime.now(CENTRAL)
                if start_date and start_date.tzinfo is None:
                    start_date = CENTRAL.localize(start_date)

            # Location
            loc_tag = li.find("span", itemprop="location")
            if loc_tag:
                name_tag = loc_tag.find("span", itemprop="name")
                location = name_tag.get_text(strip=True) if name_tag else loc_tag.get_text(strip=True)
            else:
                loc_div = li.find("div", class_="eventLocation")
                location = loc_div.get_text(" ", strip=True).lstrip("@ ") if loc_div else f"{city}, KS"

            # City from schema address
            city_tag = li.find("span", itemprop="addressLocality")
            resolved_city = city_tag.get_text(strip=True) if city_tag else city

            # Description
            desc_tag = li.find("p", itemprop="description") or li.find("p")
            description = desc_tag.get_text(" ", strip=True)[:500] if desc_tag else ""

            events.append(Event(
                title=title,
                start_date=start_date,
                end_date=None,
                location=location,
                city=resolved_city,
                description=description,
                url=url,
                source=source,
            ))
        except Exception:
            pass

    return events


class ShawneeCalendarScraper(BaseScraper):
    name = "City of Shawnee"

    def fetch(self) -> list[Event]:
        try:
            resp = requests.get(SHAWNEE_CONFIG["url"], headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            self.logger.warning(f"Fetch failed: {e}")
            return []

        events = _parse_civicengage(BeautifulSoup(resp.text, "lxml"), SHAWNEE_CONFIG)
        self.logger.info(f"Parsed {len(events)} events from Shawnee")
        return events
