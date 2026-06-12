"""
Formatter: converts a list of Event objects into a newsletter-ready HTML string.

Design principles:
- All styles are INLINE (Beehiiv strips <style> and <link> tags)
- NO emoji characters — replaced with HTML entities or plain text to avoid
  UTF-8/Latin-1 encoding corruption in Beehiiv's editor
- Mobile-first single-column layout (max-width 600px)
- Events grouped by day (Saturday first, then Sunday)
- Within each day, events are grouped by category with a coloured pill header
- Each event card: title, time + location, cost badge, description snippet, source link
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional
import pytz

from scrapers.base import Event

CENTRAL = pytz.timezone("America/Chicago")

import re

# Matches any Unicode character outside the Basic Multilingual Plane (emoji, etc.)
# plus common emoji in the BMP (Emoticons, Misc Symbols, Dingbats ranges)
_EMOJI_RE = re.compile(
    "["
    "\U00010000-\U0010FFFF"   # supplementary planes (most emoji live here)
    "\U00002600-\U000027BF"   # Misc Symbols, Dingbats
    "\U0001F300-\U0001F9FF"   # Misc Symbols and Pictographs, Emoticons
    "\U0000FE00-\U0000FE0F"   # Variation Selectors (emoji modifiers)
    "\U000020D0-\U000020FF"   # Combining Diacritical Marks for Symbols
    "]+",
    flags=re.UNICODE,
)


def _strip_emoji(text: str) -> str:
    """Remove emoji and other non-ASCII-safe Unicode from scraped text."""
    return _EMOJI_RE.sub("", text).strip()


# ── Color palette ────────────────────────────────────────────────────────────
BRAND_BLUE    = "#1A3A5C"   # header background
BRAND_ORANGE  = "#E8621A"   # event title links, cost badge
LIGHT_BG      = "#F7F8FA"   # card background
BORDER_COLOR  = "#E2E6EA"   # card border
TEXT_PRIMARY  = "#1A1A2E"   # main text
TEXT_MUTED    = "#6B7280"   # meta text (time, location, source)
WHITE         = "#FFFFFF"
FREE_GREEN    = "#16A34A"

# Category pill colors — (background, text)
CATEGORY_COLORS: dict[str, tuple[str, str]] = {
    "Family & Kids":          ("#F59E0B", "#1A1A2E"),  # amber
    "Music & Entertainment":  ("#7C3AED", WHITE),       # purple
    "Arts & Culture":         ("#DB2777", WHITE),       # pink
    "Food & Drink":           ("#D97706", WHITE),       # dark amber
    "Sports & Fitness":       ("#059669", WHITE),       # emerald
    "Outdoors & Nature":      ("#16A34A", WHITE),       # green
    "Community & Festivals":  ("#2563EB", WHITE),       # blue
    "Workshops & Classes":    ("#0891B2", WHITE),       # cyan
    "Other":                  ("#6B7280", WHITE),       # gray
}

# Display order within each day section
CATEGORY_ORDER = [
    "Family & Kids",
    "Music & Entertainment",
    "Arts & Culture",
    "Food & Drink",
    "Sports & Fitness",
    "Outdoors & Nature",
    "Community & Festivals",
    "Workshops & Classes",
    "Other",
]

# Icons (text-safe — no emoji, just ASCII/HTML entities)
CATEGORY_ICONS: dict[str, str] = {
    "Family & Kids":          "&#9733;",   # star
    "Music & Entertainment":  "&#9835;",   # music note
    "Arts & Culture":         "&#9830;",   # diamond
    "Food & Drink":           "&#9749;",   # hot beverage
    "Sports & Fitness":       "&#9654;",   # play triangle
    "Outdoors & Nature":      "&#9752;",   # shamrock / leaf
    "Community & Festivals":  "&#10022;",  # 8-pointed star
    "Workshops & Classes":    "&#9998;",   # pencil
    "Other":                  "&#8226;",   # bullet
}


def _fmt_time(dt: datetime) -> str:
    """Return '9:00 AM' or 'All day' for midnight."""
    if dt.hour == 0 and dt.minute == 0:
        return "All day"
    return dt.strftime("%-I:%M %p")


def _cost_badge(cost: Optional[str]) -> str:
    if not cost:
        return ""
    color = FREE_GREEN if "free" in cost.lower() else BRAND_ORANGE
    return (
        f'<span style="display:inline-block;background:{color};color:{WHITE};'
        f'font-size:11px;font-weight:700;letter-spacing:0.5px;padding:2px 8px;'
        f'border-radius:20px;text-transform:uppercase;margin-left:8px;">'
        f'{cost}</span>'
    )


def _event_card(event: Event) -> str:
    time_str   = _fmt_time(event.start_date)
    cost_badge = _cost_badge(event.cost)
    title      = _strip_emoji(event.title)
    location   = _strip_emoji(event.location)
    raw_desc   = _strip_emoji(event.description)
    desc       = raw_desc[:180].rstrip()
    if raw_desc and len(raw_desc) > 180:
        desc += "..."

    img_html = ""
    if event.image_url:
        img_html = (
            f'<img src="{event.image_url}" alt="" '
            f'style="width:100%;max-height:200px;object-fit:cover;'
            f'border-radius:6px 6px 0 0;display:block;margin-bottom:0;" />'
        )

    return f"""
