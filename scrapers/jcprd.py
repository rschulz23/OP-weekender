from __future__ import annotations
"""
Scraper: Johnson County Park & Recreation District (JCPRD)
Source: https://jcprd.com/calendar.aspx?view=list&CID=0
Method: HTML scraping of CivicEngage platform using schema.org microdata

JCPRD covers the entire county — concerts in the park, family events,
Movies in the Park, Theatre in the Park, nature programs, etc.
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
from dateutil import parser as dateparser
import pytz

from .base import BaseScraper, Event, HEADERS

CENTRAL = pytz.timezone("America/Chicago")
# List view is much easier to scrape than the default month/calendar view
CALENDAR_URL = "https://jcprd.com/calendar.aspx?view=list&CID=0"


class JCPRDScraper(BaseScraper):
    name = "JCPRD"

    def fetch(self) -> list[Event]:
        resp = requests.get(CALENDAR_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        return self._parse(soup)

    def _parse(self, soup: BeautifulSoup) -> list[Event]:
        """
        CivicEngage list view: each event is a <li> containing schema.org microdata.
        Key selectors:
          - Title:      <a id="eventTitle_*">
          - Start date: <span itemprop="startDate">  (ISO 8601)
          - Location:   <span itemprop="name"> inside <span itemprop="location">
          - Description: <p itemprop="description">
        """
        events = []

        for li in soup.find_all("li"):
            try:
                # Title + URL
                title_tag = li.find("a", id=lambda x: x and x.startswith("eventTitle_"))
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                href = title_tag.get("href", "")
                url = ("https://jcprd.com" + href) if href.startswith("/") else href

                # Date — schema.org startDate
                start_span = li.find("span", itemprop="startDate")
                if start_span:
                    date_str = start_span.get_text(strip=True)
                    start_date = dateparser.parse(date_str)
                    if start_date and start_date.tzinfo is None:
                        start_date = CENTRAL.localize(start_date)
                else:
                    # Fallback: read the .date div text
                    date_div = li.find("div", class_="date")
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
                    location = loc_div.get_text(" ", strip=True).lstrip("@ ") if loc_div else "Johnson County, KS"

                # City from address
                city_tag = li.find("span", itemprop="addressLocality")
                city = city_tag.get_text(strip=True) if city_tag else "Johnson County"

                # Description
                desc_tag = li.find("p", itemprop="description") or li.find("p")
                description = desc_tag.get_text(" ", strip=True)[:500] if desc_tag else ""

                events.append(Event(
                    title=title,
                    start_date=start_date,
                    end_date=None,
                    location=location,
                    city=city,
                    description=description,
                    url=url,
                    source="JCPRD",
                    tags=["parks", "recreation", "family"],
                ))
            except Exception as e:
                self.logger.warning(f"Parse error: {e}")

        self.logger.info(f"Parsed {len(events)} events")
        return events
