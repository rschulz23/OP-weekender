from __future__ import annotations
"""
Scraper: Visit Overland Park
Source: https://www.visitoverlandpark.com/events/
Method: Algolia Search API (no browser/Playwright needed)

The events page loads its listing via Algolia's search API:
  App ID:  EYQHJ2IY2M
  API Key: c6d5977cb5cd80c09abfd2a7e5d9e88b  (public read-only key embedded in page JS)
  Index:   prod-visit-overland-park-listings

Events have startDate/endDate as Unix timestamps, making date-range
filtering precise and reliable. This is the highest-quality source —
curated by the OP tourism board.
"""

import requests
from datetime import datetime
from dateutil import parser as dateparser
import pytz

from .base import BaseScraper, Event, HEADERS

CENTRAL   = pytz.timezone("America/Chicago")
BASE_URL  = "https://www.visitoverlandpark.com"
ALGOLIA_APP_ID  = "EYQHJ2IY2M"
ALGOLIA_API_KEY = "c6d5977cb5cd80c09abfd2a7e5d9e88b"
ALGOLIA_INDEX   = "prod-visit-overland-park-listings"
ALGOLIA_URL     = f"https://{ALGOLIA_APP_ID.lower()}-dsn.algolia.net/1/indexes/*/queries"

# Base Algolia filter — all event categories, all OP regions
BASE_FILTER = (
    'calendarName:"Default Calendar" '
    'AND (NOT isPrimaryEvent:false)'
)


class VisitOverlandParkScraper(BaseScraper):
    name = "VisitOverlandPark"

    def fetch(self) -> list[Event]:
        return self._fetch_all()

    def _fetch_all(self) -> list[Event]:
        """Fetch all upcoming events (no date filter) — aggregator handles weekend filtering."""
        payload = {
            "requests": [{
                "indexName": ALGOLIA_INDEX,
                "params": f"filters={requests.utils.quote(BASE_FILTER)}&hitsPerPage=100&attributesToRetrieve=title,uri,startDate,endDate,isAllDay,address,content,primaryImageUrl,website",
            }]
        }

        resp = requests.post(
            ALGOLIA_URL,
            headers={
                "X-Algolia-Application-Id": ALGOLIA_APP_ID,
                "X-Algolia-API-Key": ALGOLIA_API_KEY,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()

        hits = resp.json()["results"][0]["hits"]
        self.logger.info(f"Algolia returned {len(hits)} hits")

        events = []
        for hit in hits:
            event = self._hit_to_event(hit)
            if event:
                events.append(event)

        return events

    def _hit_to_event(self, hit: dict) -> Event | None:
        try:
            title = hit.get("title", "").strip()
            if not title:
                return None

            # URL — prefer external website, fall back to VisitOP page
            url = hit.get("website") or (BASE_URL + hit.get("uri", ""))

            # Dates — Unix timestamps
            # NOTE: The VisitOP CMS stores timestamps with a known offset bug:
            # local times are written into the DB as if they were UTC.
            # e.g. "7:30 AM CDT" is stored as Unix(07:30 UTC) not Unix(12:30 UTC).
            # Fix: read the raw UTC wall-clock value and localize it as Central,
            # rather than converting UTC→Central (which would subtract 5/6 hours).
            start_ts = hit.get("startDate")
            end_ts   = hit.get("endDate")
            start_date = CENTRAL.localize(datetime.utcfromtimestamp(start_ts)) if start_ts else datetime.now(CENTRAL)
            end_date   = CENTRAL.localize(datetime.utcfromtimestamp(end_ts))   if end_ts   else None

            # Address — stored as a list: ["Venue Name", "Street", "City, State ZIP"]
            addr = hit.get("address", [])
            if isinstance(addr, list) and addr:
                venue   = addr[0] if len(addr) > 0 else ""
                city_st = addr[-1] if len(addr) > 1 else "Overland Park, KS"
                location = f"{venue}, {city_st}".strip(", ")
                # Extract just the city name for the Event.city field
                city = city_st.split(",")[0].strip() if "," in city_st else "Overland Park"
            else:
                location = "Overland Park, KS"
                city     = "Overland Park"

            # Description from content field
            description = hit.get("content", "")[:500]

            # Image
            image_url = hit.get("primaryImageUrl")

            return Event(
                title=title,
                start_date=start_date,
                end_date=end_date,
                location=location,
                city=city,
                description=description,
                url=url,
                source="Visit Overland Park",
                image_url=image_url,
            )
        except Exception as e:
            self.logger.warning(f"Hit parse error: {e}")
            return None
