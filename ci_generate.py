"""
OP Weekender — CI Generator
================================
Runs in GitHub Actions (or any headless Linux environment).
No pbcopy, no webbrowser — saves newsletter.html and optionally
sends it to you via email so it's ready to paste into MailerLite.

Environment variables (set as GitHub Actions Secrets):
  NOTIFY_EMAIL        Your email address to receive the newsletter
  GMAIL_ADDRESS       Gmail address used to send (e.g. yourbot@gmail.com)
  GMAIL_APP_PASSWORD  Gmail App Password (not your regular password)
                      Create one at: https://myaccount.google.com/apppasswords

If email vars are absent the script still succeeds — HTML is saved
as a build artifact accessible from the Actions run page.
"""

from __future__ import annotations

import os
import sys
import logging
import smtplib
import ssl
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import pytz

import aggregator
import formatter

logging.basicConfig(
    level=logging.INFO,
    format="%(name)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("CI")
CENTRAL = pytz.timezone("America/Chicago")

OUTPUT_FILE = "newsletter.html"


def _next_weekend():
    today = datetime.now(CENTRAL)
    days_until_friday = (4 - today.weekday()) % 7
    if today.weekday() == 6:
        days_until_friday = 5  # next Friday
    friday   = today + timedelta(days=days_until_friday)
    saturday = friday + timedelta(days=1)
    sunday   = friday + timedelta(days=2)
    friday   = CENTRAL.localize(datetime(friday.year,   friday.month,   friday.day))
    saturday = CENTRAL.localize(datetime(saturday.year, saturday.month, saturday.day))
    sunday   = CENTRAL.localize(datetime(sunday.year,   sunday.month,   sunday.day, 23, 59, 59))
    return friday, saturday, sunday


def _health_report(silent: list[str]) -> str:
    """Plain-text block naming any source that returned nothing this run.

    A source going quiet is how a site changing its markup shows up: the
    newsletter still builds and still looks fine, just without that source.
    Surfacing it here is the only place it gets seen before the send.
    """
    if not silent:
        return "\nAll sources reported events.\n"
    return (
        f"\n{'=' * 52}\n"
        f"HEADS UP — {len(silent)} source(s) returned no events:\n"
        + "".join(f"  - {name}\n" for name in silent)
        + "\nThat is expected when a venue genuinely has nothing on, but a\n"
          "source that normally reports every week has probably broken.\n"
        + "=" * 52 + "\n"
    )


def send_email(html: str, saturday: datetime, subject: str, silent: list[str]) -> bool:
    """
    Email the newsletter HTML to NOTIFY_EMAIL.
    Returns True on success, False if env vars are missing or send fails.
    """
    notify_email   = os.environ.get("NOTIFY_EMAIL")
    gmail_address  = os.environ.get("GMAIL_ADDRESS")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")

    if not all([notify_email, gmail_address, gmail_password]):
        log.info("Email env vars not set — skipping email delivery")
        return False

    log.info(f"Sending newsletter to {notify_email}...")

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"]    = f"OP Weekender <{gmail_address}>"
    msg["To"]      = notify_email

    # ── Plain-text body with paste instructions ────────────────────────────
    instructions = (
        "Your OP Weekender is ready!\n\n"
        "To publish in MailerLite:\n"
        "  1. Campaigns -> Create campaign -> Regular campaign\n"
        "  2. Choose the 'Custom HTML' editor (NOT Drag & drop — its HTML\n"
        "     block caps out well below the size of this newsletter, and the\n"
        "     editor cannot be switched after the campaign is created)\n"
        "  3. Open the attached newsletter.html file\n"
        "     Select All (Cmd+A) -> Copy (Cmd+C) -> paste it in\n"
        "  4. Preview on desktop + mobile\n"
        "  5. Schedule send for Thursday morning\n\n"
        f"Subject line to use:\n  {subject}\n"
    )
    instructions += _health_report(silent)
    msg.attach(MIMEText(instructions, "plain"))

    # ── Inline HTML part (viewable directly in email client) ───────────────
    msg.attach(MIMEText(html, "html"))

    # ── Attachment: newsletter.html ────────────────────────────────────────
    attachment = MIMEBase("text", "html")
    attachment.set_payload(html.encode("utf-8"))
    encoders.encode_base64(attachment)
    attachment.add_header(
        "Content-Disposition",
        "attachment",
        filename=f"newsletter-{saturday.strftime('%Y-%m-%d')}.html",
    )
    msg.attach(attachment)

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
            server.login(gmail_address, gmail_password)
            server.sendmail(gmail_address, notify_email, msg.as_string())
        log.info("Email sent successfully")
        return True
    except Exception as e:
        log.error(f"Email send failed: {e}")
        return False


def main():
    friday, saturday, sunday = _next_weekend()
    date_label = f"{friday.strftime('%B %-d')} - {sunday.strftime('%B %-d, %Y')}"
    subject    = f"OP Weekender: {friday.strftime('%B %-d')}-{sunday.strftime('%-d, %Y')}"

    log.info(f"Targeting weekend: {date_label}")

    # ── Scrape ────────────────────────────────────────────────────────────
    log.info("Scraping events...")
    events = aggregator.run()
    silent = aggregator.silent_sources()
    aggregator.events_to_json(events, "events.json")
    log.info(f"{len(events)} unique weekend events found")

    if not events:
        log.warning("No events found — writing empty newsletter")

    # ── Render ────────────────────────────────────────────────────────────
    log.info("Rendering HTML...")
    html = formatter.render(events, friday, saturday, sunday)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    log.info(f"Saved {len(html):,} bytes to {OUTPUT_FILE}")

    # ── Email ─────────────────────────────────────────────────────────────
    email_sent = send_email(html, saturday, subject, silent)

    # ── Summary ───────────────────────────────────────────────────────────
    print()
    print("=" * 56)
    print(f"  OP Weekender — {date_label}")
    print(f"  {len(events)} events | {len(html):,} bytes")
    print(f"  Saved to: {OUTPUT_FILE}")
    print(f"  Email: {'sent' if email_sent else 'skipped (no credentials)'}")
    print(f"  Sources: {len(aggregator.LAST_RUN_COUNTS) - len(silent)} reporting, {len(silent)} silent")
    if silent:
        print(f"  Silent: {', '.join(silent)}")
    print("=" * 56)
    print(f"  Subject: {subject}")
    print("=" * 56)


if __name__ == "__main__":
    main()
