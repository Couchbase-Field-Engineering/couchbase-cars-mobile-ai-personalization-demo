"""Reference catalog for the demo: rental locations, road-trip plans, car
classes, extras, protection plans, bundles and services.

This is the single source of truth shared by the mock Redshift unload
generator (redshift/generate_mock_unload.py imports it), the backend's
personalization engine and the MCP tools. Prices and names are illustrative
demo values, not live Couchbase Cars pricing.
"""
from __future__ import annotations

import hashlib

# --------------------------------------------------------------------------
# Locations. The 17 airport locations in the demo "fleet". `lots` are the
# garage rows a reserved vehicle is assigned to (what the stateroom
# neighborhoods were in the cruise sibling of this demo).
# --------------------------------------------------------------------------
_LOTS = ["Preferred Row", "Garage P1", "Garage P2", "Garage P3", "Premium Row", "EV Row", "SUV Row"]
LOCATIONS = {
    "LAX": {"name": "Los Angeles Airport", "class": "Airport", "hub": "LAX", "city": "Los Angeles, CA", "lots": _LOTS},
    "SFO": {"name": "San Francisco Airport", "class": "Airport", "hub": "SFO", "city": "San Francisco, CA", "lots": _LOTS},
    "JFK": {"name": "New York JFK Airport", "class": "Airport", "hub": "JFK", "city": "New York, NY", "lots": _LOTS},
    "MCO": {"name": "Orlando Airport", "class": "Airport", "hub": "MCO", "city": "Orlando, FL", "lots": _LOTS},
    "DFW": {"name": "Dallas/Fort Worth Airport", "class": "Airport", "hub": "DFW", "city": "Dallas, TX", "lots": _LOTS},
    "ORD": {"name": "Chicago O'Hare Airport", "class": "Airport", "hub": "ORD", "city": "Chicago, IL", "lots": _LOTS},
    "ATL": {"name": "Atlanta Airport", "class": "Airport", "hub": "ATL", "city": "Atlanta, GA", "lots": _LOTS},
    "DEN": {"name": "Denver Airport", "class": "Airport", "hub": "DEN", "city": "Denver, CO", "lots": _LOTS},
    "MIA": {"name": "Miami Airport", "class": "Airport", "hub": "MIA", "city": "Miami, FL", "lots": _LOTS},
    "SEA": {"name": "Seattle-Tacoma Airport", "class": "Airport", "hub": "SEA", "city": "Seattle, WA", "lots": _LOTS},
    "BOS": {"name": "Boston Logan Airport", "class": "Airport", "hub": "BOS", "city": "Boston, MA", "lots": _LOTS},
    "LAS": {"name": "Las Vegas Harry Reid Airport", "class": "Airport", "hub": "LAS", "city": "Las Vegas, NV", "lots": _LOTS},
    "PHX": {"name": "Phoenix Sky Harbor Airport", "class": "Airport", "hub": "PHX", "city": "Phoenix, AZ", "lots": _LOTS},
    "IAH": {"name": "Houston Bush Airport", "class": "Airport", "hub": "IAH", "city": "Houston, TX", "lots": _LOTS},
    "EWR": {"name": "Newark Liberty Airport", "class": "Airport", "hub": "EWR", "city": "Newark, NJ", "lots": _LOTS},
    "SAN": {"name": "San Diego Airport", "class": "Airport", "hub": "SAN", "city": "San Diego, CA", "lots": _LOTS},
    "FLL": {"name": "Fort Lauderdale Airport", "class": "Airport", "hub": "FLL", "city": "Fort Lauderdale, FL", "lots": _LOTS},
}
FLEET_SIZE = len(LOCATIONS)  # the 17 airport locations in the demo

