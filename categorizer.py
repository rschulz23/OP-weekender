"""
Categorizer: assigns a display category to each Event based on
keyword scoring against title + description.

Categories (display order in newsletter):
  Family & Kids
  Music & Entertainment
  Arts & Culture
  Food & Drink
  Sports & Fitness
  Outdoors & Nature
  Community & Festivals
  Workshops & Classes
  Other

Design:
- Each category has a list of (keyword, weight) tuples
- Score = sum of weights for all keywords found in the text
- Event gets the highest-scoring category above the threshold (1.0)
- Ties broken by category priority order above
- "Other" is the fallback with no threshold requirement
"""

from __future__ import annotations
import re
from scrapers.base import Event

# ── Category definitions ──────────────────────────────────────────────────────
# (keyword, score_weight)  — keyword matched case-insensitively as whole word
# or substring where marked.  Higher weight = stronger signal.

CATEGORIES: list[tuple[str, list[tuple[str, float]]]] = [
    ("Family & Kids", [
        ("kid",         3.0),   # kids, kid-friendly
        ("children",    3.0),
        ("family",      2.5),
        ("toddler",     3.0),
        ("storytime",   3.0),
        ("story time",  3.0),
        ("youth",       1.0),   # reduced — "youth choir" should land in Music
        ("teen",        2.0),
        ("junior",      2.0),
        ("puppies",     2.0),   # puppies & storytime
        ("summer camp", 3.0),
        ("playground",  2.5),
        ("ages 3",      3.0),
        ("ages 5",      3.0),
        ("paw",         1.5),   # paw patrol, paw-tay
        ("baby",        2.0),
        ("infant",      2.0),
        ("parenting",   2.0),
        ("postpartum",  2.0),
    ]),

    ("Music & Entertainment", [
        ("concert",     3.0),
        ("live music",  3.5),
        ("band",        2.5),
        ("tribute",     3.0),
        ("orchestra",   3.0),
        ("symphony",    3.0),
        ("jazz",        3.0),
        ("blues",       2.5),
        ("country",     2.0),
        ("rock",        2.0),
        ("rapper",      2.5),
        ("dj ",         2.5),
        ("perform",     1.5),   # performance, performing
        ("theater",     2.0),   # catch-all; Arts has higher weights
        ("theatre",     2.0),
        ("comedy",      2.5),
        ("stand-up",    2.5),
        ("karaoke",     3.0),
        ("open mic",    3.0),
        ("beatles",     3.0),
        ("choir",       3.5),   # choir, choral — strong music signal
        ("choral",      3.5),
        ("musical",     3.0),   # stage musicals (also in Arts, but this ensures Music wins)
        ("oklahoma",    3.0),   # OKLAHOMA! the musical
        ("tasting room",1.5),   # often has live music
        ("center court concerts", 3.5),
    ]),

    ("Arts & Culture", [
        ("art",         1.5),   # art show, art fair
        ("gallery",     3.0),
        ("museum",      3.0),
        ("exhibit",     3.0),
        ("exhibition",  3.0),
        ("shakespeare", 3.5),
        ("oklahoma",    2.0),   # the musical (Music has higher weight — this is backup)
        ("musical",     2.0),   # Music category has higher weight for this
        ("play ",       1.5),   # theatrical play (space to avoid "playground")
        ("dance",       2.5),
        ("ballet",      3.0),
        ("film",        2.5),
        ("movie",       2.5),
        ("cinema",      3.0),
        ("history",     2.0),
        ("historic",    2.0),
        ("cultural",    2.5),
        ("culture",     2.5),
        ("heritage",    2.0),
        ("wright",      2.0),   # Frank Lloyd Wright
        ("sculpture",   3.0),
        ("mural",       2.5),
        ("craft fair",  2.5),   # specifically craft fair, not "craft beer/putt"
        ("pottery",     3.0),
        ("fiesta",      2.0),
        ("filipina",    2.0),
        ("juneteenth",  2.5),   # cultural celebration
    ]),

    ("Food & Drink", [
        ("food",        1.5),
        ("restaurant",  2.5),
        ("brewery",     3.0),
        ("brewer",      2.5),
        ("winery",      3.0),
        ("vineyard",    3.0),
        ("wine",        2.5),
        ("beer",        2.0),
        ("cocktail",    2.5),
        ("mimosa",      2.5),
        ("brunch",      2.5),
        ("tasting",     2.0),
        ("market",      1.5),   # farmers market
        ("farmer",      2.5),
        ("foodie",      2.5),
        ("chef",        2.0),
        ("bake",        2.0),
        ("cookie",      2.0),   # cookie decorating
        ("toast",       2.0),   # Toastique
        ("café",        2.0),
        ("cafe",        2.0),
        ("sweat & sip", 3.0),
        ("sweat social",3.0),
    ]),

    ("Sports & Fitness", [
        ("workout",     3.0),
        ("fitness",     3.0),
        ("yoga",        3.0),
        ("pilates",     3.0),
        ("boot camp",   3.0),
        ("bootcamp",    3.0),
        ("run ",        2.0),   # 5K run (space to reduce false matches)
        ("5k",          3.0),
        ("walk",        1.5),
        ("swim",        2.5),
        ("swimming",    2.5),
        ("long course", 3.5),   # competitive swim lanes
        ("swim meet",   3.5),
        ("aquatics",    3.0),
        ("pickleball",  3.0),
        ("tennis",      2.5),
        ("golf",        2.5),
        ("soccer",      2.5),
        ("football",    2.5),
        ("basketball",  2.5),
        ("volleyball",  2.5),
        ("baseball",    2.5),
        ("athletic",    2.0),
        ("sport",       2.0),
        ("gym",         2.0),
        ("f45",         3.0),
        ("werq",        3.0),   # WERQ fitness
        ("blush boot",  3.0),
        ("aquatic",     2.5),
        ("bingo",       1.0),   # also in Community; keep low
        ("turf",        1.5),
    ]),

    ("Outdoors & Nature", [
        ("park",        1.5),
        ("trail",       2.5),
        ("hike",        2.5),
        ("hiking",      2.5),
        ("fishing",     3.0),
        ("garden",      2.5),
        ("nature",      2.5),
        ("wildlife",    2.5),
        ("outdoor",     2.0),
        ("campfire",    2.5),
        ("camping",     2.5),
        ("scavenger",   2.0),
        ("bird",        2.5),
        ("kayak",       3.0),
        ("canoe",       3.0),
        ("lanesfield",  2.5),
        ("heritage park",2.5),
        ("kill creek",  2.5),
        ("mission park",2.0),
    ]),

    ("Community & Festivals", [
        ("festival",    3.0),
        ("fair",        2.5),
        ("celebration", 2.5),
        ("celebrate",   2.0),
        ("community",   2.0),
        ("fundraiser",  3.0),
        ("benefit",     2.5),
        ("charity",     2.5),
        ("nonprofit",   2.5),
        ("volunteer",   2.5),
        ("grand opening",3.0),
        ("ribbon cutting",3.0),
        ("parade",      3.0),
        ("kickoff",     2.5),
        ("water festival",3.0),
        ("watch party", 3.0),
        ("operation code",2.5),
        ("veterans",    2.0),
        ("bingo",       2.5),   # bingo fundraisers are community events
        ("giving back", 2.5),
        ("raising funds",2.5),
        ("putt",        2.0),   # craft putt, mini putt
    ]),

    ("Workshops & Classes", [
        ("workshop",    3.0),
        ("class",       2.5),
        ("lesson",      2.5),
        ("learn",       2.0),
        ("seminar",     3.0),
        ("lecture",     2.5),
        ("decorating",  2.5),
        ("cooking",     2.5),
        ("paint",       2.0),   # paint & sip, etc.
        ("sip and paint",3.0),
        ("immersive",   2.5),
        ("elevation",   2.0),   # leadership immersive
        ("leadership",  2.0),
        ("coding",      2.5),
        ("tech",        1.5),
    ]),
]

# Minimum total score required to claim a category
THRESHOLD = 1.5


def _score_text(text: str, keywords: list[tuple[str, float]]) -> float:
    score = 0.0
    for kw, weight in keywords:
        if kw in text:
            score += weight
    return score


def categorize(event: Event) -> str:
    """
    Return the best-matching category name for the event.
    Inspects title + description + tags (all lowercased).
    """
    text = " ".join([
        event.title,
        event.description,
        " ".join(event.tags),
    ]).lower()
    # Normalize: collapse whitespace, remove punctuation except spaces
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    best_cat   = "Other"
    best_score = 0.0

    for cat_name, keywords in CATEGORIES:
        score = _score_text(text, keywords)
        if score > best_score and score >= THRESHOLD:
            best_score = score
            best_cat   = cat_name

    return best_cat


def categorize_all(events: list[Event]) -> list[Event]:
    """Assign .category to every event in-place. Returns the same list."""
    for event in events:
        event.category = categorize(event)
    return events
