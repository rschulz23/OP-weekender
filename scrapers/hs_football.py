from __future__ import annotations
"""
Scraper: High School Football Schedules (gobound.com)
======================================================
Scrapes varsity football schedules for 13 JoCo-area schools and returns
games falling on the target weekend (Fri–Sun) as Event objects with
category = "High School Football".
"""

import json
import re
import requests
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
import pytz

from .base import BaseScraper, Event

# Last good scrape of the season schedule, committed to the repo so CI can
# fall back to it when gobound refuses the runner's IP.
CACHE_PATH = Path(__file__).resolve().parent.parent / "hs_football_schedule.json"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

CENTRAL = pytz.timezone("America/Chicago")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.gobound.com/",
}

# Maps URL slug → short display name
SCHOOLS: dict[str, str] = {
    "bluevalley":           "Blue Valley",
    "bluevalleynorthwesths":"Blue Valley Northwest",
    "bluevalleywesths":     "Blue Valley West",
    "bluevalleysw":         "Blue Valley Southwest",
    "bluevalleynorthhs":    "Blue Valley North",
    "saintthomasaquinas":   "St. Thomas Aquinas",
    "smnorth":              "SM North",
    "shawneemissionwesths": "SM West",
    "shawneemissioneasths": "SM East",
    "smnorthwest":          "SM Northwest",
    "smsouth":              "SM South",
    "olatheeasths":         "Olathe East",
    "bishopmiegehs":        "Bishop Miege",
}

BASE_URL = "https://www.gobound.com/ks/KSHSAA/fb/2026-27/{slug}/v/schedule"


def _norm_team(name: str) -> str:
    """Collapse the name variants gobound uses for the same school."""
    n = name.strip().lower()
    n = re.sub(r'\bsaint\b', 'st', n)
    n = re.sub(r'\bst\.', 'st', n)
    n = re.sub(r'\bshawnee mission\b', 'sm', n)
    n = re.sub(r'\bblue valley\b', 'bv', n)
    n = re.sub(r'[^a-z0-9 ]', '', n)
    return re.sub(r'\s+', ' ', n).strip()

# Date cell reads "Fri 10/16/26" — match the date wherever it sits in the cell.
_DATE_RE = re.compile(r'(\d{1,2}/\d{1,2}/\d{2,4})')