# Stops: where a road-trip plan goes. Location codes are stops too (pickup
# and return). "DRV" is a driving day between destinations.
STOPS = {
    **{code: f"Couchbase Cars {loc['name']}, {loc['city'].split(',')[1].strip()}" for code, loc in LOCATIONS.items()},
    "DRV": "On the road",
    # California
    "MAL": "Malibu & the Pacific Coast Highway, California",
    "SBA": "Santa Barbara, California",
    "MRY": "Monterey & Carmel-by-the-Sea, California",
    "SDO": "San Diego & La Jolla, California",
    "PSP": "Palm Springs, California",
    "NAP": "Napa Valley, California",
    "LTA": "Lake Tahoe, California",
    "YOS": "Yosemite National Park, California",
    "DVY": "Death Valley National Park, California",
    "SVL": "Silicon Valley (Palo Alto & Menlo Park), California",
    "SAU": "Sausalito & the Marin Headlands, California",
    # Florida
    "THP": "Orlando theme parks, Florida",
    "KSC": "Kennedy Space Center, Florida",
    "DAY": "Daytona Beach, Florida",
    "STA": "St. Augustine, Florida",
    "KEY": "Key West & the Overseas Highway, Florida",
    "EVG": "Everglades National Park, Florida",
    "NPL": "Naples & Marco Island, Florida",
    # Texas
    "FTW": "Fort Worth Stockyards, Texas",
    "AUS": "Austin, Texas",
    "HIL": "Texas Hill Country (Fredericksburg), Texas",
    "SAT": "San Antonio River Walk, Texas",
    "GLV": "Galveston Island, Texas",
    # Mountain West & Southwest
    "RMN": "Rocky Mountain National Park, Colorado",
    "VAI": "Vail, Colorado",
    "ASP": "Aspen, Colorado",
    "COS": "Colorado Springs & Garden of the Gods, Colorado",
    "HOO": "Hoover Dam, Nevada",
    "GCN": "Grand Canyon National Park, Arizona",
    "ZIO": "Zion National Park, Utah",
    "SED": "Sedona, Arizona",
    # Northeast
    "HUD": "Hudson Valley, New York",
    "HMP": "The Hamptons, New York",
    "CPC": "Cape Cod, Massachusetts",
    "NPT": "Newport, Rhode Island",
    "WMT": "White Mountains, New Hampshire",
    "ACA": "Acadia National Park, Maine",
    # Southeast
    "ASH": "Asheville, North Carolina",
    "BRM": "Blue Ridge Parkway, North Carolina",
    "CHS": "Charleston, South Carolina",
    "SAV": "Savannah, Georgia",
    # Pacific Northwest & Midwest
    "OLY": "Olympic National Park, Washington",
    "SJI": "San Juan Islands, Washington",
    "MTR": "Mount Rainier National Park, Washington",
    "PDX": "Portland, Oregon",
    "LKG": "Lake Geneva, Wisconsin",
    "DOR": "Door County, Wisconsin",
    "SPI": "Springfield & Route 66, Illinois",
    "STL": "St. Louis Gateway Arch, Missouri",
}
# Interest tags per stop - what the trip itself says about the renter.
STOP_TAGS = {
    "MAL": ["beach", "scenic drives", "photography"], "SBA": ["food & wine", "beach", "relaxation"],
    "MRY": ["scenic drives", "ocean", "golf", "photography"], "SDO": ["beach", "family", "theme parks"],
    "PSP": ["relaxation", "golf", "luxury"], "NAP": ["food & wine", "luxury", "relaxation"],
    "LTA": ["skiing", "mountains", "hiking", "camping"], "YOS": ["national parks", "hiking", "camping", "photography"],
    "DVY": ["national parks", "scenic drives", "photography"],
    "SVL": ["business travel", "ev", "cycling"], "SAU": ["scenic drives", "cycling", "photography", "food & wine"],
    "THP": ["theme parks", "family", "kids"], "KSC": ["family", "history", "kids"], "DAY": ["beach", "family", "thrill"],
    "STA": ["history", "culture", "beach"], "KEY": ["beach", "scenic drives", "food & wine", "snorkeling"],
    "EVG": ["national parks", "nature", "photography"], "NPL": ["beach", "golf", "luxury", "relaxation"],
    "FTW": ["culture", "history", "family"], "AUS": ["music", "food & wine", "culture"], "HIL": ["food & wine", "scenic drives"],
    "SAT": ["history", "culture", "family"], "GLV": ["beach", "family", "relaxation"],
    "RMN": ["national parks", "hiking", "camping", "photography"], "VAI": ["skiing", "mountains", "luxury"],
    "ASP": ["skiing", "mountains", "luxury", "food & wine"], "COS": ["hiking", "family", "photography"],
    "HOO": ["history", "photography"], "GCN": ["national parks", "hiking", "photography", "family"],
    "ZIO": ["national parks", "hiking", "camping", "thrill"], "SED": ["hiking", "photography", "relaxation"],
    "HUD": ["food & wine", "history", "scenic drives"], "HMP": ["beach", "luxury", "food & wine"],
    "CPC": ["beach", "family", "cycling"], "NPT": ["history", "ocean", "luxury"], "WMT": ["mountains", "hiking", "scenic drives"],
    "ACA": ["national parks", "hiking", "cycling", "photography"],
    "ASH": ["mountains", "food & wine", "culture"], "BRM": ["scenic drives", "mountains", "photography"],
    "CHS": ["history", "food & wine", "culture"], "SAV": ["history", "culture", "photography"],
    "OLY": ["national parks", "hiking", "camping"], "SJI": ["ocean", "nature", "cycling"], "MTR": ["national parks", "hiking", "mountains"],
    "PDX": ["food & wine", "culture", "cycling"], "LKG": ["relaxation", "family", "golf"], "DOR": ["scenic drives", "cycling", "relaxation"],
    "SPI": ["history", "scenic drives"], "STL": ["history", "family", "photography"],
}

