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
    KnuckleheadsScraper,
    GreenLadyLoungeScraper,
    SportingKCScraper,
    KCMonarchsScraper,
    MidlandKCScraper,
    TMobileCenterScraper,
    LeawoodCalendarScraper,
    OPKansasScraper,
    OPConventionCenterScraper,
    OPFarmersMarketScraper,
)
from .ticketmaster import TicketmasterScraper
from .hs_football import HighSchoolFootballScraper
from .kc_music_festival import KCMusicFestivalScraper
from .worlds_of_fun import WorldsOfFunScraper
from .bourgmont import BourgmontWineryScraper
from .kc_chiefs import KCChiefsScraper
from .kc_royals import KCRoyalsScraper
from .kc_current import KCCurrentScraperNew

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
    KnuckleheadsScraper,
    GreenLadyLoungeScraper,
    SportingKCScraper,
    KCCurrentScraperNew,
    KCMonarchsScraper,
    MidlandKCScraper,
    TMobileCenterScraper,
    LeawoodCalendarScraper,
    OPKansasScraper,
    OPConventionCenterScraper,
    OPFarmersMarketScraper,
    TicketmasterScraper,
    HighSchoolFootballScraper,
    KCMusicFestivalScraper,
    WorldsOfFunScraper,
    BourgmontWineryScraper,
    KCChiefsScraper,
    KCRoyalsScraper,
]
