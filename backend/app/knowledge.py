"""Knowledge Base documents published to AOM by the daily loader.

Two kinds:

* **Customer profile** - one per renter picking up soon, rendered from that
  morning's Amazon Redshift customer-profile unload as plain prose. The concierge retrieves it with a
  `document_id`-scoped search, so a customer's question can only ever be
  grounded in *their own* profile, never a neighbour's that happens to be
  semantically close.
* **Customer Care Playbook** - location, policy and product knowledge (Couchbase Cars Upgrade
  rules, bundles, check-in, protection, extras). Its FAQ entries are Redshift content
  fragments (redshift/playbook/README.md; `FAQ` below is the bundled copy served when
  no Redshift endpoint is configured). Contains no personal data, so answers
  grounded only in it are safe to share across customers through AOM's LLM cache.

FAQ entries are also synced to the phone inside the catalog document, so the
app can answer the common questions offline from Couchbase Lite.
"""
from __future__ import annotations

from . import catalog as C

FAQ = [
    {"q": "What time should I arrive at the rental counter?",
     "a": "Arrive in the pickup window you chose when you completed Skip the Counter check-in - it's on your mobile rental "
          "agreement in the app. Couchbase Cars Preferred members go straight to the Preferred Row: your name and space number are on "
          "the board, the keys are in the car, and you show your license at the exit booth.",
     "keywords": ["arrive", "arrival", "counter", "pickup", "pick up", "what time", "exit booth"]},
    {"q": "How does Couchbase Cars Upgrade work?",
     "a": "Couchbase Cars Upgrade lets you make a standby offer per day for a move to a higher car class. You're only charged if "
          "a car in that class is on the lot when you arrive, and you can change or cancel the offer until 24 hours before "
          "pickup. If you'd rather not wait, an instant upgrade confirms right away at the listed price.",
     "keywords": ["couchbase cars upgrade", "upgrade offer", "standby", "upgrade", "how does"]},
    {"q": "Do I need the Loss Damage Waiver?",
     "a": "The Loss Damage Waiver (LDW) covers damage to or theft of the Couchbase Cars car. Many personal auto policies and "
          "credit cards include rental coverage, so check yours first; if you'd like Couchbase Cars to carry the risk, add LDW on "
          "its own or as part of Peace of Mind or Total Protection. Every listed driver is covered.",
     "keywords": ["ldw", "damage waiver", "insurance", "coverage", "protection", "cover", "deductible"]},
    {"q": "What's included in Couchbase Cars Total Protection?",
     "a": "Couchbase Cars Total Protection bundles the Loss Damage Waiver, Personal Accident & Effects, Additional Liability up to "
          "$1 million, Tire & Windshield Protection, e-Toll Unlimited and a prepaid tank of fuel. Couchbase Cars Peace of Mind is the "
          "lighter bundle: LDW, Personal Accident & Effects and Roadside SafetyNet.",
     "keywords": ["total", "total protection", "peace of mind", "bundle"]},
    {"q": "Is Wi-Fi available in the car?",
     "a": "Yes - the Couchbase Cars Wi-Fi hotspot is a 4G LTE device for up to five devices. It's included with Couchbase Cars Total Protection "
          "or added per day in the app; it's cheaper before you pick up than at the counter.",
     "keywords": ["wifi", "wi-fi", "internet", "hotspot", "online", "connect"]},
    {"q": "How do tolls work?",
     "a": "e-Toll lets you drive every cashless toll road and express lane without stopping; the transponder is in the "
          "car. Pay per toll plus a daily convenience fee on the days you use it, or add e-Toll Unlimited for one flat "
          "rate for the whole rental.",
     "keywords": ["toll", "tolls", "e-toll", "etoll", "express lane", "transponder", "sunpass"]},
    {"q": "What do I need for check-in?",
     "a": "Complete Skip the Counter in the app: confirm your driver's license, add a payment card, choose a pickup window "
          "and accept the rental terms. Your mobile rental agreement is ready in the app; bring the same license and card "
          "with you to the exit booth.",
     "keywords": ["check-in", "check in", "checkin", "documents", "license", "skip the counter", "rental agreement"]},
    {"q": "Can I add a child seat?",
     "a": "Yes - infant, toddler and booster seats are available at every location for a daily fee and are installed in "
          "the car before you arrive when you add them in the app. State law requires a child seat for children under "
          "8 in most of the US.",
     "keywords": ["child seat", "car seat", "booster", "infant", "kids", "children"]},
    {"q": "What is the Preferred Row?",
     "a": "Couchbase Cars Preferred members skip the counter entirely: your name and space number are on the Preferred board, the "
          "keys are in the car and the rental agreement is in the app. Preferred Plus and President's Club members are "
          "parked on the Preferred Row nearest the exit and get complimentary one-class upgrades when available.",
     "keywords": ["preferred row", "preferred", "skip the counter", "president's club", "chairman's club", "loyalty"]},
    {"q": "Are services cheaper mid-rental?",
     "a": "Yes. Hotel delivery, collection, mobile refuel and vehicle swaps booked for a day that isn't your pickup or "
          "return day are typically discounted - this app applies a 20% mid-rental price automatically.",
     "keywords": ["service", "delivery", "collection", "refuel", "swap", "discount", "mid-rental"]},
    {"q": "What are the fuel options?",
     "a": "Return the car full and pay nothing, buy a prepaid tank at our discounted pump price and return it at any "
          "level, or let us refuel on return at the per-gallon rate on your rental agreement.",
     "keywords": ["fuel", "gas", "refuel", "prepaid", "tank", "return full", "charge"]},
]