# trip_code -> definition. `stops` lists one entry per day of the rental,
# pickup day first ("PU") and return day last ("RT"); "DRV" is a driving day.
TRIPS = {
    "7SOCAL": {"name": "7 Day Pacific Coast Highway Road Trip", "days": 7,
               "stops": ["PU", "MAL", "SBA", "DRV", "MRY", "DRV", "SDO", "RT"]},
    "3SOCAL": {"name": "3 Day Southern California Getaway", "days": 3,
               "stops": ["PU", "SDO", "PSP", "RT"]},
    "7NORCAL": {"name": "7 Day Wine Country, Tahoe & Yosemite", "days": 7,
                "stops": ["PU", "NAP", "DRV", "LTA", "YOS", "DRV", "MRY", "RT"]},
    "3BAYAREA": {"name": "3 Day Bay Area Business Trip", "days": 3,
                 "stops": ["PU", "SVL", "SAU", "RT"]},
    "4FLKEYS": {"name": "4 Day Florida Keys Escape", "days": 4,
                "stops": ["PU", "KEY", "KEY", "EVG", "RT"]},
    "3ORLANDO": {"name": "3 Day Orlando Family Getaway", "days": 3,
                 "stops": ["PU", "THP", "KSC", "RT"]},
    "7FLCOAST": {"name": "7 Day Florida Coast to Coast", "days": 7,
                 "stops": ["PU", "STA", "DAY", "KSC", "DRV", "NPL", "EVG", "RT"]},
    "7TXHILL": {"name": "7 Day Texas Hill Country", "days": 7,
                "stops": ["PU", "FTW", "DRV", "AUS", "HIL", "SAT", "DRV", "RT"]},
    "4TXGULF": {"name": "4 Day Texas Gulf Coast", "days": 4,
                "stops": ["PU", "GLV", "GLV", "DRV", "RT"]},
    "7ROCKIES": {"name": "7 Day Colorado Rockies", "days": 7,
                 "stops": ["PU", "RMN", "DRV", "VAI", "ASP", "DRV", "COS", "RT"]},
    "7SWPARKS": {"name": "7 Day Southwest National Parks", "days": 7,
                 "stops": ["PU", "HOO", "GCN", "DRV", "ZIO", "DVY", "DRV", "RT"]},
    "4DESERT": {"name": "4 Day Sedona & Grand Canyon", "days": 4,
                "stops": ["PU", "SED", "GCN", "DRV", "RT"]},
    "7NEWENG": {"name": "7 Day New England Coast", "days": 7,
                "stops": ["PU", "CPC", "NPT", "DRV", "WMT", "ACA", "DRV", "RT"]},
    "4NYC": {"name": "4 Day Hudson Valley & the Hamptons", "days": 4,
             "stops": ["PU", "HUD", "DRV", "HMP", "RT"]},
    "7SOUTH": {"name": "7 Day Southern Charm", "days": 7,
               "stops": ["PU", "ASH", "BRM", "DRV", "CHS", "SAV", "DRV", "RT"]},
    "7PNW": {"name": "7 Day Pacific Northwest", "days": 7,
             "stops": ["PU", "OLY", "DRV", "SJI", "MTR", "DRV", "PDX", "RT"]},
    "7RT66": {"name": "7 Day Great Lakes & Route 66", "days": 7,
              "stops": ["PU", "LKG", "DOR", "DRV", "SPI", "STL", "DRV", "RT"]},
    "10WEST": {"name": "10 Day Great American West", "days": 10,
               "stops": ["PU", "DRV", "GCN", "ZIO", "DRV", "LTA", "YOS", "DRV", "MRY", "DRV", "RT"]},
}

