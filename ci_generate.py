"""
OP Weekender — CI Generator
================================
Runs in GitHub Actions (or any headless Linux environment).
No pbcopy, no webbrowser — saves newsletter.html and optionally
sends it to you via email so it's ready to paste into Beehiiv.

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
from beehiiv import BeehiivClient

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


def send_email(html: str, saturday: datetime, subject: str) -> bool:
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
        "To publish in Beehiiv:\n"
        "  1. Go to https://app.beehiiv.com/posts/new\n"
        "  2. Click the (+) block inserter\n"
        "  3. Choose 'HTML' block (under 'Advanced' or search 'HTML')\n"
        "  4. Open the attached newsletter.html file\n"
        "     Select All (Cmd+A) -> Copy (Cmd+C)\n"
        "  5. Paste (Cmd+V) in the Beehiiv HTML block\n"
        "  6. Preview on desktop + mobile\n"
        "  7. Schedule send for Thursday morning\n\n"
        f"Subject line to use:\n  {subject}\n"
    )
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


def create_beehiiv_draft(html: str, subject: str, saturday: datetime) -> bool:
    """
    Create a draft post in Beehiiv via API.
    Returns True on success, False if credentials are missing or call fails.
    """
    api_key = os.environ.get("BEEHIIV_API_KEY")
    pub_id  = os.environ.get("BEEHIIV_PUBLICATION_ID")

    if not api_key or not pub_id:
        log.info("Beehiiv credentials not set — skipping draft creation")
        return False

    try:
        client = BeehiivClient(api_key=api_key, publication_id=pub_id)
        result = client.create_post(
            title=subject,
            html=html,
            subtitle=f"Your weekend guide to Overland Park — {saturday.strftime('%B %-d, %Y')}",
            draft=True,
        )
        post = result.get("data", result)
        post_url = post.get("web_url") or post.get("url") or ""
        log.info(f"Beehiiv draft created: {post_url}")
        return True
    except Exception as e:
        log.error(f"Beehiiv draft creation failed: {e}")
        return False


def main():
    friday, saturday, sunday = _next_weekend()
    date_label = f"{friday.strftime('%B %-d')} - {sunday.strftime('%B %-d, %Y')}"
    subject    = f"OP Weekender: {friday.strftime('%B %-d')}-{sunday.strftime('%-d, %Y')}"

    log.info(f"Targeting weekend: {date_label}")

    # ── Scrape ────────────────────────────────────────────────────────────
    log.info("Scraping events...")
    events = aggregator.run()
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
    email_sent = send_email(html, saturday, subject)

    # ── Beehiiv draft ─────────────────────────────────────────────────────
    draft_created = create_beehiiv_draft(html, subject, saturday)

    # ── Summary ───────────────────────────────────────────────────────────
    print()
    print("=" * 56)
    print(f"  OP Weekender — {date_label}")
    print(f"  {len(events)} events | {len(html):,} bytes")
    print(f"  Saved to: {OUTPUT_FILE}")
    print(f"  Email: {'sent' if email_sent else 'skipped (no credentials)'}")
    print(f"  Beehiiv draft: {'created ✅' if draft_created else 'skipped (no credentials)'}")
    print("=" * 56)
    print(f"  Subject: {subject}")
    print("=" * 56)


if __name__ == "__main__":
    main()
