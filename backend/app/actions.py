"""Customer-care actions - the business logic behind every MCP tool.

These functions are what actually changes state (vehicle assignments,
inventory, bookings, check-in). They are only ever reached through
`tool_gateway`, which routes them through the Couchbase Agent Operations
Manager when it is configured (RBAC, approvals, tracing, audit) and calls
them in-process otherwise. Every mutation bumps the customer's profile
`rev`, which is what invalidates that customer's context cache and re-ranks
their offers.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import uuid

from . import catalog as C
from .docs import (bookings_id, days_to_pickup, customer_channel, inventory_id, money, now_iso,
                   profile_id)
from .store import store


class ToolError(Exception):
    pass


def _h(*parts) -> int:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
async def load_profile(customer_id: str) -> dict:
    p = await store.get("profiles", profile_id(customer_id))
    if not p:
        raise ToolError(f"No customer profile for '{customer_id}'")
    return p


def party_ids(profile) -> list[str]:
    return [m["customer_id"] for m in profile["reservation"]["party"]]


def adults(profile) -> int:
    return sum(1 for m in profile["reservation"]["party"] if m["age_band"] not in ("0-2", "3-5", "6-11", "12-17")) or 1


def is_child(profile) -> bool:
    return profile["age_band"] in ("0-2", "3-5", "6-11", "12-17")


async def save_profiles(updates: dict[str, dict]):
    for gid, p in updates.items():
        p["rev"] = int(p.get("rev", 0)) + 1
        p["updated_at"] = now_iso()
        await store.upsert("profiles", profile_id(gid), p)
        from .loader import mark_live  # late import: loader -> personalization -> actions
        await mark_live(gid)


async def record_booking(customer_ids: list[str], item: dict):
    for gid in customer_ids:
        doc = await store.get("bookings", bookings_id(gid)) or {
            "type": "bookings", "customer_id": gid, "items": [], "channels": [customer_channel(gid)]}
        doc["items"] = [i for i in doc["items"] if i.get("item_id") != item["item_id"]] + [item]
        doc["updated_at"] = now_iso()
        await store.upsert("bookings", bookings_id(gid), doc)


async def after_change(customer_ids: list[str]):
    # late imports: personalization/concierge import this module
    from . import concierge, personalization
    for gid in customer_ids:
        await personalization.refresh_offers(gid)
        await concierge.invalidate_context(gid)


async def get_inventory(rental_id: str) -> tuple[dict, int]:
    doc, cas = await store.get_with_cas("inventory", inventory_id(rental_id))
    if doc is None:
        await store.insert("inventory", inventory_id(rental_id),
                           {"type": "inventory", "rental_id": rental_id, "available": C.initial_inventory(rental_id),
                            "created_at": now_iso()})
        doc, cas = await store.get_with_cas("inventory", inventory_id(rental_id))
    return doc, cas


async def take_inventory(rental_id: str, code: str):
    for _ in range(10):
        doc, cas = await get_inventory(rental_id)
        if doc["available"].get(code, 0) <= 0:
            raise ToolError(f"No {C.CLASS_BY_CODE[code]['name']} cars are left at this location for your pickup day")
        doc["available"][code] -= 1
        if await store.replace_cas("inventory", inventory_id(rental_id), doc, cas):
            return doc["available"][code]
    raise ToolError("Inventory is busy - please try again")


def _new_vehicle(profile, code) -> dict:
    cls = C.CLASS_BY_CODE[code]
    lo, hi = cls["levels"]
    seed = _h(profile["reservation"]["booking_id"], code)
    level = lo + seed % (hi - lo + 1)
    lots = C.LOCATIONS[profile["reservation"]["location_code"]]["lots"]
    lot = "Premium Row" if code in ("PCAR", "LCAR") else lots[seed % len(lots)]
    return {"space_number": f"P{level}-{100 + seed % 600:03d}", "level": level, "class_code": code,
            "class_name": cls["name"], "lot": lot, "example": cls["example"],
            "location": ["Near the exit", "Mid-row", "Far end"][seed % 3]}


def _item(kind: str, title: str, **kw) -> dict:
    return {"item_id": f"{kind}-{uuid.uuid4().hex[:10]}", "kind": kind, "title": title, "status": "confirmed",
            "booked_at": now_iso(), **kw}


def _rental_dates(profile) -> list[str]:
    return [p["date"] for p in profile["reservation"]["stops"]]


async def _reassign(profile, to_code: str, how: str, charge: float, extra: dict) -> dict:
    res = profile["reservation"]
    old = dict(res["vehicle"])
    new = _new_vehicle(profile, to_code)
    party = party_ids(profile)
    updates = {}
    for gid in party:
        p = profile if gid == profile["customer_id"] else (await store.get("profiles", profile_id(gid)))
        if not p:
            continue
        p["reservation"]["vehicle"] = new
        p["reservation"].setdefault("upgrade_history", []).append(
            {"from": old, "to": new, "how": how, "charge_usd": charge, "at": now_iso(), **extra})
        updates[gid] = p
    await save_profiles(updates)
    item = _item("upgrade", f"Upgrade to {new['class_name']} · Space {new['space_number']}",
                 how=how, from_class=old["class_code"], to_class=to_code, vehicle=new,
                 charge_usd=charge, date=res["pickup_date"], **extra)
    await record_booking(party, item)
    await after_change(party)
    return item


# --------------------------------------------------------------------------
# tools
# --------------------------------------------------------------------------
async def get_customer_context(customer_id: str) -> dict:
    p = await load_profile(customer_id)
    r = p["reservation"]
    return {
        "customer_id": customer_id, "name": f"{p['first_name']} {p['last_name']}",
        "loyalty": p["loyalty"], "location": r["location_name"], "trip": r["trip_name"],
        "pickup_date": r["pickup_date"], "days_to_pickup": days_to_pickup(p), "vehicle": r["vehicle"],
        "party": r["party"], "checkin_status": r["checkin_status"], "preferences": p["preferences"],
        "segment": p["ml_scores"].get("segment"), "next_best_action": p["ml_scores"].get("next_best_action"),
        "purchased": p.get("purchased_for_rental", {}),
    }


async def get_upgrade_offers(customer_id: str) -> dict:
    p = await load_profile(customer_id)
    r = p["reservation"]
    cur = r["vehicle"]["class_code"]
    inv, _ = await get_inventory(r["rental_id"])
    rank = C.CLASS_BY_CODE[cur]["rank"]
    offers = []
    for cls in C.CAR_CLASSES:
        if cls["rank"] <= rank or cls["rank"] > rank + 3:
            continue
        left = inv["available"].get(cls["code"], 0)
        pd = C.upgrade_price_pd(cur, cls["code"])
        min_offer = C.upgrade_offer_min(cur, cls["code"])
        offers.append({
            "class_code": cls["code"], "class_name": cls["name"], "example": cls["example"], "available": left,
            "instant_price_pd": pd, "instant_total_usd": pd * r["days"],
            "upgrade_offer_min_pd": min_offer, "perks": C.CLASS_PERKS.get(cls["code"], []),
            "recommended": cls["code"] == p["ml_scores"].get("recommended_upgrade_class"),
            "recommended_offer_pd": p["ml_scores"].get("recommended_offer_per_day_usd")
            if cls["code"] == p["ml_scores"].get("recommended_upgrade_class") else None,
        })
    return {"customer_id": customer_id, "rental_id": r["rental_id"], "current": r["vehicle"], "days": r["days"],
            "party_size": r["party_size"], "days_to_pickup": days_to_pickup(p), "offers": offers}


def _validate_upgrade(p, to_code):
    if to_code not in C.CLASS_BY_CODE:
        raise ToolError(f"Unknown car class '{to_code}'")
    cur = p["reservation"]["vehicle"]["class_code"]
    if C.CLASS_BY_CODE[to_code]["rank"] <= C.CLASS_BY_CODE[cur]["rank"]:
        raise ToolError(f"{C.CLASS_BY_CODE[to_code]['name']} is not an upgrade from {C.CLASS_BY_CODE[cur]['name']}")
    if days_to_pickup(p) < 0:
        raise ToolError("This rental has already started")
    return cur


async def place_upgrade_offer(customer_id: str, class_code: str, offer_per_day_usd: float) -> dict:
    p = await load_profile(customer_id)
    cur = _validate_upgrade(p, class_code)
    r = p["reservation"]
    min_offer = C.upgrade_offer_min(cur, class_code)
    list_pd = C.upgrade_price_pd(cur, class_code)
    offer = float(offer_per_day_usd)
    if offer < min_offer:
        raise ToolError(f"Minimum Couchbase Cars Upgrade offer for {C.CLASS_BY_CODE[class_code]['name']} is {money(min_offer)} per day")
    if offer > list_pd:
        raise ToolError(f"That offer is above the instant upgrade price ({money(list_pd)}) - upgrade instantly instead")
    # Fleet planning's clearing price for this pickup day/class (deterministic per rental).
    factor = 0.25 + (_h(r["rental_id"], class_code, "clear") % 35) / 100
    clearing = min_offer + (list_pd - min_offer) * factor
    total = round(offer * r["days"], 2)
    if offer >= clearing:
        await take_inventory(r["rental_id"], class_code)
        item = await _reassign(p, class_code, "upgrade_offer", total, {"offer_pd": offer})
        return {"ok": True, "status": "accepted", "charge_usd": total, "item": item,
                "summary": f"Couchbase Cars Upgrade offer accepted! You're now in {C.a_or_an(item['vehicle']['class_name'])} "
                           f"({item['vehicle']['example']}), space {item['vehicle']['space_number']}. {money(total)} charged to your card on file."}
    item = _item("upgrade_offer", f"Couchbase Cars Upgrade standby offer · {C.CLASS_BY_CODE[class_code]['name']}",
                 status="submitted", to_class=class_code, offer_pd=offer, potential_charge_usd=total,
                 date=r["pickup_date"])
    await record_booking([customer_id], item)
    await after_change([customer_id])
    return {"ok": True, "status": "submitted", "charge_usd": 0, "item": item,
            "summary": f"Standby offer of {money(offer)}/day submitted for {C.CLASS_BY_CODE[class_code]['name']}. "
                       "You'll only be charged if a car is on the lot when you arrive - we'll notify you before pickup."}


async def purchase_vehicle_upgrade(customer_id: str, class_code: str) -> dict:
    p = await load_profile(customer_id)
    cur = _validate_upgrade(p, class_code)
    r = p["reservation"]
    total = C.upgrade_price_pd(cur, class_code) * r["days"]
    await take_inventory(r["rental_id"], class_code)
    item = await _reassign(p, class_code, "instant", total, {})
    v = item["vehicle"]
    return {"ok": True, "status": "confirmed", "charge_usd": total, "item": item,
            "summary": f"Upgraded to {v['class_name']} ({v['example']}) - space {v['space_number']} "
                       f"on level {v['level']} ({v['lot']}). {money(total)} charged."}


async def apply_goodwill_upgrade(customer_id: str, class_code: str, reason: str) -> dict:
    """Complimentary upgrade - a customer-care recovery gesture. Held for a
    human decision in AOM's approval tier before it can run."""
    if not reason or len(reason.strip()) < 5:
        raise ToolError("A goodwill upgrade needs a reason for the audit trail")
    p = await load_profile(customer_id)
    _validate_upgrade(p, class_code)
    await take_inventory(p["reservation"]["rental_id"], class_code)
    item = await _reassign(p, class_code, "goodwill", 0.0, {"reason": reason.strip()[:300]})
    return {"ok": True, "status": "confirmed", "charge_usd": 0, "item": item,
            "summary": f"Complimentary upgrade to {item['vehicle']['class_name']} applied - space "
                       f"{item['vehicle']['space_number']}. Reason recorded: {reason.strip()[:120]}"}


