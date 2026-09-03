from __future__ import annotations
"""
Scraper: High School Football Schedules (gobound.com)
======================================================
Scrapes varsity football schedules for 13 JoCo-area schools and returns
games falling on the target weekend (Fri–Sun) as Event objects with
category = "High School Football".
"""

import re
import requests
from datetime import datetime
from bs4 import BeautifulSoup
import pytz

from .base import BaseScraper, Event

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


class HighSchoolFootballScraper(BaseScraper):
    name = "HS Football"

    def fetch(self) -> list[Event]:
        raw: list[Event] = []
        for slug, school in SCHOOLS.items():
            try:
                games = self._fetch_school(slug, school)
                raw.extend(games)
            except Exception as e:
                self.logger.warning(f"  {school}: failed — {e}")

        # Deduplicate: same two teams on the same date appear twice when both
        # schools are in our list. Key on sorted team names + date.
        seen: set[tuple] = set()
        events: list[Event] = []
        for e in raw:
            parts = e.title.split(" vs ") if " vs " in e.title else e.title.split(" @ ")
            key = (frozenset(p.strip() for p in parts), e.start_date.date())
            if key not in seen:
                seen.add(key)
                events.append(e)

        self.logger.info(f"HS Football: {len(events)} unique games fetched ({len(raw)} before dedup)")
        return events

    def _fetch_school(self, slug: str, school: str) -> list[Event]:
        url = BASE_URL.format(slug=slug)
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", class_="table-sm")
        if not table:
            return []

        events = []
        for row in table.find_all("tr")[1:]:  # skip header row
            cells = [td.get_text(" ", strip=True) for td in row.find_all(["td", "th"])]
            if len(cells) < 6:
                continue
            event = self._parse_row(cells, school, url)
            if event:
                events.append(event)
        return events

    def _parse_row(self, cells: list[str], school: str, url: str) -> Event | None:
        try:
            date_str  = cells[0].strip()   # "9/4/26"
            opp_raw   = cells[1].strip()   # "vsBlue Valley Northwest" or "@Olathe West"
            time_raw  = cells[2].strip()   # "7:00 PMCT"
            location  = cells[5].strip()

            if not date_str or not opp_raw:
                return None

            # Parse date
            dt_naive = datetime.strptime(date_str, "%m/%d/%y")
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
        except Exception:
            return None