# location -> trip plans its renters take (first is the "anchor" plan)
LOCATION_TRIPS = {
    "LAX": ["7SOCAL", "3SOCAL"],
    "SFO": ["7NORCAL", "3BAYAREA", "10WEST"],
    "JFK": ["4NYC", "7NEWENG"],
    "MCO": ["3ORLANDO", "7FLCOAST"],
    "DFW": ["7TXHILL", "4TXGULF"],
    "ORD": ["7RT66"],
    "ATL": ["7SOUTH"],
    "DEN": ["7ROCKIES"],
    "MIA": ["4FLKEYS", "7FLCOAST"],
    "SEA": ["7PNW"],
    "BOS": ["7NEWENG"],
    "LAS": ["7SWPARKS", "4DESERT"],
    "PHX": ["4DESERT", "7SWPARKS"],
    "IAH": ["4TXGULF", "7TXHILL"],
    "EWR": ["4NYC", "7NEWENG"],
    "SAN": ["3SOCAL", "7SOCAL"],
    "FLL": ["4FLKEYS", "7FLCOAST"],
}

# --------------------------------------------------------------------------
# Car classes. Rank is the upgrade ladder; prices are per day. `levels` is
# the range of garage levels a car of that class is parked on.
# --------------------------------------------------------------------------
CAR_CLASSES = [
    {"code": "ECAR", "name": "Economy", "rank": 1, "base_pd": 42, "levels": (1, 2), "example": "Mitsubishi Mirage or similar"},
    {"code": "CCAR", "name": "Compact", "rank": 2, "base_pd": 48, "levels": (1, 2), "example": "Kia Soul or similar"},
    {"code": "ICAR", "name": "Intermediate", "rank": 3, "base_pd": 55, "levels": (1, 3), "example": "Toyota Corolla or similar"},
    {"code": "FCAR", "name": "Full-size", "rank": 4, "base_pd": 64, "levels": (1, 3), "example": "Nissan Altima or similar"},
    {"code": "SFAR", "name": "Standard SUV", "rank": 5, "base_pd": 79, "levels": (2, 3), "example": "Toyota RAV4 or similar"},
    {"code": "PCAR", "name": "Premium", "rank": 6, "base_pd": 98, "levels": (1, 1), "example": "BMW 3 Series or similar"},
    {"code": "LCAR", "name": "Luxury", "rank": 7, "base_pd": 145, "levels": (1, 1), "example": "BMW 5 Series or Cadillac CT5"},
]
CLASS_BY_CODE = {c["code"]: c for c in CAR_CLASSES}
CLASS_PERKS = {
    "ICAR": ["Seats 5", "Apple CarPlay / Android Auto"],
    "FCAR": ["Seats 5 with a full-size trunk", "Apple CarPlay / Android Auto", "Adaptive cruise control"],
    "SFAR": ["All-wheel drive", "Seats 5 plus luggage for four", "Roof rails for racks and cargo boxes"],
    "PCAR": ["BMW 3 Series or similar", "Leather and heated seats", "Premium sound", "Preferred Row pickup"],
    "LCAR": ["BMW 5 Series or Cadillac CT5", "Massage seats and head-up display", "Complimentary e-Toll", "Premium Row pickup with a dedicated agent"],
}