async def search_rental_extras(customer_id: str, category: str = "", interest: str = "") -> dict:
    p = await load_profile(customer_id)
    r = p["reservation"]
    likes = set(p["preferences"]["interests"]) | {t for c in C.trip_stop_codes(r) for t in C.STOP_TAGS.get(c, [])}
    if interest:
        likes.add(interest.lower())
    if p["preferences"].get("travels_with_kids"):
        likes |= {"family", "kids"}
    owned = set(p.get("purchased_for_rental", {}).get("extras", []))
    out = []
    for e in C.EXTRAS:
        if not C.extra_fits_trip(e, r):
            continue
        if category and category.lower() not in e["tags"] and category.lower() not in e["name"].lower():
            continue
        match = sorted(likes & set(e["tags"]))
        kid_ok = not ("kids" in e["tags"] and not p["preferences"].get("travels_with_kids"))
        out.append({**e, "location_name": r["location_name"], "date": r["pickup_date"],
                    "total_usd": e["price"] * (r["days"] if e["per"] == "day" else 1),
                    "matched_interests": match, "family_friendly": kid_ok, "already_booked": e["id"] in owned,
                    "score": round(len(match) * 0.3 + (0.15 if kid_ok else -0.3), 2)})
    out.sort(key=lambda e: (-e["score"], e["price"]))
    return {"customer_id": customer_id, "extras": out[:12]}