def playbook_markdown(export_date: str, entries: list[dict] | None = None) -> str:
    lines = [f"# Couchbase Cars Customer Care Playbook (published {export_date})", "",
             "Location, policy and product knowledge for the Couchbase Cars Rental Concierge agent, from the Redshift "
             "customer-care-playbook playbook rows and the fleet catalog. Contains no customer data.", ""]
    lines += ["## Frequently asked questions", ""]
    for f in entries or FAQ:
        lines += [f"**{f['q']}** {f['a']}", ""]
    lines += ["## Car classes and upgrade policy", ""]
    for c in C.CAR_CLASSES:
        perks = ", ".join(C.CLASS_PERKS.get(c["code"], [])) or "standard features"
        lines.append(f"- {c['name']} ({c['code']}): {c['example']}; rates from about ${c['base_pd']} per day; {perks}.")
    lines += ["", "Couchbase Cars Upgrade minimum standby offers per day by number of class steps: "
              + ", ".join(f"{k} step{'s' if k > 1 else ''} ${v}" for k, v in C.UPGRADE_OFFER_MIN_PD.items()) + ".",
              "Instant upgrades are priced at roughly 82% of the rate difference and confirm immediately, subject to "
              "inventory at the pickup location. Upgrades apply to the whole reservation and every listed driver. "
              "Complimentary (goodwill) upgrades are a service recovery gesture that always requires supervisor approval.", ""]
    lines += ["## Bundles", ""]
    for p in C.BUNDLES:
        lines.append(f"- {p['name']} ({p['code']}): ${p['price_per_day']} per {p['per']}. {p['blurb']}")
    lines += ["", "## Protection plans", ""]
    for d in C.PROTECTION:
        locs = "at every location" if d["locations"] == "*" else "at " + ", ".join(C.LOCATIONS[s]["name"] for s in d["locations"])
        lines.append(f"- {d['name']}: {d['covers']}, ${d['price_pd']} per day, {locs}.")
    lines += ["", "## Locations", ""]
    for code, s in C.LOCATIONS.items():
        lines.append(f"- {s['name']} ({code}, {s['class']}), {s['city']}. Lots: " + ", ".join(s["lots"]) + ".")
    lines += ["", "## Extras and equipment", ""]
    for e in C.EXTRAS:
        locs = "every location" if e["locations"] == "*" else ", ".join(e["locations"])
        lines.append(f"- {e['name']} ({e['id']}): ${e['price']} per {e['per']}, at {locs}; good for {', '.join(e['tags'])}.")
    lines += ["", "## Trip plans and stops", ""]
    for code, t in C.TRIPS.items():
        stops = [C.STOPS[s].split(",")[0] for s in t["stops"] if s not in ("PU", "RT", "DRV")]
        lines.append(f"- {t['name']} ({code}): {t['days']} days via " + ", ".join(stops) + ".")
    lines += ["", "## Services", ""]
    for s in C.SERVICES:
        lines.append(f"- {s['name']}: ${s['price']}" + (f", about {s['minutes']} minutes." if s["minutes"] else "."))
    return "\n".join(lines)