<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {BORDER_COLOR};border-radius:8px;background:{LIGHT_BG};margin-bottom:12px;overflow:hidden;">
  <tr>
    <td style="padding:0;">
      {img_html}
      <div style="padding:14px 16px 12px;">
        <a href="{event.url}" style="font-size:16px;font-weight:700;color:{BRAND_ORANGE};text-decoration:none;line-height:1.3;">{title}</a>{cost_badge}
        <div style="margin-top:5px;font-size:13px;color:{TEXT_MUTED};line-height:1.5;">
          {time_str} &nbsp;&middot;&nbsp; {location}
        </div>
        {f'<p style="margin:8px 0 0;font-size:13px;color:{TEXT_PRIMARY};line-height:1.6;">{desc}</p>' if desc else ''}
        <div style="margin-top:8px;font-size:11px;color:{TEXT_MUTED};">
          via <a href="{event.url}" style="color:{TEXT_MUTED};text-decoration:underline;">{event.source}</a>
        </div>
      </div>
    </td>
  </tr>
</table>"""


def _category_section(category: str, events: list[Event]) -> str:
    """Render a coloured category pill + its event cards."""
    if not events:
        return ""

    bg, fg = CATEGORY_COLORS.get(category, ("#6B7280", WHITE))
    icon   = CATEGORY_ICONS.get(category, "&bull;")
    cards  = "\n".join(_event_card(e) for e in events)

    return f"""
<table width="100%" cellpadding="0" cellspacing="0" style="margin:8px 0 6px;">
  <tr>
    <td>
      <span style="display:inline-block;background:{bg};color:{fg};font-size:11px;font-weight:700;letter-spacing:0.8px;text-transform:uppercase;padding:4px 14px;border-radius:20px;">
        {icon}&nbsp; {category}
      </span>
    </td>
  </tr>
</table>
<div style="margin-bottom:20px;">
  {cards}
</div>"""


def _day_section(label: str, events: list[Event]) -> str:
    """Render a full day block with events grouped by category."""
    if not events:
        return ""

    # Group events by category, preserving CATEGORY_ORDER
    grouped: dict[str, list[Event]] = {cat: [] for cat in CATEGORY_ORDER}
    for e in events:
        cat = e.category if e.category in grouped else "Other"
        grouped[cat].append(e)

    # Render category sections in order, skipping empty ones
    cat_sections = "".join(
        _category_section(cat, grouped[cat])
        for cat in CATEGORY_ORDER
        if grouped[cat]
    )

    return f"""
<table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:8px;">
  <tr>
    <td style="background:{BRAND_BLUE};border-radius:8px;padding:12px 18px;">
      <span style="font-size:20px;font-weight:900;color:{WHITE};letter-spacing:0.3px;">{label}</span>
    </td>
  </tr>
</table>
<div style="margin-bottom:28px;">
  {cat_sections}
</div>"""


def _header(saturday: datetime, sunday: datetime, total: int) -> str:
    date_range = f"{saturday.strftime('%B %-d')} &ndash; {sunday.strftime('%B %-d, %Y')}"
    return f"""
<table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND_BLUE};border-radius:10px 10px 0 0;margin-bottom:0;">
  <tr>
    <td style="padding:28px 24px 22px;text-align:center;">
      <div style="font-size:26px;font-weight:900;color:{WHITE};letter-spacing:-0.5px;line-height:1.2;">
        JoCo Weekend Guide
      </div>
      <div style="font-size:14px;color:rgba(255,255,255,0.8);margin-top:6px;">
        {date_range} &nbsp;&middot;&nbsp; {total} events across Johnson County
      </div>
    </td>
  </tr>
</table>
<table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND_ORANGE};margin-bottom:24px;border-radius:0 0 10px 10px;">
  <tr>
    <td style="padding:8px 24px;text-align:center;">
      <span style="font-size:12px;font-weight:600;color:{WHITE};letter-spacing:1px;text-transform:uppercase;">
        Overland Park &nbsp;&middot;&nbsp; Shawnee &nbsp;&middot;&nbsp; Lenexa &nbsp;&middot;&nbsp; Leawood &nbsp;&middot;&nbsp; Olathe
      </span>
    </td>
  </tr>
</table>"""


def _footer() -> str:
    return f"""
<table width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid {BORDER_COLOR};margin-top:32px;">
  <tr>
    <td style="padding:24px 0;text-align:center;">
      <p style="font-size:13px;color:{TEXT_MUTED};margin:0 0 6px;">
        Know of an event we missed? Reply to this email and we&#39;ll add it next week.
      </p>
      <p style="font-size:12px;color:{TEXT_MUTED};margin:0;">
        JoCo Weekend Guide &nbsp;&middot;&nbsp; Johnson County, Kansas
      </p>
    </td>
  </tr>
</table>"""


def _no_events_message() -> str:
    return (
        f'<p style="text-align:center;padding:40px 0;color:{TEXT_MUTED};font-size:16px;">'
        f'No events found for this weekend. Check back next week!</p>'
    )


def render(events: list[Event], saturday: datetime, sunday: datetime) -> str:
    """
    Render a full newsletter HTML string from a list of events.

    Events are grouped first by day (Saturday / Sunday), then by category
    within each day. Category assignment must be done before calling this
    (aggregator.run() handles it via categorize_all()).

    Returns:
        A single HTML string suitable for Beehiiv's body_content field.
        All characters are ASCII-safe HTML entities -- no raw Unicode emoji.
    """
    saturday_events = [e for e in events if e.start_date.date() == saturday.date()]
    sunday_events   = [e for e in events if e.start_date.date() == sunday.date()]

    body = _header(saturday, sunday, len(events))

    if not events:
        body += _no_events_message()
    else:
        sat_label = saturday.strftime("Saturday, %B %-d")
        sun_label = sunday.strftime("Sunday, %B %-d")
        body += _day_section(sat_label, saturday_events)
        body += _day_section(sun_label, sunday_events)

    body += _footer()

    return f"""
<div style="max-width:600px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:{TEXT_PRIMARY};">
  {body}
</div>"""