async def add_rental_extra(customer_id: str, extra_id: str, quantity: int = 1) -> dict:
    p = await load_profile(customer_id)
    r = p["reservation"]
    e = C.EXTRA_BY_ID.get(extra_id)
    if not e:
        raise ToolError(f"Unknown extra '{extra_id}'")
    if not C.extra_fits_trip(e, r):
        if e.get("stops"):
            raise ToolError(f"{e['name']} is for trips that visit a national park, which isn't on your plan")
        raise ToolError(f"{e['name']} isn't stocked at {r['location_name']}")
    n = int(quantity or 1)
    if n < 1 or n > 4:
        raise ToolError("Quantity must be between 1 and 4")
    if e["id"].startswith("SEAT-") and not p["preferences"].get("travels_with_kids") and r["party_size"] == 1:
        raise ToolError("Child seats are for reservations with children in the party")
    total = e["price"] * n * (r["days"] if e["per"] == "day" else 1)
    party = party_ids(p)
    updates = {}
    for gid in party:
        gp = p if gid == customer_id else await store.get("profiles", profile_id(gid))
        if gp:
            gp.setdefault("purchased_for_rental", {}).setdefault("extras", []).append(extra_id)
            updates[gid] = gp
    await save_profiles(updates)
    item = _item("extra", e["name"] + (f" × {n}" if n > 1 else ""), extra_id=extra_id, location=r["location_name"],
                 date=r["pickup_date"], time="pickup", quantity=n, per=e["per"], charge_usd=total)
    await record_booking(party, item)
    await after_change(party)
    return {"ok": True, "status": "confirmed", "charge_usd": total, "item": item,
            "summary": f"Added {e['name']}{' × ' + str(n) if n > 1 else ''} to your {r['location_name']} pickup on "
                       f"{r['pickup_date']} - {money(total)}" + (" (installed before you arrive)." if e["id"].startswith("SEAT-") else ".")}


