from __future__ import annotations
"""
Scraper: Ticketmaster Discovery API
====================================
Covers all KC-area venues and sports teams that sell through Ticketmaster.

Requires env var: TICKETMASTER_API_KEY
Get a free key at: https://developer.ticketmaster.com

Venue IDs (concerts):
  50225  T-Mobile Center
  49168  Azura Amphitheater (Bonner Springs)
  49175  Starlight Theatre
  49686  Uptown Theater
  50599  KC Live! at Power & Light
  50571  Kauffman Center for the Performing Arts
  50295  GrindersKC
  341872 The Truman KC
  49188  Folly Theater
  50304  Kansas Speedway
  50600  The Midland Theatre (also on AXS)

Sports team attraction IDs:
  805955  Kansas City Chiefs
  805956  Kansas City Royals
  2389635 Kansas City Mavericks
  835909  Kansas City Comets
  2777162 Kansas City Monarchs (partial — some games on own platform)
"""

import os
import requests
from datetime import datetime, timezone, timedelta
import pytz

from .base import BaseScraper, Event

CENTRAL = pytz.timezone("America/Chicago")

TM_BASE = "https://app.ticketmaster.com/discovery/v2"

VENUE_IDS = [
    "KovZpZAE7eeA",  # T-Mobile Center
    "KovZpa3sfe",    # Azura Amphitheater
    "KovZpZAF7EaA",  # Starlight Theatre
    "KovZpa3sre",    # Uptown Theater
    "KovZpZAE7eAA",  # KC Live!
    "KovZpaF1me",    # Kauffman Center
    "KovZpZAaJJnA",  # Grinders KC
    "KovZ917AQI8",   # The Truman
    "KovZpaoXie",    # Folly Theater
    "KovZpZAaEeIA",  # Kansas Speedway
    "KovZpZAEdaIA",  # The Midland Theatre
]

ATTRACTION_IDS = [
    "K8vZ9171oMf",  # Kansas City Chiefs
    "K8vZ9171oF7",  # Kansas City Royals
    "K8vZ917p6x0",  # Kansas City Mavericks
    "K8vZ91719vV",  # Kansas City Comets
]

# Maps venue ID → friendly display name
VENUE_NAMES = {
    "KovZpZAE7eeA":  "T-Mobile Center",
    "KovZpa3sfe":    "Azura Amphitheater",
    "KovZpZAF7EaA":  "Starlight Theatre",
    "KovZpa3sre":    "Uptown Theater",
    "KovZpZAE7eAA":  "KC Live!",
    "KovZpaF1me":    "Kauffman Center",
    "KovZpZAaJJnA":  "Grinders KC",
    "KovZ917AQI8":   "The Truman",
    "KovZpaoXie":    "Folly Theater",
    "KovZpZAaEeIA":  "Kansas Speedway",
    "KovZpZAEdaIA":  "The Midland Theatre",
}


