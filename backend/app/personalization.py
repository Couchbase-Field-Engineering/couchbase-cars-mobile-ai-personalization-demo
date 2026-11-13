"""Ranks the "For You" offers for one customer.

Inputs are the Redshift ML scores and preferences from the daily Amazon Redshift
Redshift unload, plus live state the export can't know about: what the
customer has added since (bookings), unreserved car inventory, and how close
the pickup is. The result is written to `offers::<customer_id>`, which Sync
Gateway replicates to the customer's phone - so the For You feed renders from
Couchbase Lite, even offline, and re-ranks itself on the next sync after
every booking.
"""
from __future__ import annotations

from . import catalog as C
from .docs import days_to_pickup, customer_channel, now_iso, offers_id, profile_id
from .store import store

PALETTES = {  # gradient keys the app maps to brand gradients
    "upgrade": "luxury", "extra": "road", "protection": "protection", "bundle": "fuel", "service": "service", "checkin": "counter",
}


def _reason_list(*parts):
    return " · ".join([p for p in parts if p])


async def compute_offers(profile: dict) -> list[dict]:
    from .actions import get_inventory  # avoid import cycle

    r = profile["reservation"]
    s = profile["ml_scores"]
    prefs = profile["preferences"]
    owned = profile.get("purchased_for_rental", {})
    dts = days_to_pickup(profile)
    kids = bool(prefs.get("travels_with_kids"))
    offers: list[dict] = []
    if not profile.get("consent", {}).get("personalization_opt_in", True):
        return offers

    # --- check-in -------------------------------------------------------
    if r["checkin_status"] != "complete" and 0 <= dts <= 45:
        offers.append({
            "offer_id": "checkin", "kind": "checkin", "palette": PALETTES["checkin"],
            "title": "Check in & skip the counter",
            "subtitle": f"Picking up in {dts} day{'s' if dts != 1 else ''} - go straight to your car",
            "reason": "Pick a pickup window" + (" · morning windows are filling" if dts <= 10 else ""),
            "price_label": "Free", "score": 1.0 + (0.5 if dts <= 7 else 0),
            "cta": {"label": "Check in", "screen": "checkin"},
        })

    # --- vehicle upgrade -------------------------------------------------
    rec = s.get("recommended_upgrade_class")
    cur_rank = C.CLASS_BY_CODE[r["vehicle"]["class_code"]]["rank"]
    if rec and C.CLASS_BY_CODE[rec]["rank"] <= cur_rank:
        # Already upgraded past the model's pick since the export - offer the next step up instead.
        rec = C.CAR_CLASSES[cur_rank]["code"] if cur_rank < len(C.CAR_CLASSES) else None
        s = {**s, "recommended_offer_per_day_usd": None}
    if rec and dts >= 0:
        inv, _ = await get_inventory(r["rental_id"])
        if inv["available"].get(rec, 0) > 0:
            cur = r["vehicle"]["class_code"]
            min_offer = C.upgrade_offer_min(cur, rec)
            pd = C.upgrade_price_pd(cur, rec)
            offer = s.get("recommended_offer_per_day_usd") or min_offer
            reason = _reason_list(
                f"Only {inv['available'][rec]} left" if inv["available"][rec] <= 3 else None,
                f"Perfect for your {prefs['celebration']}" if prefs.get("celebration") else None,
                "Room for the whole family" if kids and rec == "SFAR" else None,
                f"{profile['loyalty']['tier']} member" if profile["loyalty"]["tier"] not in ("Preferred", "Member") else None,
            )
            offers.append({
                "offer_id": f"upgrade-{rec}", "kind": "upgrade", "palette": PALETTES["upgrade"],
                "title": f"Upgrade to {C.a_or_an(C.CLASS_BY_CODE[rec]['name'])}",
                "subtitle": f"{C.CLASS_BY_CODE[rec]['example']} · standby offer from ${min_offer}/day, or upgrade now for ${pd}/day",
                "reason": reason or "Your upgrade pick for this rental",
                "price_label": f"Suggested offer ${offer}/day",
                "score": s.get("upgrade_propensity", 0) * (1.15 if dts <= 14 else 1.0),
                "cta": {"label": "See upgrade options", "screen": "upgrade", "args": {"class_code": rec, "offer": offer}},
                # Everything the Upgrade screen needs, so it works offline from Couchbase Lite.
                "options": [{
                    "class_code": c["code"], "class_name": c["name"], "example": c["example"],
                    "available": inv["available"].get(c["code"], 0),
                    "instant_price_pd": C.upgrade_price_pd(cur, c["code"]),
                    "instant_total_usd": C.upgrade_price_pd(cur, c["code"]) * r["days"],
                    "upgrade_offer_min_pd": C.upgrade_offer_min(cur, c["code"]),
                    "perks": C.CLASS_PERKS.get(c["code"], []), "recommended": c["code"] == rec,
                    "recommended_offer_pd": offer if c["code"] == rec else None,
                } for c in C.CAR_CLASSES if cur_rank < c["rank"] <= cur_rank + 3],
                "days": r["days"], "party_size": r["party_size"],
            })

    # --- bundles ------------------------------------------------------------
    for pkg in C.BUNDLES:
        if pkg["code"] in owned.get("bundles", []):
            continue
        if pkg["code"] in ("PEACE", "ETOLL", "FUEL") and "TOTAL" in owned.get("bundles", []):
            continue
        if pkg["code"] == "TOTAL" and "PEACE" in owned.get("bundles", []):
            continue
        if profile["age_band"] in ("0-2", "3-5", "6-11", "12-17"):
            continue
        prop = s.get(pkg["propensity"], 0)
        if pkg["code"] == "ETOLL":
            prop = prop * 0.9 if s.get("toll_propensity", 0.5) > 0.5 else prop * 0.5
        if pkg["code"] == "FUEL":
            prop *= 0.8
        offers.append({
            "offer_id": f"bundle-{pkg['code']}", "kind": "bundle", "palette": PALETTES["bundle"],
            "title": pkg["name"], "subtitle": pkg["blurb"],
            "reason": {"PEACE": "Based on what you've added on past rentals",
                       "WIFI": "Stay connected on the road", "TOTAL": "Protection, tolls and fuel, all included" + (" for the whole family" if kids else ""),
                       "FUEL": "No refuelling stop before the airport", "ETOLL": "Toll roads on your route - never stop at a booth"}.get(pkg["code"], ""),
            "price_label": f"${pkg['price_per_day']} {pkg['per']}", "score": prop * 0.85,
            "cta": {"label": "Add to my rental", "tool": "add_bundle", "args": {"bundle_code": pkg["code"]}},
        })

    # --- extras ------------------------------------------------------------------
    likes = set(prefs["interests"]) | {t for c in C.trip_stop_codes(r) for t in C.STOP_TAGS.get(c, [])}
    if kids:
        likes |= {"family", "kids"}
    ex_scored = []
    for e in C.EXTRAS:
        if not C.extra_fits_trip(e, r) or e["id"] in owned.get("extras", []):
            continue
        if "kids" in e["tags"] and not kids:
            continue
        if "accessibility" in e["tags"] and "hand controls" not in (prefs.get("driving_needs") or []):
            continue
        if "pets" in e["tags"] and "pet friendly" not in (prefs.get("driving_needs") or []):
            continue
        match = likes & set(e["tags"])
        if not match:
            continue
        ex_scored.append((len(match), e, sorted(match)))
    ex_scored.sort(key=lambda x: (-x[0], x[1]["price"]))
    shown = 0
    for n, e, match in ex_scored:
        own = sorted(set(prefs["interests"]) & set(e["tags"]))
        why = ("For the kids" if "kids" in e["tags"] and kids
               else f"Your plan stops at {C.STOPS[next(c for c in e['stops'] if c in C.trip_stop_codes(r))].split(',')[0]}" if e.get("stops")
               else f"Because you love {' & '.join(own[:2])}" if own
               else "For the stops on your trip")
        total = e["price"] * (r["days"] if e["per"] == "day" else 1)
        offers.append({
            "offer_id": f"extra-{e['id']}", "kind": "extra", "palette": PALETTES["extra"],
            "title": e["name"], "subtitle": f"{r['location_name']} · {r['pickup_date']} · ${e['price']}/{e['per']}",
            "reason": why,
            "price_label": f"${total} for the rental" if total else "Complimentary",
            "score": s.get("extras_propensity", 0) * (0.6 + 0.15 * n),
            "cta": {"label": "Add to my rental", "tool": "add_rental_extra", "args": {"extra_id": e["id"]}},
        })
        shown += 1
        if shown >= 3:
            break

    # --- protection -------------------------------------------------------
    bundled = {"LDW", "PAI", "PEC", "RSN"} if ("PEACE" in owned.get("bundles", []) or "TOTAL" in owned.get("bundles", [])) else set()
    if "TOTAL" in owned.get("bundles", []):
        bundled |= {"ALI", "TWP"}
    protection = [d for d in C.PROTECTION if C.location_has_protection(r["location_code"], d["id"])
                  and d["id"] not in owned.get("protection", []) and d["id"] not in bundled]
    def dscore(d):
        sc = 0.0
        if prefs.get("celebration") and "celebration" in d["tags"]:
            sc += 0.4
        if kids and "family" in d["tags"]:
            sc += 0.3
        if "ev" in d["tags"] and prefs.get("fuel_type") != "ev" and "ev" not in likes:
            sc -= 1
        sc += 0.2 * len(likes & set(d["tags"]))
        return sc
    protection.sort(key=dscore, reverse=True)
    for d in protection[:2]:
        offers.append({
            "offer_id": f"protection-{d['id']}", "kind": "protection", "palette": PALETTES["protection"],
            "title": d["name"], "subtitle": f"{d['covers']} · ${d['price_pd']} per day",
            "reason": f"Celebrate your {prefs['celebration']} without a worry" if prefs.get("celebration") and "celebration" in d["tags"]
            else ("Peace of mind for the family" if "family" in d["tags"] and kids else "Picked for your route"),
            "price_label": f"${d['price_pd']}/day", "score": s.get("protection_propensity", 0) * (0.7 + dscore(d) * 0.3),
            "cta": {"label": "Add protection", "screen": "protection", "args": {"plan_id": d["id"]}},
        })

    # --- services ---------------------------------------------------------------------
    if profile["age_band"] not in ("0-2", "3-5", "6-11", "12-17"):
        pick = "SVC-DELIVERY" if prefs.get("celebration") in ("anniversary", "honeymoon") or "luxury" in likes else (
            "SVC-EVCHARGE" if prefs.get("fuel_type") == "ev" or "ev" in likes else "SVC-REFUEL")
        if pick not in owned.get("services", []):
            sp = C.SERVICE_BY_ID[pick]
            offers.append({
                "offer_id": f"service-{pick}", "kind": "service", "palette": PALETTES["service"],
                "title": sp["name"], "subtitle": f"Couchbase Cars Services · about {sp['minutes']} min" if sp["minutes"] else "Couchbase Cars Services · we come to you",
                "reason": "Save 20% on mid-rental days" if sp["when"] == "any" else "Start the trip from your hotel door",
                "price_label": f"from ${round(sp['price'] * 0.8)}" if sp["when"] == "any" else f"${sp['price']}",
                "score": s.get("services_propensity", 0) * 0.9,
                "cta": {"label": "Choose a time", "screen": "service", "args": {"service_id": pick}},
            })

    offers.sort(key=lambda o: o["score"], reverse=True)
    for i, o in enumerate(offers):
        o["rank"] = i + 1
        o["score"] = round(o["score"], 3)
    return offers


async def refresh_offers(customer_id: str) -> dict | None:
    profile = await store.get("profiles", profile_id(customer_id))
    if not profile:
        return None
    offers = await compute_offers(profile)
    doc = {
        "type": "offers", "customer_id": customer_id, "offers": offers,
        "model_version": profile["ml_scores"].get("model_version"),
        "segment": profile["ml_scores"].get("segment"),
        "export_date": profile.get("export_date"), "profile_rev": profile.get("rev", 0),
        # Which protection plans this location offers, so the protection screen only offers those.
        "protection_available": C.protection_availability(profile["reservation"]),
        "generated_at": now_iso(), "channels": [customer_channel(customer_id)],
    }
    await store.upsert("offers", offers_id(customer_id), doc)
    return doc