# Minimum Couchbase Cars Upgrade standby offer per day for a step of N classes.
UPGRADE_OFFER_MIN_PD = {1: 6, 2: 12, 3: 22, 4: 38, 5: 60}


def upgrade_price_pd(from_code: str, to_code: str) -> int:
    """Instant-upgrade price (per day) between two classes."""
    a, b = CLASS_BY_CODE[from_code], CLASS_BY_CODE[to_code]
    delta = max(0, b["base_pd"] - a["base_pd"])
    # Last-minute upgrade discount, but always comfortably above the standby
    # offer floor - otherwise a standby offer would never make sense.
    price = max(delta * 0.82, upgrade_offer_min(from_code, to_code) * 1.6)
    return int(round(price / 5.0) * 5) or 5


def upgrade_offer_min(from_code: str, to_code: str) -> int:
    steps = CLASS_BY_CODE[to_code]["rank"] - CLASS_BY_CODE[from_code]["rank"]
    return UPGRADE_OFFER_MIN_PD.get(steps, 0)


def _h(*parts: str) -> int:
    return int(hashlib.sha1("|".join(parts).encode()).hexdigest()[:8], 16)


def initial_inventory(rental_id: str) -> dict:
    """Deterministic unreserved cars per class for a pickup day at a location -
    what fleet planning would release to upgrades a week or two out."""
    out = {}
    for c in CAR_CLASSES:
        if c["code"] == "ECAR":
            continue
        cap = {"CCAR": 14, "ICAR": 22, "FCAR": 12, "SFAR": 9, "PCAR": 4, "LCAR": 2}[c["code"]]
        out[c["code"]] = _h(rental_id, c["code"]) % (cap + 1)
    # Always leave a little room in the hero classes so demos never dead-end.
    out["ICAR"] = max(out["ICAR"], 3)
    out["FCAR"] = max(out["FCAR"], 2)
    out["SFAR"] = max(out["SFAR"], 2)
    out["PCAR"] = max(out["PCAR"], 1)
    out["LCAR"] = max(out["LCAR"], 1)
    return out


