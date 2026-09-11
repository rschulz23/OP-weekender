from __future__ import annotations
"""
Scraper: Park Place Leawood (parkplaceleawood.com/events)
==========================================================
The events page renders a month grid server-side; each occurrence links to a
detail page with the full ISO date in an ``event_date`` query parameter.

Only the current month is rendered, so the next month is pulled through the
same admin-ajax endpoint the calendar's own navigation uses — otherwise a
weekend straddling a month boundary would come back empty.

Start times live on the detail pages: one-off events carry a structured time
field, while recurring ones only state it in the body copy. Detail pages are
fetched once per event and cached, since recurring events (e.g. "Every
Friday") share one page across many occurrences. Their "Start" date is the
series start, not the occurrence, so dates always come from the calendar.

Everything here is filed under Community & Festivals: the district mixes live
music, food events and markets, and the shared categorizer reads these titles
poorly ("Wednesday Date Night" scores as Family & Kids on "date with kids").
"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pytz

from .base import BaseScraper, Event, HEADERS

CENTRAL = pytz.timezone("America/Chicago")
BASE = "https://parkplaceleawood.com"
URL = f"{BASE}/events/"
LOCATION = "Park Place, 11551 Ash St, Leawood, KS"

_AJAX_RE = re.compile(
    r"parkplaceEventsAjax\s*=\s*window\.parkplaceEventsAjax\s*\|\|\s*\{(.{0,400}?)\}",
    re.S,
)
_DATE_RE = re.compile(r'event_date=(\d{4}-\d{2}-\d{2})')

# "6:00 PM - 8:00 PM" (meridiem on both) / "6 - 8pm" (only on the last) / "7pm"
_RANGE_BOTH = re.compile(
    r'(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?\s*[–\-—]\s*\d{1,2}', re.IGNORECASE)
_RANGE_TAIL = re.compile(
    r'(\d{1,2})(?::(\d{2}))?\s*[–\-—]\s*\d{1,2}(?::\d{2})?\s*([ap])\.?m\.?', re.IGNORECASE)
_SINGLE = re.compile(r'(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?', re.IGNORECASE)

DEFAULT_HOUR, DEFAULT_MINUTE = 18, 0


def _extract_time(text: str) -> tuple[int, int] | None:
    """Pull the start time out of a time range or single time."""
    for pattern in (_RANGE_BOTH, _RANGE_TAIL, _SINGLE):
        m = pattern.search(text)
        if not m:
            continue
        hour = int(m.group(1)) % 12
        if m.group(3).lower() == "p":
            hour += 12
        return hour, int(m.group(2) or 0)
    return None


class ParkPlaceScraper(BaseScraper):
    name = "Park Place Leawood"

    def fetch(self) -> list[Event]:
        session = requests.Session()
        try:
            resp = session.get(URL, headers=HEADERS, timeout=25)
            resp.raise_for_status()
        except Exception as e:
            self.logger.error(f"Fetch failed: {e}")
            return []

        html = resp.text
        pages = [html]

        next_month = self._next_month_html(session, html)
        if next_month:
            pages.append(next_month)

        detail_cache: dict[str, tuple] = {}
        events: list[Event] = []
        now = datetime.now(CENTRAL)
        seen = set()

        for page in pages:
            for item in BeautifulSoup(page, "lxml").select(".parkplace-events-calendar-event"):
                try:
                    link = item.select_one("a[href]")
                    label = item.select_one(".parkplace-events-calendar-event-label")
                    if not link or not label:
                        continue

                    url = link["href"]
                    m = _DATE_RE.search(url)
                    if not m:
                        continue
                    day = datetime.strptime(m.group(1), "%Y-%m-%d")

                    title = label.get_text(strip=True)
                    key = (title, day.date())
                    if key in seen:
                        continue
                    seen.add(key)

                    detail_url = url.split("?")[0]
                    if detail_url not in detail_cache:
                        detail_cache[detail_url] = self._fetch_detail(session, detail_url)
                    (hour, minute), sub_location = detail_cache[detail_url]

                    start = CENTRAL.localize(day.replace(hour=hour, minute=minute))
                    if start < now:
                        continue

                    desc_tag = item.select_one(".parkplace-events-calendar-popover-description")
                    img_tag = item.select_one(".parkplace-events-calendar-popover-image")

                    events.append(Event(
                        title=title,
                        start_date=start,
                        end_date=None,
                        location=f"{sub_location}, {LOCATION}" if sub_location else LOCATION,
                        city="Leawood",
                        description=desc_tag.get_text(strip=True) if desc_tag else "",
                        url=url,
                        source="Park Place Leawood",
                        image_url=img_tag["src"] if img_tag and img_tag.get("src") else None,
                        cost=None,
                        category="Community & Festivals",
                    ))
                except Exception as e:
                    self.logger.warning(f"Parse error: {e}")

        events.sort(key=lambda e: e.start_date)
        self.logger.info(f"Fetched {len(events)} Park Place Leawood events")
        return events

    def _next_month_html(self, session: requests.Session, html: str) -> str | None:
        """Ask the calendar's own AJAX endpoint for next month's grid."""
        m = _AJAX_RE.search(html)
        if not m:
            self.logger.warning("Calendar AJAX config not found — current month only")
            return None
        block = m.group(1)
        try:
            ajax_url = re.search(r"ajaxUrl:\s*'([^']+)'", block).group(1)
            nonce = re.search(r"nonce:\s*'([^']+)'", block).group(1)
        except AttributeError:
            self.logger.warning("Calendar AJAX config unreadable — current month only")
            return None

        today = datetime.now(CENTRAL)
        nxt = (today.replace(day=1) + timedelta(days=32)).strftime("%Y-%m")
        try:
            r = session.post(
                ajax_url,
                data={"action": "parkplace_events_calendar_month", "nonce": nonce, "month": nxt},
                headers={**HEADERS, "X-Requested-With": "XMLHttpRequest"},
                timeout=25,
            )
            r.raise_for_status()
            return r.text
        except Exception as e:
            self.logger.warning(f"Next-month fetch failed ({nxt}): {e}")
            return None

    def _fetch_detail(self, session: requests.Session, url: str) -> tuple[tuple[int, int], str]:
        """Return ((hour, minute), sub_location) from an event's detail page."""
        try:
            r = session.get(url, headers=HEADERS, timeout=25)
            r.raise_for_status()
        except Exception as e:
            self.logger.warning(f"Detail fetch failed {url}: {e}")
            return (DEFAULT_HOUR, DEFAULT_MINUTE), ""

        soup = BeautifulSoup(r.text, "lxml")
        body = soup.select_one(".parkplace-single-event-content") or soup.select_one(".parkplace-single-event-copy")
        text = body.get_text(" ", strip=True) if body else ""

        sub_location = ""
        loc_m = re.search(r'Location:\s*(.+?)\s*(?:Time:|$)', text)
        if loc_m:
            sub_location = loc_m.group(1).strip(" .,-–")[:60]

        # One-off events carry a structured time field; recurring ones only
        # state it in the body ("Every Friday, 6:00 PM - 8:00 PM").
        timing = soup.select_one(".parkplace-single-event-timing")
        found = None
        if timing:
            found = _extract_time(timing.get_text(" ", strip=True))
        if not found:
            labelled = re.search(r'Time:\s*(.{0,60})', text)
            if labelled:
                found = _extract_time(labelled.group(1))
        if not found and text:
            found = _extract_time(text)

        return found or (DEFAULT_HOUR, DEFAULT_MINUTE), sub_location
