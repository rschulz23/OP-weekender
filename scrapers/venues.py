from __future__ import annotations
"""
Scraper: Local Venues
Sources:
  - Bluhawk Sports Park (bluhawksports.com) — JSON-LD
  - Prairiefire (prairiefireop.com/happenings) — requests + BS4
  - Chicken N Pickle OP (chickennpickle.com/events/) — requests + BS4 (MEC plugin)
  - KC Running Company (kcrunningcompany.com/our-events) — requests + BS4
  - Blue Valley Recreation (bluevalleyrec.org/events/) — requests + BS4
  - Knuckleheads (knuckleheadskc.com) — own ticketing, requests + BS4
  - Green Lady Lounge (greenladylounge.com) — requests + BS4
  - Sporting Kansas City (seatgeek.com) — SeatGeek HTML scrape
  - Kansas City Current (seatgeek.com) — SeatGeek HTML scrape
  - Kansas City Monarchs (monarchsbaseball.com) — Igniter Tickets scrape
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


# ── Knuckleheads ──────────────────────────────────────────────────────────────

class KnuckleheadsScraper(BaseScraper):
    name    = "Knuckleheads"
    # ShowWare ticketing — JS-rendered, use Playwright
    URL     = "https://tickets.knuckleheadskc.com"
    REAL_UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    def fetch(self) -> list[Event]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.logger.warning("Playwright not installed — skipping Knuckleheads")
            return []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=self.REAL_UA)
            page = context.new_page()
            try:
                page.goto(self.URL, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_selector(".show-item, .event-item, li.item, .event-listing", timeout=12000)
            except Exception as e:
                self.logger.warning(f"Page load issue: {e}")
                browser.close()
                return []
            page.wait_for_timeout(2000)
            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, "lxml")
        return self._parse(soup)

    def _parse(self, soup: BeautifulSoup) -> list[Event]:
        events = []
        for item in soup.find_all(class_=re.compile(r"show-item|event-item|event-listing")):
            try:
                title_tag = item.find(class_=re.compile(r"name|title")) or item.find(["h2", "h3", "h4"])
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                date_tag = item.find(class_=re.compile(r"date|time")) or item.find("time")
                date_str = (date_tag.get("datetime") or date_tag.get_text(strip=True)) if date_tag else ""
                start_date = _parse_date(date_str) or datetime.now(CENTRAL)
                link = item.find("a", href=True)
                url  = link["href"] if link else self.URL
                if url.startswith("/"):
                    url = self.URL + url
                events.append(Event(
                    title=title, start_date=start_date, end_date=None,
                    location="Knuckleheads, Kansas City", city="Kansas City",
                    description="", url=url, source="Knuckleheads",
                ))
            except Exception as e:
                self.logger.warning(f"Item parse error: {e}")
        self.logger.info(f"Parsed {len(events)} events from Knuckleheads")
        return events


# ── Green Lady Lounge ─────────────────────────────────────────────────────────

class GreenLadyLoungeScraper(BaseScraper):
    name = "Green Lady Lounge"
    URL  = "https://greenladylounge.com/calendar"

    def fetch(self) -> list[Event]:
        try:
            resp = requests.get(self.URL, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            self.logger.warning(f"Fetch failed: {e}")
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        return self._parse(soup)

    def _parse(self, soup: BeautifulSoup) -> list[Event]:
        import json as _json
        events = []

        # Try JSON-LD
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = _json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") == "Event":
                        start = _parse_date(item.get("startDate", ""))
                        if start:
                            events.append(Event(
                                title=item.get("name", ""),
                                start_date=start,
                                end_date=None,
                                location="Green Lady Lounge, Kansas City",
                                city="Kansas City",
                                description=item.get("description", "")[:300],
                                url=item.get("url", self.URL),
                                source="Green Lady Lounge",
                            ))
            except Exception:
                pass

        if events:
            self.logger.info(f"Parsed {len(events)} events from Green Lady Lounge (JSON-LD)")
            return events

        # Fallback: Squarespace/generic event list pattern
        for block in soup.find_all(class_=re.compile(r"eventlist-event|event-card|event-item|summary-item")):
            try:
                title_tag = block.find(class_=re.compile(r"title|name|heading"))
                if not title_tag:
                    title_tag = block.find(["h2", "h3"])
                if not title_tag:
                    continue
                link = title_tag.find("a") or block.find("a", href=True)
                title = title_tag.get_text(strip=True)
                url   = link["href"] if link else self.URL
                if url.startswith("/"):
                    url = "https://www.greenladylounge.com" + url

                date_tag = block.find(class_=re.compile(r"date|time|dt"))
                if not date_tag:
                    date_tag = block.find("time")
                date_str = (date_tag.get("datetime") or date_tag.get_text(strip=True)) if date_tag else ""
                start_date = _parse_date(date_str) or datetime.now(CENTRAL)

                events.append(Event(
                    title=title, start_date=start_date, end_date=None,
                    location="Green Lady Lounge, Kansas City", city="Kansas City",
                    description="", url=url, source="Green Lady Lounge",
                ))
            except Exception as e:
                self.logger.warning(f"Block parse error: {e}")

        self.logger.info(f"Parsed {len(events)} events from Green Lady Lounge")
        return events


# ── Sporting Kansas City ──────────────────────────────────────────────────────

class SportingKCScraper(BaseScraper):
    name    = "Sporting KC"
    URL     = "https://www.sportingkc.com/schedule/"
    REAL_UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    def fetch(self) -> list[Event]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.logger.warning("Playwright not installed — skipping Sporting KC")
            return []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=self.REAL_UA)
            page = context.new_page()
            try:
                page.goto(self.URL, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_selector(".mls-l-module--match-list, .c-schedule, [class*='match']", timeout=12000)
            except Exception as e:
                self.logger.warning(f"Page load issue: {e}")
                browser.close()
                return []
            page.wait_for_timeout(2500)
            html = page.content()
            browser.close()

        import json as _json
        soup = BeautifulSoup(html, "lxml")
        events = []

        # JSON-LD SportsEvent
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = _json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") in ("SportsEvent", "Event"):
                        start = _parse_date(item.get("startDate", ""))
                        if not start:
                            continue
                        loc = item.get("location", {})
                        location = loc.get("name", "Children's Mercy Park") if isinstance(loc, dict) else "Children's Mercy Park"
                        events.append(Event(
                            title=item.get("name", "Sporting KC"),
                            start_date=start, end_date=None,
                            location=f"{location}, Kansas City", city="Kansas City",
                            description="", url=item.get("url", self.URL),
                            source="Sporting KC",
                        ))
            except Exception:
                pass

        if not events:
            # MLS widget match cards
            for card in soup.find_all(class_=re.compile(r"match-list__match|c-schedule__item|match-row")):
                try:
                    date_tag = card.find("time") or card.find(class_=re.compile(r"date|time"))
                    if not date_tag:
                        continue
                    start_date = _parse_date(date_tag.get("datetime") or date_tag.get_text(strip=True))
                    if not start_date:
                        continue
                    opp = card.find(class_=re.compile(r"opponent|away|home|team-name"))
                    title = f"Sporting KC vs {opp.get_text(strip=True)}" if opp else "Sporting KC"
                    link  = card.find("a", href=True)
                    url   = link["href"] if link else self.URL
                    events.append(Event(
                        title=title, start_date=start_date, end_date=None,
                        location="Children's Mercy Park, Kansas City", city="Kansas City",
                        description="", url=url, source="Sporting KC",
                    ))
                except Exception:
                    pass

        self.logger.info(f"Parsed {len(events)} events from Sporting KC")
        return events


# ── Kansas City Current ───────────────────────────────────────────────────────

class KCCurrentScraper(BaseScraper):
    name    = "KC Current"
    URL     = "https://www.kansascitycurrent.com/schedule"
    REAL_UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    def fetch(self) -> list[Event]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.logger.warning("Playwright not installed — skipping KC Current")
            return []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=self.REAL_UA)
            page = context.new_page()
            try:
                page.goto(self.URL, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_selector("[class*='match'], [class*='schedule'], [class*='game']", timeout=12000)
            except Exception as e:
                self.logger.warning(f"Page load issue: {e}")
                browser.close()
                return []
            page.wait_for_timeout(2500)
            html = page.content()
            browser.close()

        import json as _json
        soup = BeautifulSoup(html, "lxml")
        events = []

        # JSON-LD SportsEvent
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = _json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") in ("SportsEvent", "Event"):
                        start = _parse_date(item.get("startDate", ""))
                        if not start:
                            continue
                        # Skip past events
                        if start < datetime.now(CENTRAL):
                            continue
                        loc = item.get("location", {})
                        location = loc.get("name", "CPKC Stadium") if isinstance(loc, dict) else "CPKC Stadium"
                        events.append(Event(
                            title=item.get("name", "KC Current"),
                            start_date=start, end_date=None,
                            location=f"{location}, Kansas City", city="Kansas City",
                            description="", url=item.get("url", self.URL),
                            source="KC Current",
                        ))
            except Exception:
                pass

        if not events:
            for card in soup.find_all(class_=re.compile(r"match|game|fixture"), limit=30):
                try:
                    date_tag = card.find("time") or card.find(class_=re.compile(r"date"))
                    if not date_tag:
                        continue
                    start_date = _parse_date(date_tag.get("datetime") or date_tag.get_text(strip=True))
                    if not start_date or start_date < datetime.now(CENTRAL):
                        continue
                    opp = card.find(class_=re.compile(r"opponent|away|team"))
                    title = f"KC Current vs {opp.get_text(strip=True)}" if opp else "KC Current"
                    link  = card.find("a", href=True)
                    url   = link["href"] if link else self.URL
                    events.append(Event(
                        title=title, start_date=start_date, end_date=None,
                        location="CPKC Stadium, Kansas City", city="Kansas City",
                        description="", url=url, source="KC Current",
                    ))
                except Exception:
                    pass

        self.logger.info(f"Parsed {len(events)} events from KC Current")
        return events


# ── Kansas City Monarchs ──────────────────────────────────────────────────────

class KCMonarchsScraper(BaseScraper):
    name = "KC Monarchs"
    URL  = "https://www.monarchsbaseball.com/schedule"

    def fetch(self) -> list[Event]:
        try:
            resp = requests.get(self.URL, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            self.logger.warning(f"Fetch failed: {e}")
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        return self._parse(soup)

    def _parse(self, soup: BeautifulSoup) -> list[Event]:
        import json as _json
        events = []

        # Try JSON-LD first
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = _json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") in ("SportsEvent", "Event"):
                        start = _parse_date(item.get("startDate", ""))
                        if start:
                            events.append(Event(
                                title=item.get("name", "KC Monarchs"),
                                start_date=start,
                                end_date=None,
                                location="Legends Field, Kansas City",
                                city="Kansas City",
                                description="",
                                url=item.get("url", self.URL),
                                source="KC Monarchs",
                            ))
            except Exception:
                pass

        if not events:
            # Generic schedule row fallback
            for row in soup.find_all(class_=re.compile(r"schedule|game|event"), limit=30):
                try:
                    date_tag = row.find("time") or row.find(class_=re.compile(r"date"))
                    if not date_tag:
                        continue
                    start_date = _parse_date(date_tag.get("datetime") or date_tag.get_text(strip=True))
                    if not start_date:
                        continue
                    title_tag = row.find(class_=re.compile(r"opponent|title|name|team"))
                    title = f"KC Monarchs vs {title_tag.get_text(strip=True)}" if title_tag else "KC Monarchs"
                    link  = row.find("a", href=True)
                    url   = link["href"] if link else self.URL
                    events.append(Event(
                        title=title, start_date=start_date, end_date=None,
                        location="Legends Field, Kansas City", city="Kansas City",
                        description="", url=url, source="KC Monarchs",
                    ))
                except Exception:
                    pass

        self.logger.info(f"Parsed {len(events)} events from KC Monarchs")
        return events


# ── The Midland KC ────────────────────────────────────────────────────────────

class MidlandKCScraper(BaseScraper):
    name = "The Midland"
    URL  = "https://www.midlandkc.com/events"
    BASE = "https://www.midlandkc.com"

    def fetch(self) -> list[Event]:
        try:
            resp = requests.get(self.URL, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            self.logger.warning(f"Fetch failed: {e}")
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        return self._parse(soup)

    def _parse(self, soup: BeautifulSoup) -> list[Event]:
        events = []
        # Each event is div.entry.midland.clearfix
        for block in soup.find_all("div", class_="entry"):
            try:
                title_tag = block.find("h3", class_="carousel_item_title_small")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                if not title:
                    continue

                # Skip cancelled events
                buttons = block.find("div", class_="buttons")
                if buttons and re.search(r"cancel", buttons.get_text(), re.I):
                    continue

                # Date: span.date inside div.date-time-container
                date_span = block.find("span", class_="date")
                time_span = block.find("span", class_="time")
                date_text = date_span.get_text(strip=True) if date_span else ""
                # Strip the font-awesome icon text (empty span) — just keep the visible text
                date_text = re.sub(r"\s+", " ", date_text).strip()
                if time_span:
                    time_text = time_span.get_text(strip=True).replace("Show", "").strip()
                    date_text = f"{date_text} {time_text}"
                start_date = _parse_date(date_text)
                if not start_date:
                    continue

                link = block.find("a", href=re.compile(r"/events/detail/"))
                url  = link["href"] if link else self.URL

                img_tag   = block.find("img")
                image_url = img_tag.get("src") if img_tag else None

                events.append(Event(
                    title=title, start_date=start_date, end_date=None,
                    location="The Midland, Kansas City", city="Kansas City",
                    description="", url=url, source="The Midland",
                    image_url=image_url,
                ))
            except Exception as e:
                self.logger.warning(f"Block parse error: {e}")

        self.logger.info(f"Parsed {len(events)} events from The Midland")
        return events


# ── T-Mobile Center ───────────────────────────────────────────────────────────

class TMobileCenterScraper(BaseScraper):
    name = "T-Mobile Center"
    URL  = "https://www.t-mobilecenter.com/events"
    BASE = "https://www.t-mobilecenter.com"

    def fetch(self) -> list[Event]:
        try:
            resp = requests.get(self.URL, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            self.logger.warning(f"Fetch failed: {e}")
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        return self._parse(soup)

    def _parse(self, soup: BeautifulSoup) -> list[Event]:
        import json as _json
        events = []
        # Page embeds a JSON-LD array of Event objects (Vue app loads the same data)
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = _json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "Event":
                        continue
                    title = item.get("name", "").strip()
                    if not title:
                        continue
                    start_date = _parse_date(item.get("startDate", ""))
                    if not start_date:
                        continue
                    url = item.get("url") or self.URL
                    if url.startswith("/"):
                        url = self.BASE + url
                    image_url = None
                    img = item.get("image")
                    if isinstance(img, str):
                        image_url = img
                    elif isinstance(img, dict):
                        image_url = img.get("url")
                    events.append(Event(
                        title=title, start_date=start_date, end_date=None,
                        location="T-Mobile Center, Kansas City", city="Kansas City",
                        description="", url=url, source="T-Mobile Center",
                        image_url=image_url,
                    ))
            except Exception as e:
                self.logger.warning(f"JSON-LD parse error: {e}")

        self.logger.info(f"Parsed {len(events)} events from T-Mobile Center")
        return events


# ── Leawood City Calendar (RSS) ───────────────────────────────────────────────

class LeawoodCalendarScraper(BaseScraper):
    name = "Leawood"
    URL  = "https://www.leawood.org/RSSFeed.aspx?ModID=58&CID=Main-Calendar-14"

    def fetch(self) -> list[Event]:
        import xml.etree.ElementTree as ET
        try:
            resp = requests.get(self.URL, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            self.logger.warning(f"Fetch failed: {e}")
            return []

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as e:
            self.logger.warning(f"XML parse error: {e}")
            return []

        # RSS namespace for calendarEvent custom fields
        ns = {"ce": "urn:schemas-microsoft-com:office:office"}
        # Try to detect the actual namespace from the document
        ns_match = re.search(r'xmlns:calendarEvent=["\']([^"\']+)["\']', resp.text)
        ce_ns = ns_match.group(1) if ns_match else ""

        events = []
        for item in root.findall(".//item"):
            try:
                title = (item.findtext("title") or "").strip()
                url   = (item.findtext("link") or "").strip()
                if not title or not url:
                    continue

                # Prefer calendarEvent:EventDates for the date
                date_text = ""
                if ce_ns:
                    date_el = item.find(f"{{{ce_ns}}}EventDates")
                    time_el = item.find(f"{{{ce_ns}}}EventTimes")
                    loc_el  = item.find(f"{{{ce_ns}}}Location")
                    if date_el is not None and date_el.text:
                        date_text = date_el.text.strip()
                        if time_el is not None and time_el.text:
                            date_text += " " + time_el.text.strip().split("-")[0].strip()
                    location = loc_el.text.strip() if loc_el is not None and loc_el.text else "Leawood, KS"
                else:
                    location = "Leawood, KS"

                if not date_text:
                    date_text = item.findtext("pubDate") or ""

                start_date = _parse_date(date_text)
                if not start_date:
                    continue

                # Strip HTML from description
                raw_desc = item.findtext("description") or ""
                desc = re.sub(r"<[^>]+>", " ", raw_desc).strip()[:300]

                events.append(Event(
                    title=title, start_date=start_date, end_date=None,
                    location=location, city="Leawood",
                    description=desc, url=url, source="Leawood",
                ))
            except Exception as e:
                self.logger.warning(f"Item parse error: {e}")

        self.logger.info(f"Parsed {len(events)} events from Leawood")
        return events


# ── Overland Park City Events (CivicPlus / Playwright) ───────────────────────

class OPKansasScraper(BaseScraper):
    name    = "City of Overland Park"
    URL     = "https://www.opkansas.org/parks-recreation-and-sports/special-events/"
    # The /events page is a pure JS app; use the parks/recreation events page
    # which tends to have server-side rendered JSON-LD
    REAL_UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    def fetch(self) -> list[Event]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.logger.warning("Playwright not installed — skipping OP Kansas")
            return []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=self.REAL_UA)
            page = context.new_page()
            try:
                page.goto("https://www.opkansas.gov/events", wait_until="networkidle", timeout=40000)
                page.wait_for_timeout(3000)
            except Exception as e:
                self.logger.warning(f"Page load issue: {e}")
                browser.close()
                return []
            html = page.content()
            browser.close()

        import json as _json
        soup = BeautifulSoup(html, "lxml")
        events = []

        # Try JSON-LD first
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = _json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") not in ("Event", "SportsEvent"):
                        continue
                    start = _parse_date(item.get("startDate", ""))
                    if not start:
                        continue
                    loc = item.get("location", {})
                    location = loc.get("name", "Overland Park") if isinstance(loc, dict) else "Overland Park"
                    events.append(Event(
                        title=item.get("name", "").strip(),
                        start_date=start, end_date=None,
                        location=f"{location}, Overland Park", city="Overland Park",
                        description=item.get("description", "")[:300],
                        url=item.get("url", "https://www.opkansas.gov/events"),
                        source="City of Overland Park",
                    ))
            except Exception:
                pass

        if not events:
            # CivicPlus renders div.widgetItem.widgetItem--contentItem blocks
            for block in soup.find_all("div", class_="widgetItem--contentItem"):
                try:
                    title_tag = block.find(class_="cp-fieldWrapper")
                    if not title_tag:
                        continue
                    title = title_tag.get_text(strip=True)
                    if not title:
                        continue

                    # Skip government meetings, procurement, office closures, and malformed titles
                    if re.search(
                        r"\b(committee|council|commission|advisory|review board|"
                        r"bid\b|ebid\b|rfp\b|procurement|patcher|refurbishment|"
                        r"ordinance|hearing|meeting|offices closed|office closed)\b",
                        title, re.I
                    ):
                        continue
                    # Skip titles that look like address/contact blocks (contain phone or zip)
                    if re.search(r"\d{5}|\d{3}[-.\s]\d{3}[-.\s]\d{4}|a\.m\.|p\.m\.", title):
                        continue
                    # Skip unreasonably long titles (address bleed-through)
                    if len(title) > 120:
                        continue

                    link = block.find("a", class_="widgetTitle--link")
                    href = link["href"] if link else ""
                    url  = ("https://www.opkansas.gov" + href) if href.startswith("/") else href or "https://www.opkansas.gov/events"

                    # Date and location are in div.widgetDesc as plain text
                    # Format: "June 23, 2026, All Day 8909 W. 179th Street Overland Park..."
                    desc_div = block.find(class_="widgetDesc")
                    desc_text = desc_div.get_text(" ", strip=True) if desc_div else ""

                    # Extract date — text before the address (first comma-separated date pattern)
                    date_match = re.match(
                        r"([A-Za-z]+ \d{1,2},\s*\d{4}[^A-Z]*?)(?:\d{4,5}\s+[A-Z]|$)",
                        desc_text
                    )
                    date_str = date_match.group(1).strip() if date_match else desc_text[:40]
                    start = _parse_date(date_str)
                    if not start:
                        continue

                    img_tag   = block.find("img")
                    image_url = img_tag.get("src") if img_tag else None

                    events.append(Event(
                        title=title, start_date=start, end_date=None,
                        location="Overland Park", city="Overland Park",
                        description="", url=url, source="City of Overland Park",
                        image_url=image_url,
                    ))
                except Exception as e:
                    self.logger.warning(f"Block parse error: {e}")

        self.logger.info(f"Parsed {len(events)} events from City of Overland Park")
        return events
        return events