def customer_profile_markdown(p: dict) -> str:
    r = p["reservation"]
    s = p["ml_scores"]
    prefs = p["preferences"]
    v = r["vehicle"]
    party = "; ".join(f"{m['name']} ({m['relationship']}, age {m['age_band']})" for m in r["party"])
    stops = ", ".join(f"day {d['day']} {d['date']} {d['stop']}" for d in r["stops"])
    past = p["history"]["past_rentals"][:5]
    past_txt = "; ".join(f"{h['location_name']} {h['pickup_date'][:7]} {h['days']} days in {h['car_class']}, spent "
                         f"${h['ancillary_spend_usd']:,.0f} on extras" for h in past) or "first rental with us"
    mix = p.get("ancillary_spend_mix", {})
    top_mix = ", ".join(f"{k} {v:.0%}" for k, v in sorted(mix.items(), key=lambda kv: -kv[1])[:3])
    owned = p.get("purchased_for_rental", {})
    return "\n".join([
        f"# Customer profile {p['customer_id']}: {p['first_name']} {p['last_name']}",
        f"Source: Amazon Redshift customer-profile unload {p['export_date']}, scores by {s.get('model_version')}"
        + (f"; segments: {', '.join(a['name'] for a in p['segments'])}" if p.get("segments") else "") + ".",
        "",
        "## Upcoming rental",
        f"{p['first_name']} picks up at {r['location_name']} - {r['trip_name']} - from {r['pickup_location']} on "
        f"{r['pickup_date']} returning {r['return_date']} ({r['days']} days), confirmation {r['booking_id']}. "
        f"Vehicle: {v['class_name']} ({v.get('example', '')}) in space {v['space_number']} on level "
        f"{v['level']} ({v['lot']}, {v['location']}). "
        f"Check-in status: {r['checkin_status']}. Fuel: {r['fuel_option']}. Trip purpose: {r.get('trip_purpose', 'leisure')}.",
        f"Traveling party ({r['party_size']}): {party}.",
        f"Trip plan: {stops}.",
        "",
        "## Loyalty and history",
        f"Couchbase Cars Preferred {p['loyalty']['tier']} with {p['loyalty']['points']} points and "
        f"{p['loyalty']['rentals_completed']} completed rentals. Past rentals: {past_txt}. "
        f"Average ancillary spend ${p['history']['avg_ancillary_spend_usd']:,.0f}; accepted "
        f"{p['history']['upgrades_accepted']} upgrades and placed {p['history']['upgrade_offers_placed']} Couchbase Cars Upgrade offers before.",
        f"Ancillary spend mix (top): {top_mix}.",
        "",
        "## Preferences",
        f"Interests: {', '.join(prefs['interests'])}. Driving needs: {', '.join(prefs['driving_needs']) or 'none noted'}. "
        f"Celebrating: {prefs.get('celebration') or 'nothing noted'}. Transmission: {prefs['transmission']}, "
        f"fuel type {prefs['fuel_type']}. Vehicle preference: {prefs.get('vehicle_pref') or 'none'}. "
        f"Travels with kids: {'yes' if prefs.get('travels_with_kids') else 'no'}. "
        f"Prefers {prefs['communication_channel']} messages.",
        "",
        "## Personalization signals",
        f"Segment: {s.get('segment')}. Next best action: {s.get('next_best_action')}. "
        f"Upgrade propensity {s.get('upgrade_propensity')}, recommended upgrade class "
        f"{s.get('recommended_upgrade_class')} with a suggested Couchbase Cars Upgrade offer of ${s.get('recommended_offer_per_day_usd')} "
        f"per day. Price sensitivity {s.get('price_sensitivity')}. Propensities - prepaid fuel "
        f"{s.get('fuel_propensity')}, protection {s.get('protection_propensity')}, extras "
        f"{s.get('extras_propensity')}, services {s.get('services_propensity')}, Wi-Fi {s.get('wifi_propensity')}, "
        f"tolls {s.get('toll_propensity')}, Couchbase Cars Total Protection {s.get('total_propensity')}.",
        f"Already added to this rental: bundles {owned.get('bundles') or 'none'}, extras "
        f"{owned.get('extras') or 'none'}, protection {owned.get('protection') or 'none'}.",
    ])
