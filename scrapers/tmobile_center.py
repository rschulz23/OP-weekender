from __future__ import annotations
"""
Scraper: T-Mobile Center (t-mobilecenter.com/events)
=====================================================
Most of the arena's calendar sells through AXS rather than Ticketmaster, so
the Ticketmaster feed only ever saw a minority of its shows.

The listing page is static HTML. Two sources are combined:
  * a JSON-LD ``Event`` array, which carries exact start times but only
    covers a handful of events
  * the ``.eventItem.featured`` blocks, which cover the full visible list
    but date events only to the day (via the ``.date`` aria-label)

Events found in both get the JSON-LD time; the rest fall back to a default
door time. Multi-day runs emit one event per day.
"""

import json
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pytz

from .base import BaseScraper, Event, HEADERS

CENTRAL = pytz.timezone("America/Chicago")
URL = "https://www.t-mobilecenter.com/events"
LOCATION = "T-Mobile Center, 1407 Grand Blvd, Kansas City, MO"

# Typical arena show time, used when JSON-LD has no entry for the event.
DEFAULT_HOUR, DEFAULT_MINUTE = 19, 30

# "September 17 2026" or "October 3 to October 4 2026"
_YEAR_RE = re.compile(r'(\d{4})\s*$')

# The shared categorizer keys off title keywords and mis-files performer names
# here ("Teddy Swims" and "Eric Clapton" both land in Sports & Fitness), so the
# category is decided at the venue instead: concerts unless the title says
# otherwise.
_SPORTS_RE = re.compile(
    r'\b(pbr|bull rid\w+|rodeo|monster truck\w*|wrestl\w+|wwe|aew|basketball|'
    r'hockey|globetrotters|boxing|ufc|mma|supercross|motocross)\b',
    re.IGNORECASE,
)


def _category_for(title: str) -> str:
    return "Sports & Fitness" if _SPORTS_RE.search(title) else "Music & Entertainment"


def _parse_label(label: str) -> tuple[datetime, datetime] | None:
    """Parse a .date aria-label into (first_day, last_day), time-less."""
    label = re.sub(r'\s+', ' ', label).strip()
    m = _YEAR_RE.search(label)
    if not m:
        return None
    year = m.group(1)

    if " to " in label:
        first_part, last_part = label.split(" to ", 1)
        last_part = last_part[: _YEAR_RE.search(last_part).start()].strip()
        first_part = first_part.strip()
    else:
        first_part = label[: m.start()].strip()
        last_part = first_part

    def _one(part: str) -> datetime | None:
        for fmt in ("%B %d %Y", "%b %d %Y"):
            try:
                return datetime.strptime(f"{part} {year}", fmt)
            except ValueError:
                continue
        return None

    start, end = _one(first_part), _one(last_part)
    if not start:
        return None
    return start, (end or start)


class TMobileCenterScraper(BaseScraper):
    name = "T-Mobile Center"

    def fetch(self) -> list[Event]:
        try:
            resp = requests.get(URL, headers=HEADERS, timeout=25)
            resp.raise_for_status()
        except Exception as e:
            self.logger.error(f"Fetch failed: {e}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        ld = self._load_jsonld(soup)
        events: list[Event] = []
        now = datetime.now(CENTRAL)

        for item in soup.select(".eventItem.featured"):
            try:
                title_tag = item.select_one(".title a") or item.select_one(".title")
                date_tag = item.select_one(".date[aria-label]")
                if not title_tag or not date_tag:
                    continue

                title = title_tag.get_text(strip=True)
                parsed = _parse_label(date_tag["aria-label"])
                if not parsed:
                    self.logger.warning(f"Unparsed date {date_tag['aria-label']!r} for {title!r}")
                    continue
                first_day, last_day = parsed

                link_tag = item.select_one(".title a[href]")
                url = link_tag["href"] if link_tag else URL

                info = ld.get(url, {})
                img_tag = item.select_one(".thumb img[src]")
                image_url = info.get("image") or (img_tag["src"] if img_tag else None)
                description = info.get("description", "")

                # Exact time when JSON-LD knows the event, else the default
                exact = info.get("_start")
                hour, minute = (exact.hour, exact.minute) if exact else (DEFAULT_HOUR, DEFAULT_MINUTE)

                day = first_day
                while day <= last_day:
                    start = CENTRAL.localize(day.replace(hour=hour, minute=minute))
                    if start >= now:
                        events.append(Event(
                            title=title,
                            start_date=start,
                            end_date=None,
                            location=LOCATION,
                            city="Kansas City",
                            description=description,
                            url=url,
                            source="T-Mobile Center",
                            image_url=image_url,
                            cost=None,
                            category=_category_for(title),
                        ))
                    day += timedelta(days=1)
            except Exception as e:
                self.logger.warning(f"Parse error: {e}")

        events.sort(key=lambda e: e.start_date)
        self.logger.info(f"Fetched {len(events)} T-Mobile Center events")
        return events

    def _load_jsonld(self, soup: BeautifulSoup) -> dict:
        """Map event URL -> JSON-LD entry, with '_start' as a parsed datetime."""
        out: dict = {}
        for block in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(block.string or "")
            except Exception:
                continue
            for entry in data if isinstance(data, list) else [data]:
                if not isinstance(entry, dict) or entry.get("@type") != "Event":
                    continue
                url = entry.get("url")
                if not url:
                    continue
                try:
                    entry["_start"] = datetime.fromisoformat(entry["startDate"]).astimezone(CENTRAL)
                except Exception:
                    entry["_start"] = None
                out[url] = entry
        return out
