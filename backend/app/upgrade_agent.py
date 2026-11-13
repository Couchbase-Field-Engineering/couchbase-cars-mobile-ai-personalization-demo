"""Couchbase Cars Vehicle Upgrade Agent - the second AOM agent identity in the demo.

It is triggered by **Confirm** on the upgrade screen: the phone writes a
`requests` document (`purchase_vehicle_upgrade`, `place_upgrade_offer` or
`apply_goodwill_upgrade`), and the worker hands any of those three tools to
this agent instead of the concierge. One upgrade = one AOM run, attributed
to the *Couchbase Cars Vehicle Upgrade Agent* on AOM's Agents, Traces and Audit
pages, scoped to the five upgrade tools only.

What makes it an agent rather than a tool call is **AOM Agent Memory**:

1. Before applying the upgrade it recalls what AOM already remembers about
   this customer's vehicles (`POST /v1/memory/search`): earlier upgrades,
   offers, and anything the customer told the concierge about rooms.
2. After the upgrade is applied it writes an episodic memory
   (`POST /v1/memory`) - from which category to which, vehicle, level,
   rental, what was paid or offer, and the occasion - plus a semantic
   preference memory when the booking shows one (vehicle preference, fuel type).

The concierge recalls the same memories on its next turn, so "can we upgrade
again next time?" is answered with what actually happened.
"""
from __future__ import annotations

import logging

from . import catalog as C, config, tool_gateway
from .aom_client import AOMError, upgrade_aom
from .store import store

log = logging.getLogger("cbcars.upgrade_agent")

AGENT_ID = "cbcars-upgrade-agent"
AGENT_NAME = "Couchbase Cars Vehicle Upgrade Agent"
TOOLS = ["get_customer_context", "get_upgrade_offers", "place_upgrade_offer", "purchase_vehicle_upgrade",
         "apply_goodwill_upgrade"]
# Tools the worker routes to this agent (the request documents a Confirm creates).
TRIGGER_TOOLS = {"place_upgrade_offer", "purchase_vehicle_upgrade", "apply_goodwill_upgrade"}
DESCRIPTION = ("Couchbase Cars vehicle upgrade agent. Triggered when a customer confirms an upgrade in the mobile "
               "app: recalls the customer's vehicle history and preferences from Agent Memory, applies the upgrade, "
               "offer or complimentary move as a governed tool call, and remembers the outcome for the concierge.")


def enabled() -> bool:
    return upgrade_aom.enabled


async def recall(customer_id: str) -> list[str]:
    if not enabled():
        return []
    try:
        res = await upgrade_aom.memory_search(customer_id, "vehicle upgrade offer luxury SUV vehicle preference", top_k=4)
        return [e.get("content", "") for e in res.get("entries", []) if e.get("content")]
    except AOMError as exc:
        log.info("memory search skipped: %s", exc)
        return []


def _episode(tool: str, profile: dict, before: dict, result: dict) -> str:
    r = profile.get("reservation") or {}
    item = result.get("item") or {}
    room = item.get("vehicle") or {}
    occasion = (profile.get("preferences") or {}).get("celebration")
    rental = f"{r.get('location_name')} ({r.get('trip_name')}, picking up {r.get('pickup_date')})"
    frm = f"{before.get('class_name')} {before.get('space_number')} on level {before.get('level')}"
    if tool == "place_upgrade_offer":
        offer = item.get("offer_pd")
        what = (f"placed a Couchbase Cars Upgrade offer of ${offer:,.0f}/day" if offer else "placed a Couchbase Cars Upgrade offer")
        if result.get("status") == "accepted":
            what += f" that was accepted: now in {room.get('class_name')} {room.get('space_number')}"
        else:
            cat = C.CLASS_BY_CODE.get(item.get("to_class") or "", {}).get("name", "a higher category")
            what += f" for {C.a_or_an(cat) if cat != 'a higher category' else cat} (pending the revenue team)"
    elif tool == "apply_goodwill_upgrade":
        what = (f"was moved to {room.get('class_name')} {room.get('space_number')} as a complimentary goodwill "
                f"upgrade approved by Customer Care")
    else:
        charge = result.get("charge_usd")
        what = (f"bought an instant upgrade to {room.get('class_name')} {room.get('space_number')} on level "
                f"{room.get('level')}" + (f" for ${charge:,.0f}" if charge else ""))
    txt = f"Vehicle upgrade: {what}, from {frm}, on {rental}"
    if occasion:
        txt += f", celebrating their {occasion}"
    return txt + "."


def _preference(profile: dict) -> str | None:
    prefs = profile.get("preferences") or {}
    bits = []
    if prefs.get("vehicle_pref"):
        bits.append(f"prefers a {prefs['vehicle_pref']} vehicle")
    if prefs.get("fuel_type") and prefs["fuel_type"] != "any":
        bits.append(f"fuel type: {prefs['fuel_type']}")
    if prefs.get("driving_needs"):
        bits.append("needs " + ", ".join(prefs["driving_needs"]))
    return ("Vehicle preferences: " + ", ".join(bits) + ".") if bits else None


async def run(doc: dict, args: dict, approval_id: str | None = None) -> dict:
    """Apply an upgrade request as the Vehicle Upgrade Agent. Returns the
    tool result plus `agent`, `memories_recalled` and `remembered`."""
    customer_id = doc.get("customer_id")
    tool = doc.get("tool")
    profile = await store.get("profiles", f"profile::{customer_id}") or {}
    before = dict((profile.get("reservation") or {}).get("vehicle") or {})

    memories = await recall(customer_id)
    result = await tool_gateway.invoke(tool, args, approval_id=approval_id, client=upgrade_aom if enabled() else None)
    result.update({"agent": AGENT_ID, "memories_recalled": len(memories), "remembered": False})

    if result.get("ok") and result.get("status") in ("ok", "confirmed", "accepted", "submitted") and enabled():
        try:
            after = await store.get("profiles", f"profile::{customer_id}") or profile
            await upgrade_aom.memory_add(
                customer_id, _episode(tool, after, before, result), session_id=doc.get("session_id"),
                memory_type="episodic",
                metadata={"agent": AGENT_ID, "tool": tool, "rental_id": (after.get("reservation") or {}).get("rental_id"),
                          "trace_id": result.get("trace_id"), "app": "cbcars-mobile"})
            pref = _preference(after)
            if pref and not any("Vehicle preferences:" in m for m in memories):
                await upgrade_aom.memory_add(customer_id, pref, memory_type="semantic",
                                             metadata={"agent": AGENT_ID, "app": "cbcars-mobile"})
            result["remembered"] = True
        except AOMError as exc:
            log.info("memory add skipped: %s", exc)
    if memories and result.get("summary"):
        last = next((m for m in memories if m.startswith("Vehicle upgrade:")), None)
        if last:
            result["summary"] += f" (The upgrade agent remembered: {last[len('Vehicle upgrade: '):].rstrip('.')}.)"
    return result
