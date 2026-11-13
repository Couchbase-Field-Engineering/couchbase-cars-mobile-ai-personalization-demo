#!/usr/bin/env python3
"""Generate a mock Amazon Redshift daily customer-profile UNLOAD for the demo.

Couchbase Cars' customer context lives in Amazon Redshift: the customer 360 (identity
resolved across the reservation system, the app and the web), the segment
memberships the nightly segmentation job writes, and the propensity scores
Redshift ML produces. A scheduled **UNLOAD** of the
`analytics.customer_profile_personalization` view to S3 lands every morning
as JSON Lines, one profile per line, in a date partition with a manifest
(redshift/unload/README.md). This script writes that layout:

    data/redshift-unload/dt=20261009/
        0000_part_00.json                # JSON Lines, one customer profile + upcoming reservation per line
        0001_part_00.json
        ...
        manifest                         # UNLOAD ... MANIFEST: the part files, with an `unload` block
                                         # (row count, view, Redshift ML model) - written last

Each line is one customer on one upcoming reservation, joined with their
Couchbase Cars Preferred status, preferences, rental history, ancillary-spend profile,
what they've already added to this rental, their resolved identity and
segment memberships, and the scores Redshift ML produced.

Fully deterministic for a given --seed and --export-date, and standard
library only (runs anywhere Python 3.9+ does). Default target is 100 MiB.

    python redshift/generate_mock_unload.py                 # today, 100 MiB
    python redshift/generate_mock_unload.py --export-date 2026-10-09 --target-mb 100
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
from app import catalog as C  # noqa: E402

SCHEMA_VERSION = "customer_profile_personalization_v3"   # the unloaded view's schema version
MODEL_VERSION = "redshift-ml-propensity-v2"             # Redshift ML propensity model (CREATE MODEL ... AUTO)
SOURCE_VIEW = "analytics.customer_profile_personalization"
WORKGROUP = "cbcars-analytics"

# Amazon Redshift segments (segments) a customer can belong to; membership is
# derived from the same scores, the way Redshift ML feeds segmentation.
AUDIENCES = {
    "seg-upgrade-high": "Upgrade propensity - high",
    "seg-celebration": "Celebrating on the road",
    "seg-convenience": "Convenience seekers",
    "seg-families": "Families with children",
    "seg-elite": "President’s Club & Chairman’s Club",
    "seg-first-rental": "First-time renters",
    "seg-protection": "Protection-plan buyers",
    "seg-bundle-ready": "Bundle ready (Peace of Mind / Total)",
}


def audiences_for(scores: dict, tier: str, rentals: int, has_kids: bool, celebration) -> list[dict]:
    ids = []
    if scores.get("upgrade_propensity", 0) >= 0.6:
        ids.append("seg-upgrade-high")
    if celebration:
        ids.append("seg-celebration")
    if scores.get("services_propensity", 0) >= 0.6:
        ids.append("seg-convenience")
    if has_kids:
        ids.append("seg-families")
    if tier in ("Chairman’s Club", "President’s Club"):
        ids.append("seg-elite")
    if rentals == 0:
        ids.append("seg-first-rental")
    if scores.get("protection_propensity", 0) >= 0.65:
        ids.append("seg-protection")
    if max(scores.get("fuel_propensity", 0), scores.get("total_propensity", 0)) >= 0.6:
        ids.append("seg-bundle-ready")
    return [{"id": a, "name": AUDIENCES[a], "status": "realized"} for a in ids]

FIRST = ["Olivia", "Liam", "Emma", "Noah", "Ava", "Elijah", "Sophia", "James", "Isabella", "Lucas", "Mia", "Mason",
         "Amelia", "Ethan", "Harper", "Logan", "Evelyn", "Aiden", "Abigail", "Jackson", "Emily", "Sebastian", "Ella",
         "Mateo", "Scarlett", "Daniel", "Grace", "Henry", "Chloe", "Owen", "Camila", "Wyatt", "Aria", "Carter", "Riley",
         "Jayden", "Nora", "Gabriel", "Lily", "Julian", "Zoey", "Leo", "Hannah", "David", "Layla", "Joseph", "Priya",
         "Arjun", "Mei", "Hiroshi", "Fatima", "Omar", "Sofia", "Diego", "Valentina", "Carlos", "Lucia", "Andre", "Aaliyah",
         "Marcus", "Keisha", "Tyrone", "Ngozi", "Kwame", "Siobhan", "Declan", "Ingrid", "Lars", "Anika", "Ravi"]
LAST = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
        "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee",
        "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker", "Young",
        "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green", "Adams", "Nelson", "Baker",
        "Hall", "Rivera", "Campbell", "Mitchell", "Carter", "Roberts", "Patel", "Shah", "Kim", "Chen", "Okafor",
        "O'Brien", "Kowalski", "Nakamura", "Fischer", "Rossi", "Bennett", "Natarajan", "Haddad", "Silva"]
CITIES = [("Orlando", "FL", "US"), ("Miami", "FL", "US"), ("Tampa", "FL", "US"), ("Atlanta", "GA", "US"),
          ("Charlotte", "NC", "US"), ("Dallas", "TX", "US"), ("Houston", "TX", "US"), ("Austin", "TX", "US"),
          ("Chicago", "IL", "US"), ("Columbus", "OH", "US"), ("New York", "NY", "US"), ("Newark", "NJ", "US"),
          ("Philadelphia", "PA", "US"), ("Boston", "MA", "US"), ("Nashville", "TN", "US"), ("Denver", "CO", "US"),
          ("Phoenix", "AZ", "US"), ("Los Angeles", "CA", "US"), ("San Diego", "CA", "US"), ("Seattle", "WA", "US"),
          ("Toronto", "ON", "CA"), ("Montreal", "QC", "CA"), ("London", "", "GB"), ("Manchester", "", "GB"),
          ("Mexico City", "", "MX"), ("San Juan", "PR", "US")]
DRIVING_NEEDS = ["hybrid preferred", "ev preferred", "apple carplay", "android auto", "hand controls", "no-smoking car only",
                 "pet friendly", "large trunk"]
CELEBRATIONS = ["anniversary", "birthday", "honeymoon", "retirement", "graduation", "family reunion"]
CHANNELS = ["couchbase.com", "travel_advisor", "call_center", "cbcars_app", "corporate_booking_tool"]
AGE_BANDS = ["0-2", "3-5", "6-11", "12-17", "18-24", "25-34", "35-44", "45-54", "55-64", "65-74", "75+"]
INTEREST_POOL = [i for i in C.INTERESTS]
TRIP_PURPOSES = ["leisure", "leisure", "leisure", "business", "family visit", "relocation"]


def clamp(x: float, lo=0.01, hi=0.99) -> float:
    return round(max(lo, min(hi, x)), 3)


class Gen:
    def __init__(self, export_date: dt.date, seed: int):
        self.d0 = export_date
        self.r = random.Random(seed)
        self.customer_seq = 100000
        self.booking_seq = 4800000
        self.rentals = self._rentals()

    # -- rentals (pickup days per location) -------------------------------------
    def _rentals(self):
        out = []
        for code, loc in C.LOCATIONS.items():
            trips = C.LOCATION_TRIPS[code]
            day = self.d0 - dt.timedelta(days=self.d0.weekday())  # Monday this week
            i = 0
            while day < self.d0 + dt.timedelta(days=150):
                trip_code = trips[i % len(trips)]
                trip = C.TRIPS[trip_code]
                # Week-long trips start on Sundays, short ones Fri (3d) / Mon (4d)
                offset = {7: 6, 3: 4, 4: 0}.get(trip["days"], 6)
                pickup = day + dt.timedelta(days=offset)
                if pickup > self.d0:
                    out.append(self._rental(code, trip_code, pickup))
                day += dt.timedelta(days=7)
                i += 1
        return out

    def _rental(self, location_code, trip_code, pickup):
        trip = C.TRIPS[trip_code]
        hub = C.LOCATIONS[location_code]["hub"]
        stops = []
        for n, p in enumerate(trip["stops"]):
            code = hub if p in ("PU", "RT") else p
            date = pickup + dt.timedelta(days=n)
            stops.append({
                "day": n + 1, "date": date.isoformat(), "stop_code": code, "stop": C.STOPS[code],
                "arrive": None if p in ("PU", "DRV") else ("09:00" if p == "RT" else "11:00"),
                "depart": None if p in ("RT", "DRV") else ("10:00" if p == "PU" else "09:00"),
                "type": {"PU": "pickup", "RT": "dropoff", "DRV": "drive"}.get(p, "stop"),
            })
        return {
            "rental_id": f"{location_code}-{pickup:%Y%m%d}",
            "location_code": location_code, "location_name": C.LOCATIONS[location_code]["name"],
            "trip_code": trip_code, "trip_name": trip["name"], "days": trip["days"],
            "pickup_location_code": hub, "pickup_location": C.STOPS[hub],
            "pickup_date": pickup.isoformat(),
            "return_date": (pickup + dt.timedelta(days=trip["days"])).isoformat(),
            "stops": stops,
        }

    def pick_rental(self):
        # Near-term pickups are over-represented: they are the ones the app
        # is actively personalizing (pre-trip planner window).
        r = self.r
        horizon = 150 if r.random() < 0.55 else 30
        while True:
            s = r.choice(self.rentals)
            days = (dt.date.fromisoformat(s["pickup_date"]) - self.d0).days
            if days <= horizon:
                return s

    def find_rental(self, location_code, days_out, trip_code=None):
        """The demo personas' rental: exactly `days_out` days after the export
        date, whatever weekday that is, so the story ("Olivia picks up in 9
        days") is the same in every daily unload. Same trip plan as the
        location's nearest scheduled pickup."""
        target = self.d0 + dt.timedelta(days=days_out)
        best = min((s for s in self.rentals if s["location_code"] == location_code),
                   key=lambda s: abs((dt.date.fromisoformat(s["pickup_date"]) - target).days))
        if best["pickup_date"] == target.isoformat() and trip_code in (None, best["trip_code"]):
            return best
        return self._rental(location_code, trip_code or best["trip_code"], target)

    # -- people -------------------------------------------------------------
    def next_customer_id(self):
        self.customer_seq += 1
        return f"C{self.customer_seq:08d}"

    def next_booking(self):
        self.booking_seq += self.r.randint(1, 37)
        return f"{self.booking_seq}"

    def tier_for(self, rentals):
        pts = rentals * 9 + self.r.randint(0, 9) if rentals else 0
        tier = "Preferred"
        for t in C.LOYALTY_TIERS:
            if pts >= C.LOYALTY_THRESHOLDS[t]:
                tier = t
        return tier, pts

    def history(self, rentals, base_class_rank):
        r = self.r
        past = []
        for k in range(min(rentals, 12)):
            loc = r.choice(list(C.LOCATIONS))
            days = r.choice([1, 2, 3, 4, 5, 7, 7, 9])
            when = self.d0 - dt.timedelta(days=r.randint(60, 365 * 8))
            rank = max(1, min(7, base_class_rank + r.choice([-1, 0, 0, 0, 1])))
            spend = round(days * r.uniform(8, 60) * (0.7 + rank * 0.18), 2)
            past.append({
                "location_code": loc, "location_name": C.LOCATIONS[loc]["name"], "pickup_date": when.isoformat(),
                "days": days, "car_class": C.CAR_CLASSES[rank - 1]["name"],
                "ancillary_spend_usd": spend,
                "extras_added": r.randint(0, 3), "protection_days": r.choice([0, 0, days, days]),
                "nps": r.choice([6, 7, 8, 9, 9, 10, 10, None]),
            })
        past.sort(key=lambda p: p["pickup_date"], reverse=True)
        return past

    def row(self, s, booking_id, party, me, lead, vehicle, booked_date, overrides=None):
        r = self.r
        rentals = me["rentals"]
        tier, pts = self.tier_for(rentals)
        past = self.history(rentals, C.CLASS_BY_CODE[vehicle["class_code"]]["rank"])
        avg_spend = round(sum(p["ancillary_spend_usd"] for p in past) / len(past), 2) if past else 0.0
        interests = me["interests"]
        adult = me["age_band"] not in ("0-2", "3-5", "6-11", "12-17")
        price_sens = clamp(r.gauss(0.5, 0.2) - (0.05 * C.LOYALTY_TIERS.index(tier)))
        spend_mix = [r.random() for _ in range(6)]
        tot = sum(spend_mix)
        spend_mix = [round(x / tot, 3) for x in spend_mix]
        has_kids = any(p["age_band"] in ("0-2", "3-5", "6-11", "12-17") for p in party)
        rank = C.CLASS_BY_CODE[vehicle["class_code"]]["rank"]
        up_prop = clamp(0.25 + 0.08 * min(rentals, 5) + (0.12 if me.get("celebration") else 0)
                        - 0.3 * price_sens + r.gauss(0, 0.12) - (0.04 * max(0, rank - 4)))
        rec_rank = min(7, rank + (2 if up_prop > 0.75 and rank <= 3 else 1))
        rec_code = C.CAR_CLASSES[rec_rank - 1]["code"]
        min_offer = C.upgrade_offer_min(vehicle["class_code"], rec_code) if rank < 7 else 0
        rec_offer = int(round(min_offer * (1.15 + (1 - price_sens) * 0.6) / 5) * 5) if min_offer else 0
        if min_offer:
            rec_offer = max(min_offer, min(rec_offer, C.upgrade_price_pd(vehicle["class_code"], rec_code) - 5))

        scores = {
            "model_version": MODEL_VERSION,
            "scored_at": f"{self.d0.isoformat()}T05:12:44Z",
            "upgrade_propensity": up_prop if rank < 7 else 0.0,
            "price_sensitivity": price_sens,
            "fuel_propensity": clamp(spend_mix[0] * 1.6 + (0.2 if adult else -0.4) + r.gauss(0, 0.1)),
            "protection_propensity": clamp(spend_mix[1] * 1.5 + (0.2 if has_kids else 0) + r.gauss(0.1, 0.1)),
            "extras_propensity": clamp(spend_mix[2] * 1.4 + 0.1 * len(interests) / 3 + r.gauss(0.1, 0.1)),
            "services_propensity": clamp(spend_mix[3] * 1.5 + (0.35 if "luxury" in interests or "business travel" in interests else 0) + (0.1 if adult else -0.5)),
            "wifi_propensity": clamp(0.35 + (0.25 if me["age_band"] in ("12-17", "18-24", "25-34") else 0) + r.gauss(0, 0.15)),
            "total_propensity": clamp(0.15 + (0.2 if has_kids else 0) + 0.1 * (1 - price_sens) + r.gauss(0, 0.1)),
            "toll_propensity": clamp(spend_mix[4] * 1.3 + (0.2 if s["location_code"] in ("MIA", "FLL", "MCO", "DFW", "IAH", "ORD", "JFK", "EWR", "BOS", "DEN") else -0.2)),
            "churn_risk": clamp(0.35 - 0.04 * min(rentals, 8) + r.gauss(0, 0.08)),
            "predicted_ancillary_spend_usd": round(avg_spend * r.uniform(0.85, 1.25) if avg_spend else s["days"] * r.uniform(12, 45), 2),
            "recommended_upgrade_class": rec_code if rank < 7 else None,
            "recommended_offer_per_day_usd": rec_offer,
            "segment": r.choice(["Family Road Trippers", "Luxury Celebrators", "Value Explorers", "Convenience Seekers",
                                 "Weekend Escapers", "Road Warriors", "Loyal Renters", "First-Time Families"]),
        }
        nba = max(
            [("upgrade_offer", scores["upgrade_propensity"]),
             ("fuel_bundle", scores["fuel_propensity"]),
             ("rental_extra", scores["extras_propensity"]),
             ("protection", scores["protection_propensity"]),
             ("service", scores["services_propensity"])], key=lambda x: x[1])[0]
        scores["next_best_action"] = nba

        days_out = (dt.date.fromisoformat(s["pickup_date"]) - self.d0).days
        purchased = {"bundles": [], "extras": [], "protection": [], "services": []}
        if r.random() < 0.18:
            purchased["bundles"].append(r.choice(["WIFI", "PEACE", "PEACE", "ETOLL", "TOTAL"]))
        if r.random() < 0.15:
            fits = [e for e in C.EXTRAS if C.extra_fits_trip(e, s) and e["price"]]
            if fits:
                purchased["extras"].append(r.choice(fits)["id"])

        row = {
            "export_date": self.d0.isoformat(),
            "schema_version": SCHEMA_VERSION,
            "customer_id": me["customer_id"],
            "wizard_number": f"{300000000 + int(me['customer_id'][1:]) * 7 % 699999999}",
            "first_name": me["first_name"], "last_name": me["last_name"],
            "email": f"{me['first_name'].lower()}.{me['last_name'].lower().replace(chr(39), '')}{int(me['customer_id'][1:]) % 997}@example.com"
            if adult else None,
            "age_band": me["age_band"],
            "home_city": me["city"][0], "home_state": me["city"][1], "home_country": me["city"][2],
            "preferred_language": "es" if me["city"][2] == "MX" else ("fr" if me["city"][1] == "QC" else "en"),
            "loyalty": {"program": "Couchbase Cars Preferred", "tier": tier, "points": pts,
                        "rentals_completed": rentals, "member_since": str(self.d0.year - min(rentals * 2, 25) - r.randint(0, 2))},
            "reservation": {
                "booking_id": booking_id, "booking_status": "Confirmed", "booked_date": booked_date.isoformat(),
                "booking_channel": r.choice(CHANNELS), "lead_customer": lead,
                "trip_purpose": r.choice(TRIP_PURPOSES),
                **{k: s[k] for k in ("rental_id", "location_code", "location_name", "trip_code", "trip_name",
                                     "days", "pickup_location_code", "pickup_location", "pickup_date", "return_date", "stops")},
                "days_to_pickup": days_out,
                "party_size": len(party),
                "party": [{"customer_id": p["customer_id"], "name": f"{p['first_name']} {p['last_name']}",
                           "age_band": p["age_band"], "relationship": p["relationship"]} for p in party],
                "vehicle": vehicle,
                "rate_paid_usd": round(C.CLASS_BY_CODE[vehicle["class_code"]]["base_pd"] * s["days"] * r.uniform(0.85, 1.2), 2),
                "balance_due_usd": 0.0 if days_out < 90 else round(r.uniform(50, 400), 2),
                "checkin_status": "complete" if (days_out < 14 and r.random() < 0.35) else "not_started",
                "pickup_slot": None,
                "fuel_option": r.choice(["Pay at the pump", "Prepaid fuel", "Return full"]),
            },
            "preferences": {
                "interests": interests,
                "driving_needs": me["driving_needs"],
                "celebration": me.get("celebration"),
                "transmission": r.choice(["automatic", "automatic", "manual"]) if not has_kids else "automatic",
                "fuel_type": r.choice(["gasoline", "hybrid", "ev", "any"]),
                "vehicle_pref": r.choice(["SUV", "convertible", "sedan", "minivan", "pickup truck", None]),
                "communication_channel": r.choice(["push", "email", "sms"]),
                "travels_with_kids": has_kids,
            },
            "history": {
                "past_rentals": past,
                "avg_ancillary_spend_usd": avg_spend,
                "lifetime_value_usd": round(sum(p["ancillary_spend_usd"] for p in past) + rentals * r.uniform(150, 900), 2),
                "upgrades_accepted": r.randint(0, min(rentals, 4)),
                "upgrade_offers_placed": r.randint(0, min(rentals, 6)),
                "last_nps": past[0]["nps"] if past else None,
            },
            "ancillary_spend_mix": dict(zip(["fuel", "protection", "extras", "services", "tolls", "upgrades"], spend_mix)),
            "purchased_for_rental": purchased,
            "ml_scores": scores,
            # Redshift customer 360: the resolved identity and the segments this profile qualifies for.
            "identity": {"customer_id": me["customer_id"], "crm_id": f"CBCARS-{me['customer_id']}",
                         "wizard_number": f"{300000000 + int(me['customer_id'][1:]) * 7 % 699999999}",
                         "resolved_by": "customer_360_identity_graph"},
            "segments": audiences_for(scores, tier, rentals, has_kids, me.get("celebration")),
            "consent": {"personalization_opt_in": r.random() > 0.03, "marketing_opt_in": r.random() > 0.2},
            "_ingest": {"system": "amazon-redshift", "workgroup": WORKGROUP, "source_view": SOURCE_VIEW,
                        "job": "redshift-daily-unload"},
        }
        if overrides:
            deep_update(row, overrides)
            # Persona overrides change the scores, so re-derive the segments from them.
            row["segments"] = audiences_for(row["ml_scores"], row["loyalty"]["tier"], rentals, has_kids,
                                             row["preferences"].get("celebration"))
        return row

    def person(self, last=None, age_band=None, relationship="self", city=None, first=None):
        r = self.r
        return {
            "customer_id": self.next_customer_id(),
            "first_name": first or r.choice(FIRST),
            "last_name": last or r.choice(LAST),
            "age_band": age_band or r.choice(AGE_BANDS[4:]),
            "relationship": relationship,
            "city": city or r.choice(CITIES),
            "rentals": max(0, int(r.expovariate(1 / 4.5))),
            "interests": r.sample(INTEREST_POOL, r.randint(2, 5)),
            "driving_needs": r.sample(DRIVING_NEEDS, 1) if r.random() < 0.18 else [],
            "celebration": r.choice(CELEBRATIONS) if r.random() < 0.16 else None,
        }

    def vehicle(self, s, code):
        cls = C.CLASS_BY_CODE[code]
        level = self.r.randint(*cls["levels"])
        num = f"P{level}-{self.r.randint(100, 699):03d}"
        lot = self.r.choice(C.LOCATIONS[s["location_code"]]["lots"])
        return {"space_number": num, "level": level, "class_code": code, "class_name": cls["name"],
                "lot": lot, "location": self.r.choice(["Near the exit", "Mid-row", "Far end"]), "example": cls["example"]}

    def coverage_rows(self):
        """One booking per location picking up within two weeks, so every
        location in the fleet has a renter in the planning window however
        small the export is (the fleet workload plays one per location)."""
        rows = []
        for code in C.LOCATIONS:
            soon = [s for s in self.rentals if s["location_code"] == code
                    and (dt.date.fromisoformat(s["pickup_date"]) - self.d0).days <= 14]
            if soon:
                rows += self.booking_rows(self.r.choice(soon))
        return rows

    def booking_rows(self, s=None):
        r = self.r
        s = s or self.pick_rental()
        lead = self.person()
        size = r.choices([1, 1, 2, 2, 2, 3, 4, 4, 5], k=1)[0]
        party = [lead]
        kids = r.random() < 0.35 and size >= 3
        for n in range(size - 1):
            if n == 0:
                p = self.person(last=lead["last_name"] if r.random() < 0.7 else None, relationship="spouse/partner",
                                city=lead["city"])
            elif kids:
                p = self.person(last=lead["last_name"], age_band=r.choice(AGE_BANDS[1:4]), relationship="child",
                                city=lead["city"])
                p["rentals"] = min(p["rentals"], 3)
            else:
                p = self.person(relationship="friend/family", city=lead["city"])
            party.append(p)
        code = r.choices(["ECAR", "CCAR", "ICAR", "FCAR", "SFAR", "PCAR", "LCAR"], weights=[14, 22, 30, 18, 10, 4, 2])[0]
        vehicle = self.vehicle(s, code)
        bid = self.next_booking()
        booked = dt.date.fromisoformat(s["pickup_date"]) - dt.timedelta(days=r.randint(3, 180))
        return [self.row(s, bid, party, p, i == 0, vehicle, booked) for i, p in enumerate(party)]

    # -- personas -------------------------------------------------------------
    def personas(self):
        """Hand-built demo customers. Their pickups are relative to the export
        date so the demo story stays the same whenever the export is generated."""
        rows = []

        # 1. Olivia Bennett - President's Club, anniversary road trip, picks up at LAX in 9 days,
        #    Full-size -> high upgrade propensity for a Premium / Luxury car.
        s = self.find_rental("LAX", 9, "7SOCAL")
        o = {"customer_id": "C00000101", "first_name": "Olivia", "last_name": "Bennett", "age_band": "45-54",
             "relationship": "self", "city": ("Charlotte", "NC", "US"), "rentals": 12,
             "interests": ["scenic drives", "food & wine", "luxury", "beach", "photography"], "driving_needs": [],
             "celebration": "anniversary"}
        d = {"customer_id": "C00000102", "first_name": "Daniel", "last_name": "Bennett", "age_band": "45-54",
             "relationship": "spouse/partner", "city": ("Charlotte", "NC", "US"), "rentals": 11,
             "interests": ["food & wine", "golf", "history"], "driving_needs": ["apple carplay"], "celebration": "anniversary"}
        veh = {"space_number": "P2-254", "level": 2, "class_code": "FCAR", "class_name": "Full-size",
               "lot": "Garage P2", "location": "Mid-row", "example": "Nissan Altima or similar"}
        for i, p in enumerate([o, d]):
            rows.append(self.row(s, "4810101", [o, d], p, i == 0, veh, self.d0 - dt.timedelta(days=60), overrides={
                "ml_scores": {"upgrade_propensity": 0.86, "price_sensitivity": 0.22, "segment": "Luxury Celebrators",
                              "recommended_upgrade_class": "PCAR", "recommended_offer_per_day_usd": 24,
                              "next_best_action": "upgrade_offer", "protection_propensity": 0.81,
                              "services_propensity": 0.77, "fuel_propensity": 0.64, "extras_propensity": 0.72},
                "reservation": {"checkin_status": "not_started", "booking_channel": "cbcars_app", "trip_purpose": "leisure"},
                "consent": {"personalization_opt_in": True, "marketing_opt_in": True},
                "purchased_for_rental": {"bundles": ["PEACE"], "extras": [], "protection": [], "services": []},
                "email": f"{p['first_name'].lower()}.bennett@example.com",
            }))

        # 2. Carlos Rivera - Preferred, family of four, Orlando getaway from MCO in 3 days, Intermediate.
        s = self.find_rental("MCO", 3, "3ORLANDO")
        fam = [
            {"customer_id": "C00000201", "first_name": "Carlos", "last_name": "Rivera", "age_band": "35-44"},
            {"customer_id": "C00000202", "first_name": "Ana", "last_name": "Rivera", "age_band": "35-44"},
            {"customer_id": "C00000203", "first_name": "Mateo", "last_name": "Rivera", "age_band": "6-11"},
            {"customer_id": "C00000204", "first_name": "Lucia", "last_name": "Rivera", "age_band": "3-5"},
        ]
        rels = ["self", "spouse/partner", "child", "child"]
        for p, rel in zip(fam, rels):
            p.update({"relationship": rel, "city": ("Columbus", "OH", "US"), "rentals": 1 if rel != "child" else 0,
                      "interests": ["theme parks", "family", "kids", "beach", "thrill"], "driving_needs": [],
                      "celebration": "birthday" if p["first_name"] == "Mateo" else None})
        veh = {"space_number": "P1-531", "level": 1, "class_code": "ICAR", "class_name": "Intermediate",
               "lot": "Garage P1", "location": "Far end", "example": "Toyota Corolla or similar"}
        for i, p in enumerate(fam):
            rows.append(self.row(s, "4820202", fam, p, i == 0, veh, self.d0 - dt.timedelta(days=34), overrides={
                "ml_scores": {"upgrade_propensity": 0.58, "price_sensitivity": 0.66, "segment": "First-Time Families",
                              "recommended_upgrade_class": "SFAR", "recommended_offer_per_day_usd": 14,
                              "next_best_action": "rental_extra", "extras_propensity": 0.88,
                              "total_propensity": 0.61, "fuel_propensity": 0.42, "toll_propensity": 0.74},
                "reservation": {"checkin_status": "not_started", "trip_purpose": "leisure"},
                "consent": {"personalization_opt_in": True, "marketing_opt_in": True},
                "purchased_for_rental": {"bundles": [], "extras": [], "protection": [], "services": []},
                "email": f"{p['first_name'].lower()}.rivera@example.com" if rel in ("self", "spouse/partner") else None,
            }))

        # 3. Priya Natarajan - Preferred Plus, solo business traveler, picks up at SFO in 2 days, Premium.
        s = self.find_rental("SFO", 2, "3BAYAREA")
        p = {"customer_id": "C00000301", "first_name": "Priya", "last_name": "Natarajan", "age_band": "35-44",
             "relationship": "self", "city": ("Austin", "TX", "US"), "rentals": 4,
             "interests": ["business travel", "ev", "wellness", "food & wine", "cycling"], "driving_needs": ["ev preferred"],
             "celebration": None}
        veh = {"space_number": "P1-118", "level": 1, "class_code": "PCAR", "class_name": "Premium",
               "lot": "Preferred Row", "location": "Near the exit", "example": "BMW 3 Series or similar"}
        rows.append(self.row(s, "4830303", [p], p, True, veh, self.d0 - dt.timedelta(days=20), overrides={
            "ml_scores": {"upgrade_propensity": 0.71, "price_sensitivity": 0.31, "segment": "Road Warriors",
                          "recommended_upgrade_class": "LCAR", "recommended_offer_per_day_usd": 20,
                          "next_best_action": "service", "services_propensity": 0.93, "protection_propensity": 0.79,
                          "fuel_propensity": 0.28, "wifi_propensity": 0.82},
            "reservation": {"checkin_status": "complete", "pickup_slot": "12:00", "trip_purpose": "business"},
            "consent": {"personalization_opt_in": True, "marketing_opt_in": True},
            "purchased_for_rental": {"bundles": ["ETOLL"], "extras": [], "protection": [], "services": []},
            "email": "priya.natarajan@example.com",
        }))
        return rows


def deep_update(base: dict, upd: dict):
    for k, v in upd.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_update(base[k], v)
        else:
            base[k] = v


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export-date", default=dt.date.today().isoformat())
    ap.add_argument("--target-mb", type=float, default=100.0, help="approximate total size in MiB")
    ap.add_argument("--parts", type=int, default=4, help="number of part files (keep each under GitHub's 50MB warning)")
    ap.add_argument("--seed", type=int, default=20261009)
    ap.add_argument("--out", default=os.path.join(HERE, "..", "data", "redshift-unload"))
    args = ap.parse_args(argv)

    export_date = dt.date.fromisoformat(args.export_date)
    g = Gen(export_date, args.seed)
    target = int(args.target_mb * 1024 * 1024)
    per_part = target // args.parts + 1
    out_dir = os.path.abspath(os.path.join(args.out, f"dt={export_date:%Y%m%d}"))
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(out_dir):
        if f.endswith("_part_00.json") or f.startswith("part-") or f in ("manifest", "_manifest.json"):
            os.remove(os.path.join(out_dir, f))

    job_uuid = uuid.UUID(int=g.r.getrandbits(128))
    written, rows, bookings, customers_total = 0, 0, 0, 0
    files = []
    pending = g.personas() + g.coverage_rows()
    bookings += 3 + len(C.LOCATIONS)
    for part in range(args.parts):
        name = f"{part:04d}_part_00.json"
        path = os.path.join(out_dir, name)
        part_bytes, part_rows = 0, 0
        with open(path, "w", encoding="utf-8") as fh:
            while part_bytes < per_part and written < target:
                if not pending:
                    pending = g.booking_rows()
                    bookings += 1
                line = json.dumps(pending.pop(0), separators=(",", ":"), ensure_ascii=False) + "\n"
                b = len(line.encode("utf-8"))
                fh.write(line)
                part_bytes += b
                written += b
                part_rows += 1
        rows += part_rows
        files.append({"file": name, "rows": part_rows, "bytes": part_bytes})
        print(f"  {name}  {part_rows:>7,} rows  {part_bytes / 1048576:6.1f} MiB", flush=True)
    customers_total = rows

    # UNLOAD ... MANIFEST format (entries with url + meta.content_length), plus an
    # `unload` block the demo adds for the loader and the story page.
    bucket = f"s3://cbcars-analytics-unload/customer_profile_personalization/dt={export_date:%Y%m%d}/"
    manifest = {
        "entries": [{"url": bucket + f["file"], "meta": {"content_length": f["bytes"], "record_count": f["rows"]}} for f in files],
        "unload": {
            "system": "amazon-redshift", "workgroup": WORKGROUP, "source_view": SOURCE_VIEW, "job": "redshift-daily-unload",
            "query_id": str(uuid.UUID(int=g.r.getrandbits(128))), "partition": f"dt={export_date:%Y%m%d}",
            "export_date": export_date.isoformat(), "schema_version": SCHEMA_VERSION, "model_version": MODEL_VERSION,
            "format": "json", "rows": rows, "bookings": bookings, "bytes": written,
            "rentals": len(g.rentals), "generator": "redshift/generate_mock_unload.py", "seed": args.seed,
            "demo_personas": ["C00000101", "C00000201", "C00000301"],
        },
    }
    with open(os.path.join(out_dir, "manifest"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    print(f"Wrote {rows:,} renter reservations ({bookings:,} bookings, {customers_total:,} customers) "
          f"= {written / 1048576:.1f} MiB to {out_dir}")


if __name__ == "__main__":
    main()
