from __future__ import annotations
"""
Scraper: Kansas City Royals (MLB Stats API)
============================================
Uses the free, no-key MLB Stats API to fetch the Royals' schedule.
"""

import requests
from datetime import datetime
import pytz

from .base import BaseScraper, Event

CENTRAL = pytz.timezone("America/Chicago")
API_URL = "https://statsapi.mlb.com/api/v1/schedule"
TEAM_ID = 118  # Kansas City Royals
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}


def _parse_dt(date_str: str, time_str: str = "") -> datetime | None:
    """Build a timezone-aware Central datetime from API date + time fields."""
    try:
        # gameDate is ISO UTC: "2026-09-05T18:10:00Z"
        raw = (time_str or date_str).rstrip("Z")
        dt = datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S")
        return pytz.utc.localize(dt).astimezone(CENTRAL)
    except ValueError:
        pass
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=12, minute=0)
        return CENTRAL.localize(dt)
    except ValueError:
        return None


class KCRoyalsScraper(BaseScraper):
    name = "KC Royals"

    def fetch(self) -> list[Event]:
        try:
            resp = requests.get(
                API_URL,
                params={"teamId": TEAM_ID, "season": 2026, "sportId": 1},
                headers=HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
        except Exception as e:
            self.logger.error(f"Fetch failed: {e}")
            return []

        data = resp.json()
        now = datetime.now(CENTRAL)
        events: list[Event] = []

        for date_block in data.get("dates", []):
            for game in date_block.get("games", []):
                # Skip spring training (type "S") and all-star (type "A")
                if game.get("gameType") not in ("R", "F", "D", "L", "W"):
                    continue

                start = _parse_dt(game.get("gameDate", ""))
                if not start or start < now:
                    continue

                teams = game.get("teams", {})
                away = teams.get("away", {}).get("team", {}).get("name", "")
                home = teams.get("home", {}).get("team", {}).get("name", "")
                title = f"{away} at {home}"

                venue = game.get("venue", {}).get("name", "Kauffman Stadium")
                city = "Kansas City"
                if "stadium" not in venue.lower() and "field" not in venue.lower():
                    # Away game — add city context
                    pass

                is_home = home == "Kansas City Royals"
                location = f"{venue}, Kansas City" if is_home else f"{venue}"

                events.append(Event(
                    title=title,
                    start_date=start,
                    end_date=None,
                    location=location,
                    city=city,
                    description="",
                    url="https://www.mlb.com/royals/schedule",
                    source="KC Royals",
                    image_url=None,
                    cost=None,
                    category="Sports & Fitness",
                ))

        self.logger.info(f"Fetched {len(events)} Royals games")
        return events