class TicketmasterScraper(BaseScraper):
    name = "Ticketmaster"

    def fetch(self) -> list[Event]:
        api_key = os.environ.get("TICKETMASTER_API_KEY")
        if not api_key:
            self.logger.warning("TICKETMASTER_API_KEY not set — skipping Ticketmaster scraper")
            return []

        events: list[Event] = []
        # Fetch venue events (concerts) + attraction events (sports) separately
        events.extend(self._fetch_venues(api_key))
        events.extend(self._fetch_attractions(api_key))
        self.logger.info(f"Fetched {len(events)} total events from Ticketmaster")
        return events

    def _date_window(self) -> tuple[str, str]:
        """Return ISO 8601 UTC strings for the upcoming Sat 00:00 → Sun 23:59 CDT."""
        now    = datetime.now(CENTRAL)
        days   = (5 - now.weekday()) % 7
        sat    = now + timedelta(days=days)
        sun    = sat + timedelta(days=1)
        # Convert midnight CDT → UTC for API
        sat_utc = CENTRAL.localize(datetime(sat.year, sat.month, sat.day)).astimezone(timezone.utc)
        sun_utc = CENTRAL.localize(datetime(sun.year, sun.month, sun.day, 23, 59, 59)).astimezone(timezone.utc)
        return (
            sat_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            sun_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    def _fetch_venues(self, api_key: str) -> list[Event]:
        start, end = self._date_window()
        params = {
            "apikey":        api_key,
            "venueId":       ",".join(VENUE_IDS),
            "startDateTime": start,
            "endDateTime":   end,
            "size":          200,
            "countryCode":   "US",
        }
        return self._call_api(params, source_label="venue")

    def _fetch_attractions(self, api_key: str) -> list[Event]:
        start, end = self._date_window()
        params = {
            "apikey":        api_key,
            "attractionId":  ",".join(ATTRACTION_IDS),
            "startDateTime": start,
            "endDateTime":   end,
            "size":          200,
            "countryCode":   "US",
        }
        return self._call_api(params, source_label="sports")

    def _call_api(self, params: dict, source_label: str) -> list[Event]:
        try:
            resp = requests.get(
                f"{TM_BASE}/events.json",
                params=params,
                timeout=15,
            )
            if resp.status_code == 401:
                self.logger.error("Ticketmaster API key invalid or missing")
                return []
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            self.logger.error(f"API call failed ({source_label}): {e}")
            return []

        embedded = data.get("_embedded", {})
        raw_events = embedded.get("events", [])
        self.logger.info(f"  {source_label}: {len(raw_events)} events from TM API")

        events = []
        for raw in raw_events:
            event = self._parse_event(raw)
            if event:
                events.append(event)
        return events

    def _parse_event(self, raw: dict) -> Event | None:
        try:
            title = raw.get("name", "").strip()
            url   = raw.get("url", "")

            # Date/time
            dates      = raw.get("dates", {})
            start_info = dates.get("start", {})
            date_str   = start_info.get("dateTime")   # ISO 8601 UTC e.g. "2026-06-21T01:00:00Z"
            if not date_str:
                # date-only fallback
                local_date = start_info.get("localDate", "")
                local_time = start_info.get("localTime", "00:00:00")
                date_str = f"{local_date}T{local_time}"

            try:
                if date_str.endswith("Z"):
                    dt_utc = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    start_date = dt_utc.astimezone(CENTRAL)
                else:
                    start_date = CENTRAL.localize(datetime.fromisoformat(date_str))
            except Exception:
                return None

            # Venue
            venues_list = raw.get("_embedded", {}).get("venues", [])
            if venues_list:
                v = venues_list[0]
                venue_id   = v.get("id", "")
                venue_name = VENUE_NAMES.get(venue_id, v.get("name", "Kansas City"))
                city       = v.get("city", {}).get("name", "Kansas City")
                state      = v.get("state", {}).get("stateCode", "MO")
                address    = v.get("address", {}).get("line1", "")
                location   = f"{venue_name}, {city}, {state}"
                if address:
                    location = f"{venue_name} — {address}, {city}"
            else:
                venue_name = "Kansas City"
                location   = "Kansas City, MO"
                city       = "Kansas City"

            # Description / genre
            classifications = raw.get("classifications", [])
            genre = ""
            if classifications:
                seg   = classifications[0].get("segment", {}).get("name", "")
                gen   = classifications[0].get("genre", {}).get("name", "")
                genre = f"{seg} — {gen}" if gen and gen != "Undefined" else seg

            description = genre

            # Price range (use as cost hint)
            price_ranges = raw.get("priceRanges", [])
            cost = None
            if price_ranges:
                lo = price_ranges[0].get("min")
                hi = price_ranges[0].get("max")
                if lo is not None:
                    cost = f"From ${lo:.0f}" if lo != hi else f"${lo:.0f}"

            # Image
            images   = raw.get("images", [])
            image_url = None
            # Prefer landscape 16:9 images, width >= 640
            for img in images:
                if img.get("ratio") == "16_9" and img.get("width", 0) >= 640:
                    image_url = img.get("url")
                    break
            if not image_url and images:
                image_url = images[0].get("url")

            return Event(
                title=title,
                start_date=start_date,
                end_date=None,
                location=location,
                city=city,
                description=description,
                url=url,
                source=venue_name,
                image_url=image_url,
                cost=cost,
            )
        except Exception as e:
            self.logger.warning(f"Event parse error: {e}")
            return None