class HighSchoolFootballScraper(BaseScraper):
    name = "HS Football"

    def fetch(self) -> list[Event]:
        # Use Playwright so gobound.com sees a real browser (plain requests
        # are blocked by gobound on cloud/CI IP ranges).
        try:
            from playwright.sync_api import sync_playwright
            use_playwright = True
        except ImportError:
            use_playwright = False

        raw: list[Event] = []
        if use_playwright:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(user_agent=UA)
                for slug, school in SCHOOLS.items():
                    try:
                        games = self._fetch_school_playwright(context, slug, school)
                        raw.extend(games)
                    except Exception as e:
                        self.logger.warning(f"  {school}: failed — {e}")
                browser.close()
        else:
            for slug, school in SCHOOLS.items():
                try:
                    games = self._fetch_school_requests(slug, school)
                    raw.extend(games)
                except Exception as e:
                    self.logger.warning(f"  {school}: failed — {e}")

        # Deduplicate: same two teams on the same date appear twice when both
        # schools are in our list. Team names must be normalised first — gobound
        # writes the same school differently depending on whose page it is on
        # ("St. Thomas Aquinas" vs "Saint Thomas Aquinas", "SM West" vs
        # "Shawnee Mission West"), which previously let both copies through.
        seen: set[tuple] = set()
        events: list[Event] = []
        for e in raw:
            parts = e.title.split(" vs ") if " vs " in e.title else e.title.split(" @ ")
            key = (frozenset(_norm_team(p) for p in parts), e.start_date.date())
            if key not in seen:
                seen.add(key)
                events.append(e)

        if events:
            self._write_cache(events)
            self.logger.info(f"HS Football: {len(events)} unique games fetched ({len(raw)} before dedup)")
            return events

        # gobound blocks datacenter IP ranges, so a run that works from a home
        # connection can still come back empty from CI. The season schedule is
        # fixed well in advance, so serve the last good scrape rather than
        # dropping the section.
        cached = self._read_cache()
        if cached:
            self.logger.warning(
                f"HS Football: live fetch returned nothing — falling back to "
                f"{len(cached)} cached games from {self._cache_age()}"
            )
            return cached

        self.logger.warning("HS Football: live fetch returned nothing and no cache available")
        return []

    # ── Season cache ──────────────────────────────────────────────────────────

    def _write_cache(self, events: list[Event]) -> None:
        payload = {
            "scraped_at": datetime.now(CENTRAL).isoformat(),
            "games": [
                {
                    "title": e.title,
                    "start_date": e.start_date.isoformat(),
                    "location": e.location,
                    "description": e.description,
                    "url": e.url,
                }
                for e in events
            ],
        }
        try:
            CACHE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as e:
            self.logger.warning(f"Could not write schedule cache: {e}")

    def _read_cache(self) -> list[Event]:
        try:
            payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
        events = []
        for g in payload.get("games", []):
            try:
                events.append(Event(
                    title=g["title"],
                    start_date=datetime.fromisoformat(g["start_date"]),
                    end_date=None,
                    location=g["location"],
                    city="Overland Park",
                    description=g.get("description", ""),
                    url=g["url"],
                    source="HS Football",
                    image_url=None,
                    cost="Free",
                    category="Sports & Fitness",
                ))
            except Exception:
                continue
        return events

    def _cache_age(self) -> str:
        try:
            payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            return payload.get("scraped_at", "unknown")[:10]
        except Exception:
            return "unknown"

    def _parse_html(self, html: str, school: str, url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", class_="table-sm")
        if not table:
            return []
        events = []
        for row in table.find_all("tr")[1:]:
            cells = [td.get_text(" ", strip=True) for td in row.find_all(["td", "th"])]
            if len(cells) < 6:
                continue
            event = self._parse_row(cells, school, url)
            if event:
                events.append(event)
        return events

    def _fetch_school_playwright(self, context, slug: str, school: str) -> list[Event]:
        url = BASE_URL.format(slug=slug)
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_selector("table.table-sm", timeout=8000)
            html = page.content()
        finally:
            page.close()
        return self._parse_html(html, school, url)

    def _fetch_school_requests(self, slug: str, school: str) -> list[Event]:
        url = BASE_URL.format(slug=slug)
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return self._parse_html(resp.text, school, url)

    def _parse_row(self, cells: list[str], school: str, url: str) -> Event | None:
        try:
            date_str  = cells[0].strip()   # "Fri 10/16/26"
            opp_raw   = cells[1].strip()   # "vsBlue Valley Northwest" or "@Olathe West"
            time_raw  = cells[2].strip()   # "7:00 PMCT"
            location  = cells[5].strip()

            if not date_str or not opp_raw:
                return None

            # Pull the date out rather than parsing the whole cell: gobound
            # prefixes it with a weekday ("Fri 10/16/26") and has changed that
            # formatting before.
            m = _DATE_RE.search(date_str)
            if not m:
                self.logger.warning(f"{school}: unparsed date cell {date_str!r}")
                return None
            dt_naive = datetime.strptime(m.group(1), "%m/%d/%y")
            # Parse time — strip trailing timezone label (CT, ET, etc.)
            time_clean = re.sub(r"[A-Z]{2,4}$", "", time_raw).strip()
            if time_clean:
                try:
                    time_part = datetime.strptime(time_clean, "%I:%M %p")
                    dt_naive = dt_naive.replace(hour=time_part.hour, minute=time_part.minute)
                except ValueError:
                    pass  # keep midnight if unparseable
            start_date = CENTRAL.localize(dt_naive)

            # Parse home/away and opponent name
            if opp_raw.startswith("vs"):
                opponent = opp_raw[2:].strip()
                home_away = "Home"
            elif opp_raw.startswith("@"):
                opponent = opp_raw[1:].strip()
                home_away = "Away"
            else:
                opponent  = opp_raw
                home_away = ""

            # Skip TBD or empty opponent games
            if not opponent or opponent.upper() in ("TBD", "BYE"):
                return None

            matchup = f"{school} vs {opponent}" if home_away == "Home" else f"{school} @ {opponent}"

            # Keep the specific stadium name (after " - ") but drop redundant
            # prefixes like "Blue Valley District Activities Complex - Switzer Football Stadium"
            # → "Switzer Football Stadium"
            if " - " in location:
                loc_short = location.split(" - ", 1)[1].strip()
            else:
                loc_short = location.strip()
            if len(loc_short) > 65:
                loc_short = loc_short[:62] + "..."

            return Event(
                title=matchup,
                start_date=start_date,
                end_date=None,
                location=loc_short,
                city="Overland Park",
                description=home_away,
                url=url,
                source="HS Football",
                image_url=None,
                cost="Free",
                category="Sports & Fitness",
            )
        except Exception as e:
            self.logger.warning(f"{school}: row parse failed ({e}) — {cells[:3]}")
            return None
