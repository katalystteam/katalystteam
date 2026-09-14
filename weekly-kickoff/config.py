"""Configuration for the Weekly Kickoff market intelligence pipeline."""

from datetime import date

REPORT_TITLE = "Central Iowa Multifamily Market Intelligence"
BRAND = "KataLYST COMMERCIAL"
SUBTITLE = "WEEKLY MARKET REPORT"
CONTACT_LINE = (
    "Jared Husmann, CCIM | KataLYST Team by KW Commercial | "
    "(515) 639-0145 | JHusmann@KataLYSTteam.com | KataLYSTteam.com"
)
FOOTER_DISCLAIMER = (
    "All data sourced from the KataLYST Current Listings tracker and public listing platforms. "
    "Figures reflect asking and recorded prices, believed accurate but not guaranteed. "
    "Cap rates may reflect asking or pro-forma projections. This report is for informational "
    "purposes only and does not constitute investment advice. "
    "KataLYST Team by KW Commercial · 4001 Westown Pkwy, West Des Moines, IA 50266"
)

# Iowa submarket classification
DSM_CITIES = {
    "des moines", "west des moines", "ames", "mitchellville", "ankeny",
    "urbandale", "clive", "altoona", "johnston", "waukee",
}
RURAL_CITIES = {
    "ft. dodge", "fort dodge", "maquoketa", "dubuque", "west burlington",
    "burlington", "cedar falls", "marshalltown", "mason city", "ottumwa",
}
WATERLOO_CITIES = {"waterloo", "cedar rapids"}
SIOUX_CITY_CITIES = {"sioux city", "sioux center"}
IOWA_CITY_CITIES = {"iowa city", "coralville", "north liberty"}
QUAD_CITIES_CITIES = {"davenport", "bettendorf", "moline", "rock island", "east moline"}

SCRAPE_SITES = {
    "Crexi": "https://www.crexi.com/properties?propertyTypes=Multifamily&states=IA",
    "LoopNet": "https://www.loopnet.com/search/apartment-buildings/iowa/for-sale/",
    "CBRE": "https://www.cbre.com/properties?aspects=isLetting,isSale&locations=Iowa%2C%20USA&propertyTypes=Multifamily",
    "DealFlow": "https://www.dealflow.com/properties?state=IA&propertyType=Multifamily",
    "JLL": "https://property.jll.com/search?propertyType=Multifamily&country=US&state=IA",
    "MarcusMillichap": "https://www.marcusmillichap.com/properties?propertyType=Multifamily&state=IA",
}

LOOKBACK_DAYS = 7
OUTPUT_DIR = "output"

# Brand colors for PDF
COLOR_NAVY = "#1B2A4A"
COLOR_GOLD = "#C9A227"
COLOR_TEAL = "#2A9D8F"
COLOR_LIGHT = "#F4F6F8"
COLOR_GREEN = "#2D6A4F"
COLOR_GRAY = "#6C757D"
COLOR_WHITE = "#FFFFFF"
COLOR_DARK_TEXT = "#1A1A2E"
