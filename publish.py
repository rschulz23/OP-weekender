"""
OP Weekender — One-Click Beehiiv Publisher
==============================================
Scrapes events, renders the newsletter HTML, copies it to your clipboard,
and opens your Beehiiv new-post editor in one command.

Usage:
  python publish.py                    # Target next weekend
  python publish.py --date 2026-06-21  # Target a specific Saturday
  python publish.py --html-only        # Just copy HTML, don't open browser

Beehiiv steps after running:
  1. In the editor that opens, click the (+) block inserter
  2. Choose "HTML" (or "Embed" > "Custom HTML")
  3. Paste (Cmd+V) — your full newsletter drops in
  4. Preview, then schedule for Thursday morning
"""

from __future__ import annotations

import argparse
import subprocess
import webbrowser
import sys
from datetime import datetime, timedelta
import pytz
import logging

import aggregator
import formatter

logging.basicConfig(level=logging.INFO, format="%(name)s | %(levelname)s | %(message)s")
CENTRAL = pytz.timezone("America/Chicago")

# Your Beehiiv new-post URL — opens straight to the editor
BEEHIIV_NEW_POST_URL = "https://app.beehiiv.com/posts/new"


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


def copy_to_clipboard(text: str) -> bool:
    """Copy text to macOS clipboard using pbcopy. Returns True on success."""
    try:
        proc = subprocess.run(
            ["pbcopy"],
            input=text.encode("utf-8"),
            check=True,
        )
        return proc.returncode == 0
    except FileNotFoundError:
        print("⚠️  pbcopy not found — are you on macOS?")
        return False
    except Exception as e:
        print(f"⚠️  Clipboard copy failed: {e}")
        return False


def save_html(html: str, path: str = "newsletter.html"):
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    parser = argparse.ArgumentParser(description="OP Weekender — Beehiiv Publisher")
    parser.add_argument("--date",      type=str,  help="Target Saturday (YYYY-MM-DD)")
    parser.add_argument("--html-only", action="store_true",
                        help="Copy HTML to clipboard only, don't open browser")
    args = parser.parse_args()

    # ── Resolve target weekend ────────────────────────────────────────────────
    target_saturday = None
    if args.date:
        target_saturday = CENTRAL.localize(datetime.strptime(args.date, "%Y-%m-%d"))

    saturday, sunday = _next_weekend(target_saturday)
    date_label = f"{saturday.strftime('%B %-d')} - {sunday.strftime('%B %-d, %Y')}"

    print(f"\n📋  OP Weekender Publisher")
    print(f"    Weekend: {date_label}")
    print()

    # ── Scrape ────────────────────────────────────────────────────────────────
    print("Step 1/3  Scraping events...")
    events = aggregator.run(target_saturday=target_saturday)
    aggregator.events_to_json(events, "events.json")
    print(f"          {len(events)} weekend events found\n")

    if not events:
        print("⚠️  No events found for this weekend. Aborting.")
        sys.exit(0)

    # ── Render ────────────────────────────────────────────────────────────────
    print("Step 2/3  Rendering newsletter HTML...")
    html = formatter.render(events, saturday, sunday)
    save_html(html)
    print(f"          {len(html):,} bytes rendered → newsletter.html\n")

    # ── Clipboard ─────────────────────────────────────────────────────────────
    print("Step 3/3  Copying HTML to clipboard...")
    success = copy_to_clipboard(html)
    if success:
        print("          Copied!\n")
    else:
        print("          Could not copy automatically.")
        print("          Open newsletter.html and copy the contents manually.\n")

    # ── Open Beehiiv ──────────────────────────────────────────────────────────
    if not args.html_only:
        print(f"          Opening Beehiiv editor...")
        webbrowser.open(BEEHIIV_NEW_POST_URL)

    # ── Instructions ──────────────────────────────────────────────────────────
    subject = f"OP Weekender: {saturday.strftime('%B %-d')}-{sunday.strftime('%-d, %Y')}"
    print("─" * 56)
    print("  Next steps in Beehiiv:")
    print()
    print(f"  1. Set the subject line to:")
    print(f"     {subject}")
    print()
    print("  2. In the editor, click the (+) block inserter")
    print("  3. Choose 'HTML' block (under 'Advanced' or search 'HTML')")
    print("  4. Paste  Cmd+V  — your newsletter drops in")
    print("  5. Preview on desktop + mobile")
    print("  6. Schedule send for Thursday morning")
    print("─" * 56)
    print()


if __name__ == "__main__":
    main()
