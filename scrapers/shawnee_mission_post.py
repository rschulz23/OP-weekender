from __future__ import annotations
"""
Scraper: Shawnee Mission Post
Source: https://shawneemissionpost.com/events/
Method: WordPress RSS feed + HTML event listing fallback

Shawnee Mission Post is the primary local news source for Johnson County.
Their events calendar covers Overland Park, Shawnee, Lenexa, Leawood, and more.
"""

import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime
from dateutil import parser as dateparser
import pytz

from .base import BaseScraper, Event, HEADERS

CENTRAL = pytz.timezone("America/Chicago")

# Note: shawneemissionpost.com was compromised as of June 2026.
# Replaced with Overland Park Patch community calendar, which covers the same area.
RSS_URL = "https://patch.com/kansas/overland-park/calendar/rss"
EVENTS_URL = "https://patch.com/kansas/overland-park/calendar"


class ShawneeMissionPostScraper(BaseScraper):
    name = "ShawneeMissionPost"

    def fetch(self) -> list[Event]:
        events = []

        # --- Try RSS feed first (most reliable) ---
        try:
            feed = feedparser.parse(RSS_URL)
            if feed.entries:
                self.logger.info(f"RSS feed returned {len(feed.entries)} entries")
                for entry in feed.entries:
                    events.append(self._parse_rss_entry(entry))
                return [e for e in events if e is not None]
        except Exception as e:
            self.logger.warning(f"RSS failed, falling back to HTML: {e}")

        # --- HTML fallback ---
        resp = requests.get(EVENTS_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        events = self._parse_html(soup)
        return events

    def _parse_rss_entry(self, entry) -> Event | None:
        try:
            title = entry.get("title", "").strip()
            url = entry.get("link", "")
            summary = BeautifulSoup(entry.get("summary", ""), "lxml").get_text(" ", strip=True)
            image_url = None

            # Pull first <img> from content if available
            content_html = entry.get("content", [{}])[0].get("value", "") if entry.get("content") else ""
            if content_html:
                img_soup = BeautifulSoup(content_html, "lxml")
                img_tag = img_soup.find("img")
                if img_tag:
                    image_url = img_tag.get("src")

            # Parse date
            published = entry.get("published", entry.get("updated", ""))
            try:
                start_date = dateparser.parse(published)
                if start_date and start_date.tzinfo is None:
                    start_date = CENTRAL.localize(start_date)
            except Exception:
                start_date = datetime.now(CENTRAL)

            return Event(
                title=title,
                start_date=start_date,
                end_date=None,
                location="Johnson County, KS",
                city="Johnson County",
                description=summary[:500],
                url=url,
                source="Overland Park Patch",
                image_url=image_url,
            )
        except Exception as e:
            self.logger.warning(f"Could not parse RSS entry: {e}")
            return None

    def _parse_html(self, soup: BeautifulSoup) -> list[Event]:
        """
        Fallback HTML parser for the SMP events page.
        The page uses The Events Calendar plugin (common WordPress pattern).
        """
        events = []
        # The Events Calendar plugin wraps each event in an <article> with class 'type-tribe_events'
        articles = soup.find_all("article", class_=lambda c: c and "tribe_events" in c)

        for article in articles:
            try:
                title_tag = article.find(class_="tribe-event-url") or article.find("h2")
                title = title_tag.get_text(strip=True) if title_tag else "Untitled"
                url = title_tag.get("href", EVENTS_URL) if title_tag and title_tag.name == "a" else EVENTS_URL

                date_tag = article.find(class_="tribe-event-schedule-details")
                date_str = date_tag.get_text(strip=True) if date_tag else ""
                try:
                    start_date = dateparser.parse(date_str, fuzzy=True)
                    if start_date and start_date.tzinfo is None:
                        start_date = CENTRAL.localize(start_date)
                except Exception:
                    start_date = datetime.now(CENTRAL)

                desc_tag = article.find(class_="tribe-events-list-event-description")
                description = desc_tag.get_text(" ", strip=True)[:500] if desc_tag else ""

                venue_tag = article.find(class_="tribe-venue")
                location = venue_tag.get_text(" ", strip=True) if venue_tag else "Johnson County, KS"

                img_tag = article.find("img")
                image_url = img_tag.get("src") if img_tag else None

                events.append(Event(
                    title=title,
                    start_date=start_date,
                    end_date=None,
                    location=location,
                    city="Johnson County",
                    description=description,
                    url=url,
                    source="Overland Park Patch",
                    image_url=image_url,
                ))
            except Exception as e:
                self.logger.warning(f"Could not parse HTML article: {e}")

        return events
