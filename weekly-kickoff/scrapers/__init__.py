from scrapers.cbre import CBREScraper
from scrapers.crexi import CrexiScraper
from scrapers.dealflow import DealFlowScraper
from scrapers.jll import JLLScraper
from scrapers.katalyst_tracker import KatalystTrackerScraper
from scrapers.loopnet import LoopNetScraper
from scrapers.marcus_millichap import MarcusMillichapScraper

ALL_SCRAPERS = [
    KatalystTrackerScraper,
    CrexiScraper,
    LoopNetScraper,
    CBREScraper,
    DealFlowScraper,
    JLLScraper,
    MarcusMillichapScraper,
]