# --------------------------------------------------------------------------
# Extras: equipment and add-ons (tags drive interest matching). `locations`
# limits region-specific gear; `stops` lists the trip stops an extra is made
# for (a parks pass when the plan visits a national park).
# --------------------------------------------------------------------------
EXTRAS = [
    {"id": "SEAT-INFANT", "name": "Infant car seat", "price": 15, "per": "day", "locations": "*",
     "tags": ["family", "kids", "safety"], "activity": "low"},
    {"id": "SEAT-TODDLER", "name": "Toddler car seat", "price": 15, "per": "day", "locations": "*",
     "tags": ["family", "kids", "safety"], "activity": "low"},
    {"id": "SEAT-BOOSTER", "name": "Booster seat", "price": 13, "per": "day", "locations": "*",
     "tags": ["family", "kids", "safety"], "activity": "low"},
    {"id": "GPS", "name": "Couchbase Cars Navigation (GPS)", "price": 16, "per": "day", "locations": "*",
     "tags": ["scenic drives", "national parks", "mountains"], "activity": "low"},
    {"id": "ADDL-DRIVER", "name": "Additional driver", "price": 13, "per": "day", "locations": "*",
     "tags": ["family", "couples", "scenic drives", "business travel"], "activity": "low"},
    {"id": "SAT-RADIO", "name": "SiriusXM satellite radio", "price": 8, "per": "day", "locations": "*",
     "tags": ["scenic drives", "music", "family"], "activity": "low"},
    {"id": "ROOF-BOX", "name": "Roof cargo box", "price": 18, "per": "day", "locations": "*",
     "tags": ["family", "camping", "skiing", "scenic drives"], "activity": "medium"},
    {"id": "BIKE-RACK", "name": "Bike rack (2 bikes)", "price": 12, "per": "day", "locations": "*",
     "tags": ["cycling", "national parks", "hiking"], "activity": "high"},
    {"id": "SKI-RACK", "name": "Ski & snowboard rack", "price": 12, "per": "day", "locations": ["DEN", "SEA", "BOS", "SFO", "LAS"],
     "tags": ["skiing", "mountains", "thrill"], "activity": "high"},
    {"id": "SNOW-READY", "name": "Snow chains & all-weather tires", "price": 15, "per": "day", "locations": ["DEN", "SEA", "BOS", "ORD", "SFO"],
     "tags": ["skiing", "mountains", "safety"], "activity": "medium"},
    {"id": "PARKS-PASS", "name": "America the Beautiful national parks pass", "price": 80, "per": "rental", "locations": "*",
     "stops": ["YOS", "DVY", "EVG", "RMN", "GCN", "ZIO", "ACA", "OLY", "MTR"],
     "tags": ["national parks", "hiking", "camping", "nature"], "activity": "high"},
    {"id": "CAMP-KIT", "name": "Camping kit (tent, chairs, lantern)", "price": 20, "per": "day", "locations": ["DEN", "SEA", "LAS", "PHX", "SFO", "LAX"],
     "tags": ["camping", "national parks", "hiking", "nature"], "activity": "high"},
    {"id": "BEACH-KIT", "name": "Beach kit (chairs, umbrella, cooler)", "price": 15, "per": "day", "locations": ["MIA", "FLL", "MCO", "LAX", "SAN", "IAH"],
     "tags": ["beach", "family", "relaxation"], "activity": "low"},
    {"id": "GOLF-CARRIER", "name": "Golf club carrier", "price": 10, "per": "day", "locations": ["PHX", "MCO", "FLL", "MIA", "LAS", "SAN", "LAX"],
     "tags": ["golf", "relaxation", "luxury"], "activity": "medium"},
    {"id": "COOLER", "name": "Road-trip cooler & snack kit", "price": 10, "per": "day", "locations": "*",
     "tags": ["scenic drives", "family", "camping", "food & wine"], "activity": "low"},
    {"id": "EV-CHARGE", "name": "Unlimited EV charging credit", "price": 25, "per": "day", "locations": ["LAX", "SFO", "SAN", "SEA", "DEN", "BOS"],
     "tags": ["ev", "sustainability", "business travel"], "activity": "low"},
    {"id": "DASH-CAM", "name": "Dash cam", "price": 6, "per": "day", "locations": "*",
     "tags": ["safety", "business travel", "scenic drives"], "activity": "low"},
    {"id": "PET-KIT", "name": "Pet travel kit (seat cover, harness, bowls)", "price": 12, "per": "day", "locations": "*",
     "tags": ["pets", "family", "camping"], "activity": "low"},
    {"id": "HAND-CONTROLS", "name": "Hand controls & spinner knob (complimentary)", "price": 0, "per": "rental", "locations": "*",
     "tags": ["accessibility"], "activity": "low"},
    {"id": "SKI-BOX", "name": "Heated ski boot bag & boot dryer", "price": 9, "per": "day", "locations": ["DEN", "SFO", "SEA"],
     "tags": ["skiing", "mountains"], "activity": "medium"},
]
EXTRA_BY_ID = {e["id"]: e for e in EXTRAS}

INTERESTS = sorted({t for e in EXTRAS for t in e["tags"]} | {t for ts in STOP_TAGS.values() for t in ts}
                   | {"theme parks", "luxury", "wellness", "photography", "business travel"})