async def select_protection_plan(customer_id: str, plan_id: str, term: str = "whole rental", drivers: int = 0) -> dict:
    p = await load_profile(customer_id)
    r = p["reservation"]
    d = C.PROTECTION_BY_ID.get(plan_id)
    if not d:
        raise ToolError(f"Unknown protection plan '{plan_id}'")
    if not C.location_has_protection(r["location_code"], plan_id):
        raise ToolError(f"{d['name']} isn't offered at {r['location_name']}")
    if plan_id in p.get("purchased_for_rental", {}).get("protection", []):
        raise ToolError(f"You already have {d['name']} on this rental")
    bundles = p.get("purchased_for_rental", {}).get("bundles", [])
    if plan_id in ("LDW", "PAI", "PEC", "RSN") and ("PEACE" in bundles or "TOTAL" in bundles):
        raise ToolError(f"{d['name']} is already included in your {'Couchbase Cars Total Protection' if 'TOTAL' in bundles else 'Couchbase Cars Peace of Mind'} bundle")
    term = (term or "whole rental").lower()
    if term not in C.PROTECTION_TERMS:
        raise ToolError(f"Choose one of these terms: {', '.join(C.PROTECTION_TERMS)}")
    n = int(drivers or adults(p))
    if n < 1 or n > adults(p):
        raise ToolError(f"Covered drivers must be between 1 and {adults(p)}")
    covered_days = {"whole rental": r["days"], "pickup day only": 1, "first 3 days": min(3, r["days"])}[term]
    total = d["price_pd"] * covered_days
    note = " We've noted you're celebrating your " + p["preferences"]["celebration"] + " - enjoy the road." \
        if p["preferences"].get("celebration") and "celebration" in d["tags"] else ""
    needs = p["preferences"].get("driving_needs") or []
    item = _item("protection", f"{d['name']} · {n} driver{'s' if n > 1 else ''}", plan_id=plan_id, date=r["pickup_date"],
                 time=term, term=term, covered_days=covered_days, drivers=n, charge_usd=total, driving_needs=needs,
                 celebration=p["preferences"].get("celebration"))
    await record_booking([customer_id], item)
    p.setdefault("purchased_for_rental", {}).setdefault("protection", []).append(plan_id)
    await save_profiles({customer_id: p})
    await after_change([customer_id])
    return {"ok": True, "status": "confirmed", "charge_usd": total, "item": item,
            "summary": f"{d['name']} added for {n} driver{'s' if n > 1 else ''}, {term} - {money(total)}.{note}"
                       + (f" Driving needs on file: {', '.join(needs)}." if needs else "")}


