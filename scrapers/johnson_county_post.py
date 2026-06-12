from __future__ import annotations
"""
Scraper: Johnson County Post
Source: https://johnsoncountypost.com/calendar/
Method: Playwright (headless Chromium) + BeautifulSoup

The calendar is rendered by a CitySpark widget (Vue.js SPA).
Bot detection blocks headless Chrome by UA — spoofing a real Chrome UA bypasses it.

CitySpark event card structure:
  <div class="csEvWrap" data-date="2026-06-13T00:00:00Z">
    <a href="#/details/{slug}/{id}/{datetime}">
      <div class="csOneLine"><span>{title}</span></div>
      <div class="cityVenue"><span>{venue}</span> | <span>{city, state}</span></div>
      <span> {time} </span>         ← inside .csIconRow
    </a>
  </div>
"""

from datetime import datetime
from dateutil import parser as dateparser
import re
import pytz

from .base import BaseScraper, Event

CENTRAL      = pytz.timezone("America/Chicago")
CALENDAR_URL = "https://johnsoncountypost.com/calendar/"
REAL_UA      = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class JohnsonCountyPostScraper(BaseScraper):
    name = "JohnsonCountyPost"

    def fetch(self) -> list[Event]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.logger.warning("Playwright not installed — skipping JoCo Post")
            return []

        from bs4 import BeautifulSoup

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=REAL_UA)
            page = context.new_page()

            # Remove the webdriver flag that bot detectors check
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            try:
                page.goto(CALENDAR_URL, wait_until="domcontentloaded", timeout=30000)
                # Wait for CitySpark widget to render event cards
                page.wait_for_selector(".csEvWrap", timeout=12000)
            except Exception as e:
                self.logger.warning(f"Page load issue: {e}")
                browser.close()
                return []

            # Give Vue.js time to finish rendering
            page.wait_for_timeout(2000)
            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, "lxml")
        return self._parse(soup)

    def _parse(self, soup) -> list[Event]:
        from bs4 import BeautifulSoup

        events = []
        cards = soup.find_all("div", class_=re.compile(r"csEvWrap"))

        for card in cards:
            try:
                # Date from data-date attribute (ISO 8601 UTC)
                date_str = card.get("data-date", "")
                if not date_str:
                    continue
                start_date = dateparser.parse(date_str)
                if start_date and start_date.tzinfo is None:
                    start_date = CENTRAL.localize(start_date)
                elif start_date:
                    start_date = start_date.astimezone(CENTRAL)

                # Title
                title_tag = card.find(class_="csOneLine")
                title = title_tag.get_text(strip=True) if title_tag else ""
                if not title:
                    continue

                # Append time from the icon row (e.g. "8:00 am")
                time_tag = card.find(class_="csIconRow")
                if time_tag:
                    time_text = time_tag.get_text(strip=True)
                    time_match = re.search(r'\d+:\d+\s*[ap]m', time_text, re.I)
                    if time_match:
                        try:
                            time_only = dateparser.parse(time_match.group())
                            if time_only:
                                start_date = start_date.replace(
                                    hour=time_only.hour,
                                    minute=time_only.minute,
                                    second=0,
                                )
                        except Exception:
                            pass

                # Location
                venue_div = card.find(class_="cityVenue")
                if venue_div:
                    spans = venue_div.find_all("span")
                    parts = [s.get_text(strip=True) for s in spans if s.get_text(strip=True) and s.get_text(strip=True) != "|"]
                    location = " | ".join(parts) if parts else "Johnson County, KS"
                    city = parts[-1].split(",")[0].strip() if parts else "Johnson County"
                else:
                    location = "Johnson County, KS"
                    city     = "Johnson County"

                # URL — hash-based SPA link, construct full URL
                link = card.find("a", href=True)
                href = link["href"] if link else ""
                url = CALENDAR_URL + href if href.startswith("#") else (href or CALENDAR_URL)

                # Image from inline background-image style
                img_div = card.find(class_=re.compile(r"csimg|csImg"))
                image_url = None
                if img_div:
                    style = img_div.get("style", "")
                    img_match = re.search(r'url\(["\']?([^"\']+)["\']?\)', style)
                    if img_match:
                        image_url = img_match.group(1)

                events.append(Event(
                    title=title,
                    start_date=start_date,
                    end_date=None,
                    location=location,
                    city=city,
                    description="",
                    url=url,
                    source="Johnson County Post",
                    image_url=image_url,
                ))
            except Exception as e:
                self.logger.warning(f"Card parse error: {e}")

        self.logger.info(f"Parsed {len(events)} events from CitySpark widget")
        return events
