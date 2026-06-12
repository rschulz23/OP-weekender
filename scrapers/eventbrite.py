from __future__ import annotations
"""
Scraper: Eventbrite — Overland Park / Johnson County, KS
Source: https://www.eventbrite.com/d/ks--overland-park/events/
Method: HTML scraping via httpx with browser-like headers

API NOTE: Eventbrite deprecated their public events/search API in 2019.
Their API token is only useful for managing your own organization's events.
This scraper uses the public HTML listing pages instead.

Eventbrite pages are server-side rendered for the initial listing (the
event cards are in a <script type="application/ld+json"> JSON-LD block),
making them parseable without JavaScript execution.
"""

import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from dateutil import parser as dateparser
import pytz
import re

from .base import BaseScraper, Event, HEADERS

CENTRAL = pytz.timezone("America/Chicago")

# Public HTML listing pages for the JoCo area
SCRAPE_URLS = [
    ("https://www.eventbrite.com/d/ks--overland-park/events/", "Overland Park"),
    ("https://www.eventbrite.com/d/ks--olathe/events/", "Olathe"),
    ("https://www.eventbrite.com/d/ks--lenexa/events/", "Lenexa"),
    ("https://www.eventbrite.com/d/ks--shawnee/events/", "Shawnee"),
]

# Eventbrite sends bot-detection for generic UA strings — use a realistic one
EB_HEADERS = {
    **HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Referer": "https://www.eventbrite.com/",
}


class EventbriteScraper(BaseScraper):
    name = "Eventbrite"

    def fetch(self) -> list[Event]:
        all_events = []
        for url, city in SCRAPE_URLS:
            try:
                resp = requests.get(url, headers=EB_HEADERS, timeout=15)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "lxml")

                # Strategy 1: JSON-LD structured data (most reliable)
                events = self._parse_jsonld(soup, city, url)
                if not events:
                    # Strategy 2: HTML card fallback
                    events = self._parse_html(soup, city, url)

                self.logger.info(f"  → {city}: {len(events)} events")
                all_events.extend(events)
            except Exception as e:
                self.logger.warning(f"Failed {city} ({url}): {e}")

        return all_events

    def _parse_jsonld(self, soup: BeautifulSoup, city: str, source_url: str) -> list[Event]:
        """
        Eventbrite embeds JSON-LD in <script type="application/ld+json">.
        The listing page uses an ItemList wrapper:
          { "@type": "ItemList", "itemListElement": [ { "@type": "ListItem", "item": {...event...} } ] }
        We unwrap all levels to find event objects.
        """
        events = []
        EVENT_TYPES = {"Event", "MusicEvent", "SportsEvent", "EducationEvent",
                       "FoodEvent", "SocialEvent", "BusinessEvent"}

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                candidates = data if isinstance(data, list) else [data]

                for obj in candidates:
                    # Unwrap ItemList → ListItem → item
                    if obj.get("@type") == "ItemList":
                        for list_item in obj.get("itemListElement", []):
                            inner = list_item.get("item", list_item)
                            if inner.get("@type") in EVENT_TYPES or "startDate" in inner:
                                event = self._jsonld_to_event(inner, city)
                                if event:
                                    events.append(event)
                    elif obj.get("@type") in EVENT_TYPES or "startDate" in obj:
                        event = self._jsonld_to_event(obj, city)
                        if event:
                            events.append(event)
            except Exception:
                pass
        return events

    def _jsonld_to_event(self, item: dict, city: str) -> Event | None:
        try:
            title = item.get("name", "").strip()
            if not title:
                return None

            url = item.get("url", "")
            description = item.get("description", "")[:500]
            image_url = item.get("image", None)
            if isinstance(image_url, list):
                image_url = image_url[0] if image_url else None

            # Dates
            start_str = item.get("startDate", "")
            end_str = item.get("endDate", "")
            start_date = dateparser.parse(start_str) if start_str else datetime.now(CENTRAL)
            end_date = dateparser.parse(end_str) if end_str else None
            if start_date and start_date.tzinfo is None:
                start_date = CENTRAL.localize(start_date)
            if end_date and end_date.tzinfo is None:
                end_date = CENTRAL.localize(end_date)

            # Location
            loc = item.get("location", {})
            if isinstance(loc, dict):
                venue_name = loc.get("name", "")
                addr = loc.get("address", {})
                addr_city = addr.get("addressLocality", city) if isinstance(addr, dict) else city
                location = f"{venue_name}, {addr_city}".strip(", ")
            else:
                location = str(loc) if loc else f"{city}, KS"
                addr_city = city

            # Offers / cost
            offers = item.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = offers.get("price", "") if isinstance(offers, dict) else ""
            cost = "Free" if str(price) == "0" else (f"${price}" if price else None)

            return Event(
                title=title,
                start_date=start_date,
                end_date=end_date,
                location=location,
                city=addr_city,
                description=description,
                url=url,
                source="Eventbrite",
                image_url=image_url,
                cost=cost,
            )
        except Exception as e:
            self.logger.warning(f"JSON-LD parse error: {e}")
            return None

    def _parse_html(self, soup: BeautifulSoup, city: str, source_url: str) -> list[Event]:
        events = []

        # Eventbrite event cards use data attributes and structured markup
        cards = soup.find_all("div", attrs={"data-testid": re.compile(r"event", re.I)})

        # Fallback: section or article tags
        if not cards:
            cards = soup.find_all(["article", "section"], class_=re.compile(r"event", re.I))

        # Fallback: any li with an event-like link
        if not cards:
            cards = soup.find_all("li", class_=re.compile(r"event|search", re.I))

        for card in cards:
            try:
                # Title
                title_tag = card.find(["h2", "h3", "h4"]) or card.find(class_=re.compile(r"title|name", re.I))
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                if not title:
                    continue

                # URL
                link = card.find("a", href=True)
                url = link["href"] if link else source_url
                if not url.startswith("http"):
                    url = "https://www.eventbrite.com" + url

                # Date
                date_tag = card.find("time") or card.find(class_=re.compile(r"date|when|time", re.I))
                date_str = ""
                if date_tag:
                    date_str = date_tag.get("datetime", "") or date_tag.get_text(strip=True)
                try:
                    start_date = dateparser.parse(date_str, fuzzy=True) if date_str else datetime.now(CENTRAL)
                    if start_date and start_date.tzinfo is None:
                        start_date = CENTRAL.localize(start_date)
                except Exception:
                    start_date = datetime.now(CENTRAL)

                # Location
                loc_tag = card.find(class_=re.compile(r"locat|venue|address", re.I))
                location = loc_tag.get_text(strip=True) if loc_tag else f"{city}, KS"

                # Image
                img = card.find("img")
                image_url = img.get("src") or img.get("data-src") if img else None

                # Cost
                cost_tag = card.find(class_=re.compile(r"price|cost|ticket|free", re.I))
                cost = cost_tag.get_text(strip=True) if cost_tag else None

                events.append(Event(
                    title=title,
                    start_date=start_date,
                    end_date=None,
                    location=location,
                    city=city,
                    description="",
                    url=url,
                    source="Eventbrite",
                    image_url=image_url,
                    cost=cost,
                ))
            except Exception as e:
                self.logger.warning(f"Card parse error: {e}")

        return events
