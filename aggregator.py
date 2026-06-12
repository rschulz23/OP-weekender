"""
Aggregator: runs all scrapers, deduplicates results, and filters to
weekend events (Saturday + Sunday) within a target date window.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Optional
import pytz
import logging

from scrapers import ALL_SCRAPERS
from scrapers.base import Event

CENTRAL = pytz.timezone("America/Chicago")
logger = logging.getLogger("Aggregator")


def _next_weekend(from_date: Optional[datetime] = None) -> tuple[datetime, datetime]:
    """
    Returns (saturday, sunday) for the upcoming weekend relative to from_date.
    If from_date is a Saturday or Sunday, returns the current weekend.
    """
    today = from_date or datetime.now(CENTRAL)
    # weekday(): Monday=0 ... Saturday=5, Sunday=6
    days_until_saturday = (5 - today.weekday()) % 7
    if days_until_saturday == 0 and today.weekday() == 5:
        days_until_saturday = 0
    elif today.weekday() == 6:
        days_until_saturday = 6  # next Saturday

    saturday = today + timedelta(days=days_until_saturday)
    sunday = saturday + timedelta(days=1)

    saturday = CENTRAL.localize(datetime(saturday.year, saturday.month, saturday.day))
    sunday = CENTRAL.localize(datetime(sunday.year, sunday.month, sunday.day, 23, 59, 59))

    return saturday, sunday


def _is_duplicate(a: Event, b: Event, threshold: float = 0.85) -> bool:
    """
    Returns True if two events are likely duplicates based on title similarity
    and date proximity (within 1 day).
    """
    title_ratio = SequenceMatcher(None, a.title.lower(), b.title.lower()).ratio()
    if title_ratio < threshold:
        return False

    date_diff = abs((a.start_date - b.start_date).total_seconds())
    return date_diff < 86400  # within 24 hours


def deduplicate(events: list[Event]) -> list[Event]:
    """Remove near-duplicate events, keeping the one with the most detail."""
    unique: list[Event] = []
    for event in events:
        is_dup = False
        for i, existing in enumerate(unique):
            if _is_duplicate(event, existing):
                # Keep whichever has a longer description or an image
                if len(event.description) > len(existing.description) or (event.image_url and not existing.image_url):
                    unique[i] = event
                is_dup = True
                break
        if not is_dup:
            unique.append(event)
    return unique


def filter_weekend(events: list[Event], saturday: datetime, sunday: datetime) -> list[Event]:
    """Keep only events that fall on the target Saturday or Sunday."""
    result = []
    for e in events:
        # Ensure timezone-aware comparison
        start = e.start_date
        if start.tzinfo is None:
            start = CENTRAL.localize(start)

        if saturday.date() <= start.date() <= sunday.date():
            result.append(e)

    return result


def sort_events(events: list[Event]) -> list[Event]:
    """Sort by date, then city, then title."""
    return sorted(events, key=lambda e: (e.start_date, e.city, e.title))


def run(
    target_saturday: Optional[datetime] = None,
    scraper_classes=None,
) -> list[Event]:
    """
    Main entry point. Runs all scrapers, deduplicates, filters to weekend,
    and returns sorted events.

    Args:
        target_saturday: Override which weekend to target.
        scraper_classes: Override which scrapers to use (defaults to ALL_SCRAPERS).
    """
    scraper_classes = scraper_classes or ALL_SCRAPERS
    saturday, sunday = _next_weekend(target_saturday)

    logger.info(f"Targeting weekend: {saturday.strftime('%A %b %d')} – {sunday.strftime('%A %b %d, %Y')}")
    logger.info(f"Running {len(scraper_classes)} scrapers...")

    all_events: list[Event] = []
    for cls in scraper_classes:
        scraper = cls()
        events = scraper.safe_fetch()
        all_events.extend(events)

    logger.info(f"Total raw events: {len(all_events)}")

    weekend_events = filter_weekend(all_events, saturday, sunday)
    logger.info(f"Weekend events (before dedup): {len(weekend_events)}")

    unique_events = deduplicate(weekend_events)
    logger.info(f"Unique weekend events: {len(unique_events)}")

    return sort_events(unique_events)


def events_to_json(events: list[Event], path: str = "events.json") -> None:
    """Save events to a JSON file for inspection or backup."""
    with open(path, "w") as f:
        json.dump([e.to_dict() for e in events], f, indent=2, default=str)
    logger.info(f"Saved {len(events)} events to {path}")