# --------------------------------------------------------------------------
# Protection plans, bundles, services
# --------------------------------------------------------------------------
PROTECTION = [
    {"id": "LDW", "name": "Loss Damage Waiver (LDW)", "covers": "Damage to or theft of the Couchbase Cars car", "price_pd": 32, "locations": "*",
     "tags": ["essential", "family", "classic"]},
    {"id": "PAI", "name": "Personal Accident Insurance (PAI)", "covers": "Medical costs for the driver and passengers", "price_pd": 7, "locations": "*",
     "tags": ["family", "safety", "classic"]},
    {"id": "PEC", "name": "Personal Effects Coverage (PEC)", "covers": "Your belongings in the car", "price_pd": 4, "locations": "*",
     "tags": ["business travel", "luggage"]},
    {"id": "ALI", "name": "Additional Liability Insurance (ALI)", "covers": "Third-party liability up to $1 million", "price_pd": 16, "locations": "*",
     "tags": ["peace of mind", "business travel", "classic"]},
    {"id": "RSN", "name": "Roadside SafetyNet", "covers": "Lockouts, flat tires, jump starts and fuel delivery", "price_pd": 8, "locations": "*",
     "tags": ["scenic drives", "national parks", "mountains", "family"]},
    {"id": "TWP", "name": "Tire & Windshield Protection", "covers": "Tire, wheel and glass damage on rough roads", "price_pd": 9,
     "locations": ["LAS", "PHX", "DEN", "LAX", "SFO", "SEA", "SAN"], "tags": ["scenic drives", "mountains", "national parks"]},
    {"id": "EVP", "name": "EV Charging Cable & Battery Protection", "covers": "Charging cables, adapters and battery incidents", "price_pd": 6,
     "locations": ["LAX", "SFO", "SAN", "SEA", "DEN", "BOS"], "tags": ["ev", "sustainability"]},
    {"id": "ZERO", "name": "Zero Deductible Premium Protection", "covers": "LDW plus ALI with no deductible and a courtesy replacement car within 2 hours",
     "price_pd": 45, "locations": ["LAX", "SFO", "JFK", "MIA", "LAS", "BOS", "EWR"],
     "tags": ["luxury", "celebration", "peace of mind"]},
]
PROTECTION_BY_ID = {d["id"]: d for d in PROTECTION}
# Coverage terms a plan can be added for.
PROTECTION_TERMS = ["whole rental", "pickup day only", "first 3 days"]

BUNDLES = [
    {"code": "PEACE", "name": "Couchbase Cars Peace of Mind", "price_per_day": 45, "per": "car/day",
     "blurb": "Loss Damage Waiver, Personal Accident & Effects and Roadside SafetyNet in one bundle for every listed driver.",
     "propensity": "protection_propensity"},
    {"code": "ETOLL", "name": "e-Toll Unlimited", "price_per_day": 11, "per": "car/day",
     "blurb": "Drive every toll road and express lane without stopping - unlimited tolls for the whole rental.",
     "propensity": "toll_propensity"},
    {"code": "WIFI", "name": "Couchbase Cars Wi-Fi hotspot", "price_per_day": 10, "per": "device/day",
     "blurb": "In-car 4G LTE hotspot for up to five devices - stream, navigate and work from the back seat.",
     "propensity": "wifi_propensity"},
    {"code": "TOTAL", "name": "Couchbase Cars Total Protection", "price_per_day": 69, "per": "car/day",
     "blurb": "Everything in Peace of Mind plus Additional Liability, Tire & Windshield, e-Toll Unlimited and a prepaid tank of fuel.",
     "propensity": "total_propensity"},
    {"code": "FUEL", "name": "Prepaid Fuel", "price_per_day": 55, "per": "tank (one-time)", "one_time": True,
     "blurb": "A full tank at our discounted pump price - return the car at any level, no refuelling stop before the airport.",
     "propensity": "fuel_propensity"},
]
BUNDLE_BY_CODE = {p["code"]: p for p in BUNDLES}

