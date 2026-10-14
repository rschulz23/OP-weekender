from __future__ import annotations
"""
Scrapers: Official City Event Calendars
Sources:
  - Overland Park:  https://www.opkansas.org/events/
  - Olathe:         https://www.olatheks.gov/residents/calendar
  - Shawnee:        https://www.cityofshawnee.org/calendar  (CivicEngage)
  - Leawood:        https://www.leawood.org/Calendar.aspx   (CivicEngage)
  - Lenexa:         https://www.lenexa.com/Events-Activities

All CivicEngage cities (Shawnee, Leawood) use schema.org microdata with
itemprop="startDate" for reliable date parsing. Olathe and Lenexa block
direct requests — alternative URLs are tried automatically.
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
from dateutil import parser as dateparser
import re
import pytz

from .base import BaseScraper, Event, HEADERS

CENTRAL = pytz.timezone("America/Chicago")

# Overland Park and Leawood are deliberately absent: both have dedicated
# scrapers (OPKansasScraper, LeawoodCalendarScraper) that handle the JS
# rendering and Cloudflare blocking those sites now require.
CITY_CONFIGS = [
    {
        "name": "Olathe",
        # olatheks.gov returns 403 to scripted requests and to a headless
        # browser alike; the Patch community calendar is the stand-in.
        "url": "https://patch.com/kansas/olathe-ks/calendar",
        "base_url": "https://patch.com",
        "city": "Olathe",
        "platform": "patch",
    },
    {
        "name": "Shawnee",
        "url": "https://www.cityofshawnee.org/calendar",
        "base_url": "https://www.cityofshawnee.org",
        "city": "Shawnee",
        "platform": "civicengage",
    },
    {
        "name": "Lenexa",
        # lenexa.com blocks scripted requests and its own calendar URL 404s.
        "url": "https://events.visitshawnee.com/calendar",
        "base_url": "https://events.visitshawnee.com",
        "city": "Lenexa",
        "platform": "generic",
    },
]


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


def _parse_patch(soup: BeautifulSoup, config: dict) -> list[Event]:
    """Parser for Patch.com community calendars."""
    events = []
    city = config["city"]

    # Patch event cards
    cards = soup.find_all("div", class_=re.compile(r"EventCard|event-card|CalendarItem", re.I))
    if not cards:
        cards = soup.find_all("article")

    for card in cards:
        try:
            title_tag = card.find(["h2", "h3", "h4"]) or card.find(class_=re.compile(r"title", re.I))
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            if not title:
                continue

            link = card.find("a", href=True)
            url = link["href"] if link else config["url"]
            if url.startswith("/"):
                url = "https://patch.com" + url

            date_tag = card.find("time") or card.find(class_=re.compile(r"date|time|when", re.I))
            date_str = ""
            if date_tag:
                date_str = date_tag.get("datetime", "") or date_tag.get_text(strip=True)
            try:
                start_date = dateparser.parse(date_str, fuzzy=True) if date_str else datetime.now(CENTRAL)
                if start_date and start_date.tzinfo is None:
                    start_date = CENTRAL.localize(start_date)
            except Exception:
                start_date = datetime.now(CENTRAL)

            desc_tag = card.find("p")
            description = desc_tag.get_text(" ", strip=True)[:500] if desc_tag else ""

            events.append(Event(
                title=title,
                start_date=start_date,
                end_date=None,
                location=f"{city}, KS",
                city=city,
                description=description,
                url=url,
                source=f"City of {city}",
            ))
        except Exception:
            pass

    return events


def _parse_generic(soup: BeautifulSoup, config: dict) -> list[Event]:
    """Generic parser — tries multiple card patterns with schema.org dates."""
    events = []
    city = config["city"]
    base_url = config["base_url"]
    source = f"City of {city}"

    # Try schema.org event items first
    for item in soup.find_all(itemtype=re.compile(r"schema.org/Event", re.I)):
        try:
            name_tag = item.find(itemprop="name")
            title = name_tag.get_text(strip=True) if name_tag else ""
            if not title:
                continue

            url_tag = item.find("a", href=True)
            href = url_tag["href"] if url_tag else ""
            url = (base_url + href) if href.startswith("/") else (href or config["url"])

            start_tag = item.find(itemprop="startDate")
            date_str = start_tag.get_text(strip=True) if start_tag else ""
            try:
                start_date = dateparser.parse(date_str) if date_str else datetime.now(CENTRAL)
                if start_date and start_date.tzinfo is None:
                    start_date = CENTRAL.localize(start_date)
            except Exception:
                start_date = datetime.now(CENTRAL)

            desc_tag = item.find(itemprop="description") or item.find("p")
            description = desc_tag.get_text(" ", strip=True)[:500] if desc_tag else ""

            loc_tag = item.find(itemprop="location")
            location = loc_tag.get_text(strip=True) if loc_tag else f"{city}, KS"

            events.append(Event(
                title=title, start_date=start_date, end_date=None,
                location=location, city=city, description=description,
                url=url, source=source,
            ))
        except Exception:
            pass

    if events:
        return events

    # Fallback: article/card HTML pattern
    cards = (
        soup.find_all("article") or
        soup.find_all("div", class_=re.compile(r"event[-_]?(card|item|listing)", re.I)) or
        soup.find_all("li", class_=re.compile(r"event|item", re.I))
    )

    for card in cards:
        try:
            title_tag = card.find(["h2", "h3", "h4"]) or card.find(class_=re.compile(r"title|name", re.I))
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            if len(title) < 3:
                continue

            link = card.find("a", href=True)
            href = link["href"] if link else ""
            url = (base_url + href) if href.startswith("/") else (href or config["url"])

            date_tag = card.find("time") or card.find(class_=re.compile(r"date|when|time|start", re.I))
            date_str = (date_tag.get("datetime", "") or date_tag.get_text(strip=True)) if date_tag else ""
            try:
                start_date = dateparser.parse(date_str, fuzzy=True) if date_str else datetime.now(CENTRAL)
                if start_date and start_date.tzinfo is None:
                    start_date = CENTRAL.localize(start_date)
            except Exception:
                start_date = datetime.now(CENTRAL)

            desc_tag = card.find("p")
            description = desc_tag.get_text(" ", strip=True)[:500] if desc_tag else ""

            loc_tag = card.find(class_=re.compile(r"locat|venue|address", re.I))
            location = loc_tag.get_text(strip=True) if loc_tag else f"{city}, KS"

            events.append(Event(
                title=title, start_date=start_date, end_date=None,
                location=location, city=city, description=description,
                url=url, source=source,
            ))
        except Exception:
            pass

    return events


PLATFORM_PARSERS = {
    "civicengage": _parse_civicengage,
    "patch": _parse_patch,
    "generic": _parse_generic,
}


class _CityCalendarScraper(BaseScraper):
    """One city's calendar. Split per city so the run report names the exact
    city that went quiet — when all five shared one scraper, a working Shawnee
    masked Olathe and Lenexa returning nothing for weeks."""

    CONFIG: dict = {}

    def fetch(self) -> list[Event]:
        config = self.CONFIG
        try:
            resp = requests.get(config["url"], headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            self.logger.warning(f"Fetch failed: {e}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        parser = PLATFORM_PARSERS.get(config["platform"], _parse_generic)
        events = parser(soup, config)
        self.logger.info(f"Parsed {len(events)} events from {config['name']}")
        return events


def _city_scraper(config: dict) -> type:
    return type(
        f"{config['city'].replace(' ', '')}CalendarScraper",
        (_CityCalendarScraper,),
        {"name": f"City of {config['city']}", "CONFIG": config},
    )


OlatheCalendarScraper  = _city_scraper(CITY_CONFIGS[0])
ShawneeCalendarScraper = _city_scraper(CITY_CONFIGS[1])
LenexaCalendarScraper  = _city_scraper(CITY_CONFIGS[2])

CITY_SCRAPERS = [OlatheCalendarScraper, ShawneeCalendarScraper, LenexaCalendarScraper]
