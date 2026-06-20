from .shawnee_mission_post import ShawneeMissionPostScraper
from .johnson_county_post import JohnsonCountyPostScraper
from .visit_overland_park import VisitOverlandParkScraper
from .jcprd import JCPRDScraper
from .city_calendars import CityCalendarScraper
from .eventbrite import EventbriteScraper
from .venues import (
    BluhawkScraper,
    PrairiefireScraper,
    ChickenNPickleScraper,
    KCRunningCompanyScraper,
    BlueValleyRecScraper,
)

ALL_SCRAPERS = [
    ShawneeMissionPostScraper,
    JohnsonCountyPostScraper,
    VisitOverlandParkScraper,
    JCPRDScraper,
    CityCalendarScraper,
    EventbriteScraper,
    BluhawkScraper,
    PrairiefireScraper,
    ChickenNPickleScraper,
    KCRunningCompanyScraper,
    BlueValleyRecScraper,
]