async def add_bundle(customer_id: str, bundle_code: str) -> dict:
    p = await load_profile(customer_id)
    r = p["reservation"]
    pkg = C.BUNDLE_BY_CODE.get(bundle_code)
    if not pkg:
        raise ToolError(f"Unknown bundle '{bundle_code}'")
    owned = p.get("purchased_for_rental", {}).get("bundles", [])
    if bundle_code in owned:
        raise ToolError(f"You already have {pkg['name']}")
    if bundle_code in ("PEACE", "ETOLL", "FUEL") and "TOTAL" in owned:
        raise ToolError(f"{pkg['name']} is already included in Couchbase Cars Total Protection")
    if is_child(p):
        raise ToolError("Bundles are added by the primary driver on the reservation")
    qty = 1
    if pkg.get("one_time"):
        total = pkg["price_per_day"] * qty
    else:
        total = pkg["price_per_day"] * r["days"] * qty
    p.setdefault("purchased_for_rental", {}).setdefault("bundles", []).append(bundle_code)
    await save_profiles({customer_id: p})
    item = _item("bundle", pkg["name"], bundle_code=bundle_code, quantity=qty, charge_usd=total, date=r["pickup_date"])
    await record_booking([customer_id], item)
    await after_change([customer_id])
    how = "one-time" if pkg.get("one_time") else f"{r['days']} days"
    return {"ok": True, "status": "confirmed", "charge_usd": total, "item": item,
            "summary": f"{pkg['name']} added for {how} - {money(total)}."
                       + (" Every listed driver is covered." if bundle_code in ("PEACE", "TOTAL") else "")}


async def book_rental_service(customer_id: str, service_id: str, date: str, time: str = "10:00") -> dict:
    p = await load_profile(customer_id)
    r = p["reservation"]
    s = C.SERVICE_BY_ID.get(service_id)
    if not s:
        raise ToolError(f"Unknown service '{service_id}'")
    dates = _rental_dates(p)
    if date not in dates:
        raise ToolError("Pick a day during your rental")
    if s["when"] == "pickup" and date != dates[0]:
        raise ToolError(f"{s['name']} is for your pickup day, {dates[0]}")
    if s["when"] == "return" and date != dates[-1]:
        raise ToolError(f"{s['name']} is for your return day, {dates[-1]}")
    peak = date in (dates[0], dates[-1])
    price = s["price"] if peak else round(s["price"] * 0.8)
    item = _item("service", s["name"], service_id=service_id, date=date, time=time, charge_usd=price,
                 mid_rental_discount=not peak)
    await record_booking([customer_id], item)
    p.setdefault("purchased_for_rental", {}).setdefault("services", []).append(service_id)
    await save_profiles({customer_id: p})
    await after_change([customer_id])
    return {"ok": True, "status": "confirmed", "charge_usd": price, "item": item,
            "summary": f"{s['name']} booked for {date} at {time} - {money(price)}"
                       + ("" if peak else " (20% mid-rental savings applied)") + "."}


async def complete_mobile_checkin(customer_id: str, pickup_slot: str) -> dict:
    p = await load_profile(customer_id)
    if pickup_slot not in C.PICKUP_SLOTS:
        raise ToolError(f"Pickup windows available: {', '.join(C.PICKUP_SLOTS)}")
    dts = days_to_pickup(p)
    if dts > 45:
        raise ToolError("Skip the Counter check-in opens 45 days before pickup")
    party = party_ids(p)
    updates = {}
    for gid in party:
        gp = p if gid == customer_id else await store.get("profiles", profile_id(gid))
        if gp:
            gp["reservation"]["checkin_status"] = "complete"
            gp["reservation"]["pickup_slot"] = pickup_slot
            updates[gid] = gp
    await save_profiles(updates)
    item = _item("checkin", f"Skip the Counter · pickup {pickup_slot}", pickup_slot=pickup_slot,
                 date=p["reservation"]["pickup_date"], time=pickup_slot, charge_usd=0)
    await record_booking(party, item)
    await after_change(party)
    return {"ok": True, "status": "confirmed", "charge_usd": 0, "item": item,
            "summary": f"You're checked in! {len(updates)} traveler{'s' if len(updates) > 1 else ''} picking up at "
                       f"{pickup_slot} on {p['reservation']['pickup_date']}. Your mobile rental agreement is in My Trip - "
                       "go straight to your space."}


TOOLS = {
    "get_customer_context": get_customer_context,
    "get_upgrade_offers": get_upgrade_offers,
    "place_upgrade_offer": place_upgrade_offer,
    "purchase_vehicle_upgrade": purchase_vehicle_upgrade,
    "apply_goodwill_upgrade": apply_goodwill_upgrade,
    "search_rental_extras": search_rental_extras,
    "add_rental_extra": add_rental_extra,
    "select_protection_plan": select_protection_plan,
    "add_bundle": add_bundle,
    "book_rental_service": book_rental_service,
    "complete_mobile_checkin": complete_mobile_checkin,
}
READ_ONLY_TOOLS = {"get_customer_context", "get_upgrade_offers", "search_rental_extras"}
