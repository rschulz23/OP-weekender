from __future__ import annotations
"""
Scraper: Local Venues
Sources:
  - Bluhawk (bluhawk.com/events/) — Playwright, JS-rendered
  - Prairiefire (prairiefireop.com/happenings) — requests + BS4
  - Chicken N Pickle OP (chickennpickle.com/events/) — requests + BS4 (Tribe Events)
  - KC Running Company (kcrunningcompany.com/our-events) — requests + BS4
  - Blue Valley Recreation (bluevalleyrec.org/events/) — requests + BS4
"""

import re
import requests
from datetime import datetime
from dateutil import parser as dateparser
import pytz
from bs4 import BeautifulSoup

from .base import BaseScraper, Event, HEADERS

CENTRAL = pytz.timezone("America/Chicago")


def _parse_date(text: str) -> datetime | None:
    """Best-effort date parse; returns None on failure."""
    try:
        dt = dateparser.parse(text, fuzzy=True)
        if dt:
            return CENTRAL.localize(dt) if dt.tzinfo is None else dt.astimezone(CENTRAL)
    except Exception:
        pass
    return None


# ── Bluhawk (AdventHealth Sports Park) ───────────────────────────────────────

class BluhawkScraper(BaseScraper):
    name = "Bluhawk"
    URL  = "https://bluhawksports.com/event-calendar/"

    def fetch(self) -> list[Event]:
        import json as _json
        resp = requests.get(self.URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        events = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = _json.loads(script.string or "")
                if not isinstance(data, list):
                    continue
                for item in data:
                    if item.get("@type") != "Event":
                        continue
                    event = self._item_to_event(item)
                    if event:
                        events.append(event)
            except Exception as e:
                self.logger.warning(f"JSON-LD parse error: {e}")

        self.logger.info(f"Parsed {len(events)} events from Bluhawk")
        return events

    def _item_to_event(self, item: dict) -> Event | None:
        try:
            title      = item.get("name", "").strip()
            url        = item.get("url", self.URL)
            start_date = _parse_date(item.get("startDate", ""))
            end_date   = _parse_date(item.get("endDate", ""))
            description = item.get("description", "")[:300]

            loc = item.get("location", {})
            location = loc.get("name", "AdventHealth Sports Park at BluHawk, Overland Park") if isinstance(loc, dict) else "BluHawk, Overland Park"

            if not title or not start_date:
                return None

            return Event(
                title=title,
                start_date=start_date,
                end_date=end_date,
                location=location,
                city="Overland Park",
                description=description,
                url=url,
                source="Bluhawk",
            )
        except Exception as e:
            self.logger.warning(f"Item parse error: {e}")
            return None


# ── Prairiefire ───────────────────────────────────────────────────────────────

class PrairiefireScraper(BaseScraper):
    name = "Prairiefire"
    URL  = "https://www.prairiefireop.com/happenings"
    BASE = "https://www.prairiefireop.com"

    def fetch(self) -> list[Event]:
        resp = requests.get(self.URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        return self._parse(soup)

    def _parse(self, soup: BeautifulSoup) -> list[Event]:
        events = []
        seen_slugs: set[str] = set()

        # Each event block has: event link + a Google Calendar link with dates=YYYYMMDDTHHMMSSZ
        # Walk all Google Calendar links to extract structured date + paired event info
        for gcal in soup.find_all("a", href=re.compile(r"google\.com/calendar/event")):
            try:
                href = gcal["href"]
                # Extract start datetime from dates= param: dates=20260522T020000Z/...
                m_date = re.search(r"dates=(\d{8})T(\d{6})Z", href)
                if not m_date:
                    continue
                date_part = m_date.group(1)   # e.g. "20260522"
                time_part = m_date.group(2)   # e.g. "020000"
                # Parse as UTC, then convert to Central
                from datetime import timezone
                dt_utc = datetime(
                    int(date_part[:4]), int(date_part[4:6]), int(date_part[6:8]),
                    int(time_part[:2]), int(time_part[2:4]),
                    tzinfo=timezone.utc,
                )
                start_date = dt_utc.astimezone(CENTRAL)

                # Event title from text= param
                m_title = re.search(r"text=([^&]+)", href)
                title = requests.utils.unquote(m_title.group(1)).replace("+", " ") if m_title else ""

                # Find the matching /happenings/ link nearby for the canonical URL
                parent = gcal.find_parent(["div", "li", "article", "section"])
                event_link = None
                if parent:
                    event_link = parent.find("a", href=re.compile(r"^/happenings/[^?#]+$"))
                slug = event_link["href"] if event_link else f"/happenings/{title.lower().replace(' ', '-')}"

                if slug in seen_slugs or not title:
                    continue
                seen_slugs.add(slug)

                url = self.BASE + slug

                events.append(Event(
                    title=title,
                    start_date=start_date,
                    end_date=None,
                    location="Prairiefire, Overland Park",
                    city="Overland Park",
                    description="",
                    url=url,
                    source="Prairiefire",
                ))
            except Exception as e:
                self.logger.warning(f"Card parse error: {e}")

        self.logger.info(f"Parsed {len(events)} events from Prairiefire")
        return events


# ── Chicken N Pickle ──────────────────────────────────────────────────────────

class ChickenNPickleScraper(BaseScraper):
    name = "Chicken N Pickle"
    # Main events page — Modern Events Calendar (MEC) plugin
    URL  = "https://chickennpickle.com/events/"

    def fetch(self) -> list[Event]:
        events = []
        url = self.URL
        page_num = 1

        while url and page_num <= 5:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                break
            soup = BeautifulSoup(resp.text, "lxml")
            new_events = self._parse_page(soup)
            if not new_events:
                break
            events.extend(new_events)

            # MEC pagination
            next_link = soup.find("a", class_=re.compile(r"mec-next|next-page"))
            url = next_link["href"] if next_link else None
            page_num += 1

        # Filter to Overland Park location only
        op_events = [e for e in events if "overland park" in e.title.lower()
                     or "overland park" in e.location.lower()
                     or "cnp op" in e.title.lower()]
        # If no OP-specific events found, return all (they may not tag by location)
        result = op_events if op_events else events
        self.logger.info(f"Parsed {len(result)} events from Chicken N Pickle")
        return result

    def _parse_page(self, soup: BeautifulSoup) -> list[Event]:
        events = []
        # Modern Events Calendar uses article.mec-event-article
        articles = soup.find_all("article", class_=re.compile(r"mec-event-article"))

        for art in articles:
            try:
                # Title: h3.mec-event-title
                title_tag = art.find(class_="mec-event-title")
                if not title_tag:
                    continue
                link = title_tag.find("a") or art.find("a", href=re.compile(r"chickennpickle\.com/events/"))
                title = title_tag.get_text(strip=True)
                url   = link["href"] if link else self.URL

                # Date: div.mec-date-details → "20 Jun"
                # Year extracted from article class mec-toggle-YYYYMM-ID
                year = datetime.now(CENTRAL).year
                art_classes = " ".join(art.get("class", []))
                m_year = re.search(r"mec-toggle-(\d{4})\d{2}-", art_classes)
                if m_year:
                    year = int(m_year.group(1))

                date_tag = art.find(class_="mec-date-details")
                time_tag = art.find(class_="mec-start-time")
                date_str = f"{date_tag.get_text(strip=True)} {year}" if date_tag else ""
                if time_tag:
                    date_str += f" {time_tag.get_text(strip=True)}"

                start_date = _parse_date(date_str) or datetime.now(CENTRAL)

                events.append(Event(
                    title=title,
                    start_date=start_date,
                    end_date=None,
                    location="Chicken N Pickle, Overland Park",
                    city="Overland Park",
                    description="",
                    url=url,
                    source="Chicken N Pickle",
                ))
            except Exception as e:
                self.logger.warning(f"Card parse error: {e}")

        return events


# ── KC Running Company ────────────────────────────────────────────────────────

class KCRunningCompanyScraper(BaseScraper):
    name      = "KC Running Company"
    LIST_URL  = "https://www.kcrunningcompany.com/our-events"
    BASE      = "https://www.kcrunningcompany.com"

    def fetch(self) -> list[Event]:
        resp = requests.get(self.LIST_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Collect all race/event links from the listing page
        event_links = []
        seen = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Internal links that look like event pages (not nav/footer boilerplate)
            if href.startswith("/") and href.count("/") == 1 and len(href) > 2:
                full = self.BASE + href
                if full not in seen and href not in ("/our-events", "/contact", "/about"):
                    seen.add(full)
                    event_links.append((a.get_text(strip=True), full))
            elif href.startswith(self.BASE) and href not in seen:
                seen.add(href)
                event_links.append((a.get_text(strip=True), href))

        events = []
        for title, url in event_links:
            if not title or len(title) < 3:
                continue
            event = self._scrape_event_page(title, url)
            if event:
                events.append(event)

        self.logger.info(f"Parsed {len(events)} events from KC Running Company")
        return events

    def _scrape_event_page(self, title: str, url: str) -> Event | None:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                return None
            soup = BeautifulSoup(resp.text, "lxml")

            # Look for JSON-LD first
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    import json
                    data = json.loads(script.string or "")
                    if isinstance(data, dict) and data.get("startDate"):
                        start_date = _parse_date(data["startDate"])
                        if start_date:
                            return Event(
                                title=data.get("name", title),
                                start_date=start_date,
                                end_date=_parse_date(data.get("endDate", "")),
                                location=data.get("location", {}).get("name", "Kansas City area"),
                                city="Overland Park",
                                description=data.get("description", "")[:300],
                                url=url,
                                source="KC Running Company",
                            )
                except Exception:
                    pass

            # Fallback: look for a date pattern in the page text
            text = soup.get_text(" ")
            m = re.search(
                r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}",
                text, re.I
            )
            if not m:
                return None

            start_date = _parse_date(m.group())
            if not start_date:
                return None

            # Description: first non-empty paragraph
            desc = ""
            for p in soup.find_all("p"):
                t = p.get_text(strip=True)
                if len(t) > 40:
                    desc = t[:300]
                    break

            return Event(
                title=title,
                start_date=start_date,
                end_date=None,
                location="Kansas City area",
                city="Overland Park",
                description=desc,
                url=url,
                source="KC Running Company",
            )
        except Exception as e:
            self.logger.warning(f"Event page error ({url}): {e}")
            return None


# ── Blue Valley Recreation ────────────────────────────────────────────────────

class BlueValleyRecScraper(BaseScraper):
    name = "Blue Valley Rec"
    URL  = "https://www.bluevalleyrec.org/events/"

    def fetch(self) -> list[Event]:
        resp = requests.get(self.URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        return self._parse(soup)

    def _parse(self, soup: BeautifulSoup) -> list[Event]:
        events = []

        # Structure: <h4><a href="...">Title</a></h4> followed by <p>Location</p><p>Date</p>
        for h4 in soup.find_all("h4"):
            try:
                link = h4.find("a")
                if not link:
                    continue
                title = link.get_text(strip=True)
                url   = link.get("href", self.URL)

                # Sibling <p> tags: first = location, second = date
                siblings = h4.find_next_siblings("p")
                location = siblings[0].get_text(strip=True) if len(siblings) > 0 else "Blue Valley, KS"
                date_str = siblings[1].get_text(strip=True) if len(siblings) > 1 else ""

                # Date format from site: "25 June 2026"
                start_date = _parse_date(date_str) or datetime.now(CENTRAL)

                if not title:
                    continue

                events.append(Event(
                    title=title,
                    start_date=start_date,
                    end_date=None,
                    location=location or "Blue Valley, KS",
                    city="Overland Park",
                    description="",
                    url=url,
                    source="Blue Valley Rec",
                ))
            except Exception as e:
                self.logger.warning(f"Row parse error: {e}")

        self.logger.info(f"Parsed {len(events)} events from Blue Valley Rec")
        return events
