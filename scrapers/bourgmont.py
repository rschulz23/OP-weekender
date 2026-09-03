from __future__ import annotations
"""
Scraper: Bourgmont Winery Events (bourgmont.com/events)
=========================================================
Squarespace eventlist page — parses article.eventlist-event blocks.
"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz

from .base import BaseScraper, Event

CENTRAL = pytz.timezone("America/Chicago")
URL = "https://www.bourgmont.com/events"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}


class BourgmontWineryScraper(BaseScraper):
    name = "Bourgmont Winery"

    def fetch(self) -> list[Event]:
        try:
            resp = requests.get(URL, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            self.logger.error(f"Fetch failed: {e}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        events: list[Event] = []

        for article in soup.find_all("article", class_="eventlist-event"):
            try:
                # Title
                title_tag = article.find(class_="eventlist-title")
                title = title_tag.get_text(strip=True) if title_tag else "Event"

                # Full date string e.g. "Thursday, September 4, 2026"
                date_li = article.find("li", class_="eventlist-meta-date")
                date_str = date_li.get_text(strip=True) if date_li else ""

                # Time e.g. "5:00 PM 8:00 PM" (start and end run together)
                time_li = article.find("li", class_="eventlist-meta-time")
                time_str = time_li.get_text(" ", strip=True).replace(" ", " ") if time_li else ""

                # Parse date
                date_clean = re.sub(r"^[A-Za-z]+,\s*", "", date_str).strip()
                try:
                    dt = datetime.strptime(date_clean, "%B %d, %Y")
                except ValueError:
                    continue

                # Parse start time from "5:00 PM 8:00 PM"
                time_match = re.match(r"(\d+:\d+\s*[AP]M)", time_str, re.IGNORECASE)
                if time_match:
                    try:
                        tp = datetime.strptime(time_match.group(1).strip(), "%I:%M %p")
                        dt = dt.replace(hour=tp.hour, minute=tp.minute)
                    except ValueError:
                        pass

                start_date = CENTRAL.localize(dt)

                # Link
                link = article.find("a", href=True)
                href = link["href"] if link else URL
                event_url = href if href.startswith("http") else f"https://www.bourgmont.com{href}"

                # Image
                img = article.find("img")
                image_url = img.get("src") or img.get("data-src") if img else None

                events.append(Event(
                    title=title,
                    start_date=start_date,
                    end_date=None,
                    location="Bourgmont Winery, 28700 W 199th St, Bucyrus, KS",
                    city="Bucyrus",
                    description="",
                    url=event_url,
                    source="Bourgmont Winery",
                    image_url=image_url,
                    cost=None,
                    category="Food & Drink",
                ))
            except Exception as e:
                self.logger.warning(f"Parse error: {e}")

        self.logger.info(f"Fetched {len(events)} events")
        return events