SERVICES = [
    {"id": "SVC-DELIVERY", "name": "Deliver my car to my hotel", "price": 49, "minutes": 0, "tags": ["convenience", "luxury", "business travel"],
     "when": "pickup"},
    {"id": "SVC-COLLECT", "name": "Collect my car from my hotel", "price": 49, "minutes": 0, "tags": ["convenience", "luxury", "business travel"],
     "when": "return"},
    {"id": "SVC-SWAP", "name": "Mid-trip vehicle swap & wash", "price": 39, "minutes": 45, "tags": ["convenience", "family", "scenic drives"],
     "when": "any"},
    {"id": "SVC-REFUEL", "name": "Mobile refuel at my hotel", "price": 29, "minutes": 30, "tags": ["convenience", "business travel"],
     "when": "any"},
    {"id": "SVC-EVCHARGE", "name": "Mobile EV charging at my hotel", "price": 35, "minutes": 60, "tags": ["ev", "convenience", "sustainability"],
     "when": "any"},
    {"id": "SVC-LATE", "name": "Late return (4 extra hours)", "price": 29, "minutes": 240, "tags": ["flexibility", "business travel"],
     "when": "return"},
]
SERVICE_BY_ID = {s["id"]: s for s in SERVICES}

PICKUP_SLOTS = ["06:00", "08:00", "10:00", "12:00", "14:00", "16:00", "18:00", "20:00"]

# Couchbase Cars Preferred tiers. Thresholds are in loyalty points (the generator awards
# about 9 per completed rental): Preferred after the first rental, Preferred
# Plus from 3, President's Club from 5, Chairman's Club from 15.
LOYALTY_TIERS = ["Member", "Preferred", "Preferred Plus", "President’s Club", "Chairman’s Club"]
LOYALTY_THRESHOLDS = {"Member": 0, "Preferred": 1, "Preferred Plus": 27, "President’s Club": 45, "Chairman’s Club": 135}


def _at_location(item: dict, location_code: str) -> bool:
    locs = item.get("locations", "*")
    return locs == "*" or location_code in locs


def location_has_protection(location_code: str, plan_id: str) -> bool:
    return _at_location(PROTECTION_BY_ID[plan_id], location_code)


def location_has_extra(location_code: str, extra_id: str) -> bool:
    return _at_location(EXTRA_BY_ID[extra_id], location_code)


def a_or_an(name: str) -> str:
    """'a Premium', 'an Intermediate'."""
    return f"{'an' if name[:1].lower() in 'aeiou' else 'a'} {name}"


def trip_stop_codes(reservation: dict) -> set[str]:
    return {d["stop_code"] for d in reservation["stops"] if d["type"] == "stop"}


def extra_fits_trip(extra: dict, reservation: dict) -> bool:
    """Region-specific gear only where it is stocked; stop-specific extras
    (a parks pass) only when the plan goes there."""
    if not _at_location(extra, reservation["location_code"]):
        return False
    if extra.get("stops"):
        return bool(set(extra["stops"]) & trip_stop_codes(reservation))
    return True


def protection_availability(reservation: dict) -> dict:
    """Which protection plans this location offers, synced to the phone with
    the offers so the protection screen can grey out the rest, offline too."""
    return {d["id"]: _at_location(d, reservation["location_code"]) for d in PROTECTION}


def public_catalog() -> dict:
    """What the mobile app syncs as `catalog` documents."""
    return {
        "locations": LOCATIONS,
        "stops": STOPS,
        "stop_tags": STOP_TAGS,
        "trips": TRIPS,
        "car_classes": [
            {**{k: v for k, v in c.items() if k != "levels"}, "perks": CLASS_PERKS.get(c["code"], [])}
            for c in CAR_CLASSES
        ],
        "extras": EXTRAS,
        "protection": PROTECTION,
        "protection_terms": PROTECTION_TERMS,
        "bundles": BUNDLES,
        "services": SERVICES,
        "pickup_slots": PICKUP_SLOTS,
        "loyalty_tiers": LOYALTY_TIERS,
    }
