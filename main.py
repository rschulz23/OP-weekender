"""
OP Weekender — Main Runner
======================================
Scrapes event sources, deduplicates, filters to the upcoming weekend,
and optionally publishes to Beehiiv.

Usage:
  python main.py                        # Scrape + save events.json
  python main.py --preview              # Print formatted event list to terminal
  python main.py --save-html            # Save rendered HTML to newsletter.html for review
  python main.py --draft                # Create a draft post in Beehiiv (safe, review before sending)
  python main.py --send                 # Create a confirmed/scheduled post in Beehiiv
  python main.py --date 2026-06-21      # Target a specific Saturday
  python main.py --draft --date 2026-06-21

Environment variables:
  BEEHIIV_API_KEY            Required for --draft / --send
  BEEHIIV_PUBLICATION_ID     Required for --draft / --send
  EVENTBRITE_TOKEN           Optional (not currently used; kept for future API access)
"""

import argparse
import logging
from datetime import datetime, timedelta
import pytz

import aggregator
import formatter
from scrapers.base import Event

logging.basicConfig(level=logging.INFO, format="%(name)s | %(levelname)s | %(message)s")
CENTRAL = pytz.timezone("America/Chicago")


def _next_weekend(from_date=None):
    today = from_date or datetime.now(CENTRAL)
    days_until_saturday = (5 - today.weekday()) % 7
    if today.weekday() == 6:
        days_until_saturday = 6
    saturday = today + timedelta(days=days_until_saturday)
    sunday   = saturday + timedelta(days=1)
    saturday = CENTRAL.localize(datetime(saturday.year, saturday.month, saturday.day))
    sunday   = CENTRAL.localize(datetime(sunday.year, sunday.month, sunday.day, 23, 59, 59))
    return saturday, sunday


def print_preview(events: list[Event]):
    print("\n" + "=" * 60)
    print("  OP Weekender — Preview")
    print("=" * 60)

    if not events:
        print("  No events found for this weekend.")
        return

    current_day = None
    for e in events:
        day = e.start_date.strftime("%A, %B %-d")
        if day != current_day:
            print(f"\n📅  {day}")
            print("-" * 40)
            current_day = day

        time_str  = e.start_date.strftime("%-I:%M %p") if e.start_date.hour != 0 else "All day"
        cost_str  = f" · {e.cost}" if e.cost else ""
        print(f"  🔹 {e.title}")
        print(f"     {time_str} · {e.location}{cost_str}")
        print(f"     {e.source} → {e.url}")
        if e.description:
            snippet = e.description[:120] + ("..." if len(e.description) > 120 else "")
            print(f"     {snippet}")
        print()

    print(f"  Total: {len(events)} events")
    print("=" * 60 + "\n")


def build_post_title(saturday: datetime, sunday: datetime) -> str:
    return f"OP Weekender: {saturday.strftime('%B %-d')}–{sunday.strftime('%-d, %Y')}"


def build_subtitle(events: list[Event], saturday: datetime) -> str:
    """Generate a preview-text subtitle from the top highlights."""
    highlights = [e.title for e in events[:3]]
    month_str = saturday.strftime("%B %-d")
    if highlights:
        return f"This weekend ({month_str}): {' · '.join(highlights)} + more"
    return f"Your guide to the best events in Johnson County this weekend ({month_str})"


def main():
    parser = argparse.ArgumentParser(description="OP Weekender")
    parser.add_argument("--preview",   action="store_true", help="Print events to terminal")
    parser.add_argument("--save-html", action="store_true", help="Save rendered HTML to newsletter.html")
    parser.add_argument("--draft",     action="store_true", help="Push as draft to Beehiiv (safe — won't send)")
    parser.add_argument("--send",      action="store_true", help="Push as confirmed post to Beehiiv (will send!)")
    parser.add_argument("--date",      type=str,            help="Target Saturday (YYYY-MM-DD)")
    args = parser.parse_args()

    # ── Resolve target weekend ────────────────────────────────────────────────
    target_saturday = None
    if args.date:
        target_saturday = CENTRAL.localize(datetime.strptime(args.date, "%Y-%m-%d"))

    saturday, sunday = _next_weekend(target_saturday)

    # ── Scrape events ─────────────────────────────────────────────────────────
    events = aggregator.run(target_saturday=target_saturday)
    aggregator.events_to_json(events, "events.json")

    if args.preview:
        print_preview(events)

    # ── Render HTML ───────────────────────────────────────────────────────────
    html = formatter.render(events, saturday, sunday)

    if args.save_html:
        with open("newsletter.html", "w") as f:
            f.write(html)
        print(f"✅  Saved to newsletter.html ({len(html):,} bytes)")

    # ── Beehiiv publish ───────────────────────────────────────────────────────
    if args.draft or args.send:
        from beehiiv import BeehiivClient

        client  = BeehiivClient()
        title   = build_post_title(saturday, sunday)
        subtitle = build_subtitle(events, saturday)
        is_draft = not args.send

        result = client.create_post(
            title=title,
            html=html,
            subtitle=subtitle,
            draft=is_draft,
            content_tags=["weekend", "events", "johnson-county"],
        )

        post = result.get("data", result)
        status   = post.get("status", "unknown")
        post_url = post.get("web_url") or post.get("url") or "—"

        print(f"\n{'📝 Draft' if is_draft else '🚀 Post'} created in Beehiiv!")
        print(f"   Title:  {title}")
        print(f"   Status: {status}")
        print(f"   URL:    {post_url}")
        if is_draft:
            print("\n   Review it in your Beehiiv dashboard before sending.")
    elif not args.preview and not args.save_html:
        print(f"\n✅  {len(events)} weekend events found. Options:")
        print("   --preview    Print events to terminal")
        print("   --save-html  Save newsletter.html for review")
        print("   --draft      Push draft to Beehiiv")
        print("   --send       Publish to Beehiiv immediately")


if __name__ == "__main__":
    main()
