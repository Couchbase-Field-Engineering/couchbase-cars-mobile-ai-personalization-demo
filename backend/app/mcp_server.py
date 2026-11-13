"""`cbcars-customer-care` - the MCP server registered with AOM.

Streamable HTTP at /cbcars/mcp/. AOM ingests these tool definitions into its
vetted catalog (embeddings for discovery, RBAC per role, drift detection)
and is the only caller the demo expects: the app and concierge reach these
tools through `POST /v1/tools/invoke`, never directly.

Business errors (sold out, bad date) come back as `{"ok": false, ...}`
results rather than MCP errors, so AOM records a completed call and the
customer gets a useful message instead of a gateway failure.
"""
from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from . import actions

log = logging.getLogger("cbcars.mcp")

mcp = FastMCP(
    "cbcars-customer-care",
    instructions=("Couchbase Cars customer care for a customer's upcoming rental: vehicle upgrades (Couchbase Cars Upgrade offers, "
                  "instant and goodwill upgrades), extras, protection, bundles, service and mobile check-in."),
    stateless_http=True,
    # Called by AOM over the Docker host gateway, so the Host header is not
    # localhost; same reasoning as AOM's own bundled sample servers.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


async def _run(fn, **kw) -> dict:
    try:
        res = await fn(**kw)
    except actions.ToolError as exc:
        return {"ok": False, "status": "failed", "summary": str(exc)}
    return res if isinstance(res, dict) and "ok" in res else {"ok": True, "status": "ok", "data": res}


@mcp.tool()
async def get_customer_context(customer_id: str) -> dict:
    """Read a rental customer's upcoming rental, vehicle, party, loyalty tier, preferences and personalization segment."""
    return await _run(actions.get_customer_context, customer_id=customer_id)


@mcp.tool()
async def get_upgrade_offers(customer_id: str) -> dict:
    """List vehicle upgrade options for a customer's rental: car classes above theirs, unreserved inventory at the pickup location, instant upgrade price and Couchbase Cars Upgrade minimum standby offer."""
    return await _run(actions.get_upgrade_offers, customer_id=customer_id)


@mcp.tool()
async def place_upgrade_offer(customer_id: str, class_code: str, offer_per_day_usd: float) -> dict:
    """Place a Couchbase Cars Upgrade standby offer (per day, USD) to move a customer to a higher car class (CCAR, ICAR, FCAR, SFAR, PCAR, LCAR). Charged only if a car is on the lot at pickup."""
    return await _run(actions.place_upgrade_offer, customer_id=customer_id, class_code=class_code,
                      offer_per_day_usd=offer_per_day_usd)


@mcp.tool()
async def purchase_vehicle_upgrade(customer_id: str, class_code: str) -> dict:
    """Instantly purchase a paid upgrade to a higher car class for the whole reservation and reassign the vehicle and space."""
    return await _run(actions.purchase_vehicle_upgrade, customer_id=customer_id, class_code=class_code)


@mcp.tool()
async def apply_goodwill_upgrade(customer_id: str, class_code: str, reason: str) -> dict:
    """Apply a complimentary (no-charge) goodwill vehicle upgrade as a customer-recovery gesture. Requires a reason; held for supervisor approval."""
    return await _run(actions.apply_goodwill_upgrade, customer_id=customer_id, class_code=class_code, reason=reason)


@mcp.tool()
async def search_rental_extras(customer_id: str, category: str = "", interest: str = "") -> dict:
    """Find extras and equipment for a customer's rental (child seats, GPS, roof box, parks pass...), ranked by their interests and the stops on their trip."""
    return await _run(actions.search_rental_extras, customer_id=customer_id, category=category, interest=interest)


@mcp.tool()
async def add_rental_extra(customer_id: str, extra_id: str, quantity: int = 1) -> dict:
    """Add an extra to a customer's rental (quantity defaults to 1; child seats are installed before pickup)."""
    return await _run(actions.add_rental_extra, customer_id=customer_id, extra_id=extra_id, quantity=quantity)


@mcp.tool()
async def select_protection_plan(customer_id: str, plan_id: str, term: str = "whole rental", drivers: int = 0) -> dict:
    """Add a protection plan (LDW, PAI, PEC, ALI, RSN, TWP, EVP, ZERO) to a customer's rental for a term (whole rental, pickup day only, first 3 days) and a number of covered drivers (defaults to all adults)."""
    return await _run(actions.select_protection_plan, customer_id=customer_id, plan_id=plan_id, term=term, drivers=drivers)


@mcp.tool()
async def add_bundle(customer_id: str, bundle_code: str) -> dict:
    """Add a bundle to the rental: PEACE (Peace of Mind), ETOLL (e-Toll Unlimited), WIFI (hotspot), TOTAL (Total Protection) or FUEL (prepaid fuel)."""
    return await _run(actions.add_bundle, customer_id=customer_id, bundle_code=bundle_code)


@mcp.tool()
async def book_rental_service(customer_id: str, service_id: str, date: str, time: str = "10:00") -> dict:
    """Book a Couchbase Cars service (hotel delivery or collection, mobile refuel, EV charging, vehicle swap, late return) on a day of the rental. Mid-rental days are discounted."""
    return await _run(actions.book_rental_service, customer_id=customer_id, service_id=service_id, date=date, time=time)


@mcp.tool()
async def complete_mobile_checkin(customer_id: str, pickup_slot: str) -> dict:
    """Complete Skip the Counter check-in for a customer's reservation and choose a pickup window to get the mobile rental agreement and skip the counter."""
    return await _run(actions.complete_mobile_checkin, customer_id=customer_id, pickup_slot=pickup_slot)
