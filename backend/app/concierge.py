"""Couchbase Cars Rental Concierge - the agent behind the app's Concierge tab.

One turn:

1. **Classify** the question into an intent, and decide whether it is
   *personal* (needs this customer's data) or a *playbook* question anyone
   could ask ("what's in Couchbase Cars Total Protection?").
2. **Playbook questions -> AOM RAG Application.** One call to
   `/v1/agent/rag/cbcars-rental-concierge/query`. The app is scoped to today's
   Customer Care Playbook document; AOM runs retrieval behind its Context
   Cache and generation behind its LLM Cache, and counts the query on its
   RAG Applications page. If the app isn't registered (or AOM predates RAG
   Applications) the question takes the personal path below without customer
   data.
3. **Personal questions -> Context Caching.** Look the context up in AOM's
   Context Cache (`/v1/context/get`, namespace
   `rag:cbcars-rental-concierge:customer-context`), then in the Couchbase
   `ctx::<customer>::<intent>` document. On a miss, assemble it: the customer's
   current Amazon Redshift profile (Redshift Data API: segment
   memberships, Redshift ML scores), AOM Knowledge Base retrieval scoped to
   this customer's profile document and to the playbook, plus live facts from
   the governed MCP tools (upgrade inventory, extras for their trip). It
   is stored in AOM (`/v1/context/set`, with the real build time - the Amazon Redshift
   round trip included) and in Couchbase, keyed by the unload date and the
   profile revision, so the next daily unload or any booking the customer makes
   invalidates it. The Couchbase copy carries the
   customer's channel, so Sync Gateway puts it on the phone too - which is what
   lets the app answer offline.
4. **Memory** - recall what this customer told the concierge before (AOM agent
   memory), live every turn.
5. **LLM Caching** - complete through AOM `/v1/llm/complete` in the
   `rag:cbcars-rental-concierge:personal` namespace (the `rag:<app>:` prefix is
   how AOM attributes the activity to the RAG application).
6. Suggest one-tap actions; the app turns a tap into an offline-first
   `requests` document.
"""
from __future__ import annotations

import logging
import re
import time
import uuid

from . import redshift
from . import catalog as C
from . import config, knowledge, metrics, rag_app, tool_gateway
from .aom_client import AOMError, aom, current_trace
from .docs import (STATE, chat_id, ctx_id, days_to_pickup, customer_channel, now_iso,
                   profile_id)
from .store import store

log = logging.getLogger("cbcars.concierge")

INTENTS = ["upgrade", "extra", "protection", "bundle", "service", "checkin", "trip", "service_recovery", "general"]
# Context-cache keys: personal context per intent, plus a playbook-only
# context per intent for generic questions (no customer data in it).
CONTEXT_KEYS = INTENTS + [f"playbook_{i}" for i in INTENTS]

KEYWORDS = {
    "service_recovery": ["smells", "smell", "dirty", "broken", "warning light", "complain", "disappointed", "upset", "terrible", "awful",
                         "not working", "problem with my car", "problem with our car", "scratched", "damaged", "wrong car", "check engine"],
    "upgrade": ["upgrade", "luxury", "couchbase cars upgrade", "upgrade offer", "standby", "bigger car", "bigger vehicle", "suv", "premium",
                "convertible", "car class", "nicer car"],
    "extra": ["extra", "extras", "child seat", "car seat", "booster", "gps", "navigation", "roof box", "ski rack", "bike rack",
              "additional driver", "parks pass", "equipment", "add-on", "cooler", "beach kit", "things to add"],
    "protection": ["protection", "insurance", "ldw", "damage waiver", "coverage", "cover", "liability", "deductible", "roadside",
                   "safetynet", "accident"],
    "bundle": ["fuel", "gas", "prepaid", "wifi", "wi-fi", "internet", "hotspot", "toll", "tolls", "e-toll", "total protection",
               "peace of mind", "bundle"],
    "service": ["service", "deliver", "delivery", "collect", "collection", "late return", "swap", "refuel", "car wash", "charging"],
    "checkin": ["check-in", "check in", "checkin", "pickup time", "pickup window", "skip the counter", "counter", "rental agreement",
                "license", "documents", "exit booth"],
    "trip": ["trip", "itinerary", "route", "schedule", "what day", "which day", "when do we", "stops", "my rental", "my trip",
             "where are we", "return date", "drop off", "drop-off"],
}
PERSONAL_RE = re.compile(r"\b(i|i'm|im|me|my|mine|we|we're|our|us)\b", re.I)
PERSONAL_INTENTS = {"upgrade", "trip", "service_recovery"}

# Canonical retrieval query per intent: the cached context is per intent, so
# it is retrieved with a stable query rather than the wording of whichever
# question happened to miss the cache first.
INTENT_QUERY = {
    "upgrade": "car class upgrade Couchbase Cars Upgrade standby offer premium luxury perks",
    "extra": "extras equipment child seat GPS roof box parks pass trip stops interests",
    "protection": "protection plans LDW liability roadside coverage drivers",
    "bundle": "bundles prepaid fuel e-Toll Wi-Fi hotspot Couchbase Cars Total Protection Peace of Mind",
    "service": "Couchbase Cars Services hotel delivery collection refuel swap mid-rental",
    "checkin": "Skip the Counter mobile check-in pickup window rental agreement license exit booth",
    "trip": "trip plan stops days rental schedule pickup return",
    "service_recovery": "vehicle issue service recovery goodwill upgrade",
    "general": "frequently asked questions policy",
}

PERSONA = ("You are the Couchbase Cars Rental Concierge in the customer's mobile app. Be warm, concise (under 120 words) "
           "and specific. Use only the facts in CONTEXT. Never invent prices, availability or bookings. Never say a "
           "booking is done - the customer confirms actions with the buttons shown under your reply.")


def classify(message: str) -> tuple[str, bool]:
    m = message.lower()
    scores = {i: sum(1 for k in kws if k in m) for i, kws in KEYWORDS.items()}
    intent = max(scores, key=scores.get)
    if scores[intent] == 0:
        intent = "general"
    personal = bool(PERSONAL_RE.search(message)) or intent in PERSONAL_INTENTS
    if intent == "general" and not personal:
        return "general", False
    # A product/policy question phrased generically ("how does Couchbase Cars Upgrade work?")
    # stays on the shared playbook path even though its intent is personal-capable.
    if not PERSONAL_RE.search(message) and re.match(r"\s*(how|what|is|are|can|do|does|who)\b", m) and intent not in ("service_recovery",):
        return intent, False
    return intent, True


def _norm(q: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", q.lower()).strip()


async def kb_doc_id(key: str) -> str | None:
    doc = await store.get("lookups", f"kbdoc::{key}")
    return doc.get("document_id") if doc else None


# --------------------------------------------------------------------------
# Context cache
# --------------------------------------------------------------------------
async def invalidate_context(customer_id: str):
    for key in CONTEXT_KEYS:
        await store.remove("context_cache", ctx_id(customer_id, key))


async def _kb(query: str, document_id: str | None, top_k=3) -> tuple[list[dict], str]:
    if not (aom.enabled and document_id):
        return [], "unavailable"
    try:
        res = await aom.knowledge_search(query, top_k=top_k, document_id=document_id)
        return [{"title": r.get("document_title"), "content": r.get("content"), "score": round(r.get("score") or 0, 3),
                 "document_id": r.get("document_id"), "source": "aom-kb"} for r in res.get("results", [])], "aom"
    except AOMError as exc:
        log.warning("KB search failed: %s", exc)
        return [], "error"


def _local_profile_chunks(profile: dict, intent: str) -> list[dict]:
    md = knowledge.customer_profile_markdown(profile)
    sections = md.split("\n## ")
    want = {"upgrade": ["Upcoming", "Personalization", "Loyalty"], "extra": ["Upcoming", "Preferences"],
            "protection": ["Preferences", "Personalization"], "bundle": ["Personalization", "Loyalty"],
            "service": ["Preferences", "Personalization"], "checkin": ["Upcoming"], "trip": ["Upcoming"],
            "service_recovery": ["Upcoming", "Loyalty"], "general": ["Upcoming"]}[intent]
    out = []
    for s in sections:
        if any(s.startswith(w) for w in want):
            out.append({"title": f"Customer profile {profile['customer_id']}", "content": s[:1200], "score": None,
                        "document_id": None, "source": "local-export"})
    return out


def _local_playbook_chunks(query: str) -> list[dict]:
    q = query.lower()
    scored = []
    for f in knowledge.FAQ:
        s = sum(1 for k in f["keywords"] if k in q)
        if s:
            scored.append((s, f))
    scored.sort(key=lambda x: -x[0])
    return [{"title": "Customer Care Playbook", "content": f"{f['q']} {f['a']}", "answer": f["a"], "score": None,
             "document_id": None, "source": "local-playbook"} for _, f in scored[:3]]


async def _facts(customer_id: str, intent: str) -> dict:
    tool = {"upgrade": "get_upgrade_offers", "service_recovery": "get_upgrade_offers",
            "extra": "search_rental_extras"}.get(intent, "get_customer_context")
    res = await tool_gateway.invoke(tool, {"customer_id": customer_id})
    data = res.get("data", res)
    return {"tool": tool, "governed": res.get("governed", False), "trace_id": res.get("trace_id"), "data": data}


def _aom_context_key(customer_id: str, cache_key: str, profile: dict, personal: bool) -> str:
    """Key in AOM's Context Cache. The unload date and (for personal context)
    the profile revision are part of the key, so a new daily unload or any
    booking makes the old entry unreachable at once. Playbook context holds
    no customer data, so every customer shares one entry per intent."""
    if personal:
        return f"{customer_id}:{cache_key}:{profile.get('export_date')}:r{profile.get('rev', 0)}"
    return f"{cache_key}:{profile.get('export_date')}"


def _local_valid(doc: dict | None, profile: dict, personal: bool) -> bool:
    return bool(doc and doc.get("export_date") == profile.get("export_date")
                and (not personal or doc.get("profile_rev") == profile.get("rev", 0)))


async def get_context(customer_id: str, intent: str, profile: dict, personal: bool = True) -> dict:
    """Context Caching, with AOM's Context Cache in front of the assembly.

    1. AOM `/v1/context/get` in the `rag:<app>:customer-context` namespace, so
       hit rate and latency avoided show on AOM's Context Cache and RAG
       Applications pages.
    2. On a miss (or with AOM unreachable), the Couchbase `context_cache`
       document, if it was built from today's unload and the current profile.
    3. Otherwise assemble: the customer's current Amazon Redshift profile view
       (segments, scores), KB retrieval scoped to this customer's profile
       document and the playbook, plus live facts from the governed MCP
       tools. The result goes to AOM (`/v1/context/set` with the real build
       time as `source_latency_ms`) and to Couchbase, where the customer's
       channel puts it on the phone for offline answers.
    """
    cache_key = intent if personal else f"playbook_{intent}"
    key = ctx_id(customer_id, cache_key)
    aom_key = _aom_context_key(customer_id, cache_key, profile, personal)
    t0 = time.perf_counter()
    aom_status = "off"
    if aom.enabled:
        try:
            res = await aom.context_get(aom_key, config.CONTEXT_NAMESPACE)
            aom_status = (res.get("cache") or {}).get("status") or ("hit" if res.get("hit") else "miss")
            value = res.get("value")
            if res.get("hit") and isinstance(value, dict):
                # A shared playbook entry may have been stored by another customer's
                # turn: re-home it to this customer before it syncs to their phone.
                doc = dict(value, customer_id=customer_id, channels=[customer_channel(customer_id)])
                local = await store.get("context_cache", key)
                if not _local_valid(local, profile, personal):
                    # Keep the phone's copy current for offline answers.
                    await store.upsert("context_cache", key, doc, ttl=config.CONTEXT_CACHE_TTL_SECONDS)
                doc["_cache"] = {"status": "hit", "source": "aom", "namespace": config.CONTEXT_NAMESPACE,
                                 "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
                return doc
        except AOMError as exc:
            aom_status = "error"
            log.info("AOM context get failed: %s", exc)

    cached = await store.get("context_cache", key)
    if _local_valid(cached, profile, personal):
        cached["_cache"] = {"status": "hit", "source": "couchbase", "aom": aom_status,
                            "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
        if aom_status == "miss":
            await _aom_context_set(aom_key, cached, cached.get("build_ms"))
        return cached

    query = INTENT_QUERY[intent]
    customer_doc = await kb_doc_id(customer_id) if personal else None
    playbook_doc = await kb_doc_id("playbook")
    kb_profile, kb_mode = ([], "skipped")
    if personal and intent != "general":
        kb_profile, kb_mode = await _kb(query, customer_doc)
        if not kb_profile:
            kb_profile = _local_profile_chunks(profile, intent)
    kb_playbook, pb_mode = await _kb(query, playbook_doc)
    if not kb_playbook:
        kb_playbook = _local_playbook_chunks(query + " " + intent)
    if kb_mode == "skipped":
        kb_mode = pb_mode
    facts = await _facts(customer_id, intent) if personal and intent != "general" else {}
    # The customer's *current* profile from Amazon Redshift: segments and
    # scores as of now, not as of this morning's unload.
    cust360 = await redshift.profile_view(customer_id, profile) if personal else None
    build_ms = round((time.perf_counter() - t0) * 1000, 1)
    doc = {
        "type": "context_cache", "customer_id": customer_id, "intent": intent, "personal": personal, "query": query,
        "export_date": profile.get("export_date"), "profile_rev": profile.get("rev", 0),
        "built_at": now_iso(), "build_ms": build_ms, "kb_mode": kb_mode,
        "kb_profile": kb_profile, "kb_playbook": kb_playbook, "facts": facts, "redshift": cust360,
        "customer_document_id": customer_doc, "playbook_document_id": playbook_doc,
        "aom_key": aom_key, "channels": [customer_channel(customer_id)],
    }
    await store.upsert("context_cache", key, doc, ttl=config.CONTEXT_CACHE_TTL_SECONDS)
    await _aom_context_set(aom_key, doc, build_ms)
    doc = dict(doc)
    doc["_cache"] = {"status": "miss", "source": "built", "aom": aom_status, "latency_ms": build_ms}
    return doc


async def _aom_context_set(aom_key: str, doc: dict, build_ms) -> None:
    if not aom.enabled:
        return
    value = {k: v for k, v in doc.items() if not k.startswith("_")}
    if not value.get("personal"):
        if value.get("kb_profile") or value.get("facts") or value.get("redshift"):
            return  # never share customer data across customers
        for k in ("customer_id", "channels", "customer_document_id"):
            value.pop(k, None)
    try:
        await aom.context_set(aom_key, value, config.CONTEXT_NAMESPACE, ttl_seconds=config.CONTEXT_CACHE_TTL_SECONDS,
                              source_latency_ms=int(build_ms or 0))
    except AOMError as exc:
        # 409 = context caching switched off in AOM's policy, 413 = over its size limit.
        log.info("AOM context set skipped: %s", exc)


# --------------------------------------------------------------------------
# Answer composition
# --------------------------------------------------------------------------
def _customer_summary(p: dict) -> str:
    r = p["reservation"]
    v = r["vehicle"]
    return (f"{p['first_name']} {p['last_name']}, Couchbase Cars Preferred {p['loyalty']['tier']}. Picking up at {r['location_name']} "
            f"({r['trip_name']}) on {r['pickup_date']}, {days_to_pickup(p)} days away, returning {r['return_date']}. "
            f"Party of {r['party_size']}. Vehicle: {v['class_name']} ({v.get('example', '')}), space {v['space_number']}. "
            f"Check-in: {r['checkin_status']}. Celebrating: "
            f"{p['preferences'].get('celebration') or 'n/a'}. Interests: {', '.join(p['preferences']['interests'])}. "
            f"Driving needs: {', '.join(p['preferences'].get('driving_needs') or []) or 'none'}.")


def _facts_text(facts: dict) -> str:
    d = facts.get("data") or {}
    if facts.get("tool") == "get_upgrade_offers":
        rows = [f"{o['class_name']} ({o['class_code']}, {o.get('example', '')}): {o['available']} left, instant ${o['instant_price_pd']}"
                f"/day (total ${o['instant_total_usd']:,}), Couchbase Cars Upgrade min offer ${o['upgrade_offer_min_pd']}/day"
                + (f", suggested offer ${o['recommended_offer_pd']}" if o.get("recommended_offer_pd") else "")
                for o in d.get("offers", [])]
        return "Upgrade options: " + "; ".join(rows)
    if facts.get("tool") == "search_rental_extras":
        rows = [f"{e['name']} ({e['id']}) at {e['location_name']}, ${e['price']}/{e['per']} (${e['total_usd']} for the rental)"
                + (f", matches {', '.join(e['matched_interests'])}" if e.get("matched_interests") else "")
                for e in d.get("extras", [])[:6]]
        return "Extras for this rental: " + "; ".join(rows)
    if d:
        return f"Customer context: next best action {d.get('next_best_action')}, purchased {d.get('purchased')}."
    return ""


def build_prompt(message: str, personal: bool, ctx: dict, profile: dict, memories: list[str]) -> str:
    parts = [PERSONA, "", "CONTEXT:"]
    if personal:
        parts.append("Customer: " + _customer_summary(profile))
        for c in ctx.get("kb_profile", [])[:3]:
            parts.append("Profile note: " + (c.get("content") or "")[:900])
        ft = _facts_text(ctx.get("facts") or {})
        if ft:
            parts.append(ft)
        if ctx.get("redshift"):
            parts.append("Amazon Redshift segments: " + redshift.audiences_text(ctx["redshift"]) + ".")
        for m in memories[:3]:
            parts.append("Earlier the customer said: " + m[:300])
    for c in ctx.get("kb_playbook", [])[:3]:
        parts.append("Playbook: " + (c.get("content") or "")[:900])
    parts += ["", f"CUSTOMER QUESTION: {message.strip()}", "", "ANSWER:"]
    return "\n".join(parts)


def protection_pick(profile: dict) -> dict | None:
    """The protection plan the concierge suggests: offered at this customer's
    location, not already added or bundled, celebration-grade when they're
    celebrating, else family-grade for families, else the essentials."""
    r = profile["reservation"]
    owned = profile.get("purchased_for_rental", {})
    bundled = {"LDW", "PAI", "PEC", "RSN"} if ("PEACE" in owned.get("bundles", []) or "TOTAL" in owned.get("bundles", [])) else set()
    options = [d for d in C.PROTECTION if C.location_has_protection(r["location_code"], d["id"])
               and d["id"] not in owned.get("protection", []) and d["id"] not in bundled]
    if not options:
        return None
    want = "celebration" if profile["preferences"].get("celebration") else ("family" if r["party_size"] > 2 else "essential")
    return next((d for d in options if want in d["tags"]), options[0])


def compose_fallback(intent: str, personal: bool, message: str, ctx: dict, profile: dict) -> str:
    """Deterministic answer from the same context - used when AOM has no LLM
    provider key (it returns a labelled stub) or AOM is not configured."""
    r = profile["reservation"]
    d = (ctx.get("facts") or {}).get("data") or {}
    first = profile["first_name"]
    if not personal or intent == "general":
        # Answer the question actually asked from the FAQ when it matches;
        # otherwise the best retrieved playbook chunk.
        pb = _local_playbook_chunks(message) or ctx.get("kb_playbook")
        if pb:
            return pb[0].get("answer") or pb[0]["content"]
        return "I can help with upgrades, extras, protection, bundles, services and check-in for your rental."
    if intent in ("upgrade", "service_recovery"):
        offers = d.get("offers", [])
        rec = next((o for o in offers if o.get("recommended")), offers[0] if offers else None)
        if intent == "service_recovery":
            return (f"I'm so sorry, {first} - that's not the experience we want for you. I can ask a Customer Care "
                    f"supervisor to approve a complimentary move"
                    + (f" to {C.a_or_an(rec['class_name'])}" if rec else "") + ". Tap below to send the request; "
                    "you'll see their decision right here.")
        if not rec:
            return f"You're already in our top available class at {r['location_name']}, {first}."
        cel = profile["preferences"].get("celebration")
        left = (f"there's only 1 {rec['class_name']} ({rec.get('example', '')}) left" if rec["available"] == 1
                else f"there are {rec['available']} {rec['class_name']} cars ({rec.get('example', '')}) left")
        return (f"Great news, {first} - {left} at {r['location_name']} for your pickup day"
                + (f", perfect for your {cel}" if cel else "") + f". You can make a Couchbase Cars Upgrade standby offer from "
                f"${rec['upgrade_offer_min_pd']}/day (we'd suggest "
                f"${rec.get('recommended_offer_pd') or rec['upgrade_offer_min_pd']}) or upgrade instantly for "
                f"${rec['instant_price_pd']}/day (${rec['instant_total_usd']:,} for your {r['days']}-day rental).")
    if intent == "extra":
        ex = d.get("extras", [])[:3]
        if not ex:
            return f"Your car is ready to go as booked, {first} - nothing else to add for this trip."
        lines = "; ".join(f"{e['name']} (${e['price']}/{e['per']})" for e in ex)
        return f"Based on your trip and what you love, {first}, here are my top picks: {lines}."
    if intent == "checkin":
        if r["checkin_status"] == "complete":
            return f"You're all checked in, {first}! Pickup window {r.get('pickup_slot')} on {r['pickup_date']} - go straight to your space."
        return (f"You haven't checked in yet, {first}. It takes about 2 minutes - pick a pickup window for "
                f"{r['pickup_date']} and your mobile rental agreement will be ready, so you can skip the counter.")
    if intent == "trip":
        stops = ", ".join(f"{p['date'][5:]} {p['stop'].split(',')[0]}" for p in r["stops"])
        return f"Here's your {r['trip_name']} from {r['location_name']}: {stops}."
    if intent == "protection":
        cel = profile["preferences"].get("celebration")
        pick = protection_pick(profile)
        if not pick:
            return f"You're fully covered for this rental, {first} - every plan {r['location_name']} offers is already on it."
        return (f"For your {r['location_name']} rental, I'd suggest {pick['name']}" + (f" for your {cel}" if cel else "")
                + f" - it covers {pick['covers'].lower()}. Pick the drivers and term and I'll add it.")
    if intent == "service":
        return "Hotel delivery, collection, mobile refuel and vehicle swaps are 20% off on mid-rental days - we come to you."
    if intent == "bundle":
        return "Based on your past rentals, a bundle could save you money - see the options below."
    return "Here's what I found for your rental."


def suggest_actions(intent: str, ctx: dict, profile: dict, message: str) -> list[dict]:
    d = (ctx.get("facts") or {}).get("data") or {}
    r = profile["reservation"]
    acts: list[dict] = []
    if intent == "upgrade":
        offers = d.get("offers", [])
        rec = next((o for o in offers if o.get("recommended")), offers[0] if offers else None)
        if rec and rec["available"] > 0:
            offer = rec.get("recommended_offer_pd") or rec["upgrade_offer_min_pd"]
            acts.append({"label": f"Offer ${offer}/day · {rec['class_name']}", "tool": "place_upgrade_offer",
                         "args": {"class_code": rec["class_code"], "offer_per_day_usd": offer}})
            acts.append({"label": f"Upgrade now · ${rec['instant_total_usd']:,}", "tool": "purchase_vehicle_upgrade",
                         "args": {"class_code": rec["class_code"]}})
    elif intent == "service_recovery":
        offers = [o for o in d.get("offers", []) if o.get("available", 0) > 0]
        pick = next((o for o in offers if o.get("recommended")), offers[0] if offers else None)
        if pick:
            acts.append({"label": f"Request complimentary {pick['class_name']}", "tool": "apply_goodwill_upgrade",
                         "args": {"class_code": pick["class_code"],
                                  "reason": f"Customer-reported issue via concierge: {message.strip()[:200]}"}})
    elif intent == "extra":
        for e in d.get("extras", [])[:2]:
            if not e.get("already_booked"):
                acts.append({"label": f"Add {e['name']} · ${e['total_usd']:,}", "tool": "add_rental_extra",
                             "args": {"extra_id": e["id"]}})
    elif intent == "protection":
        pick = protection_pick(profile)
        acts.append({"label": f"Add {pick['name'].split(' (')[0]}" if pick else "Add protection", "screen": "protection",
                     "args": {"plan_id": pick["id"]} if pick else {}})
    elif intent == "service":
        acts.append({"label": "Book a service", "screen": "service"})
    elif intent == "checkin" and r["checkin_status"] != "complete":
        acts.append({"label": "Check in now", "screen": "checkin"})
    elif intent == "bundle":
        owned = profile.get("purchased_for_rental", {}).get("bundles", [])
        s = profile["ml_scores"]
        ranked = sorted([p for p in C.BUNDLES if p["code"] not in owned], key=lambda p: -s.get(p["propensity"], 0))
        for p in ranked[:2]:
            acts.append({"label": f"Add {p['name']}", "tool": "add_bundle", "args": {"bundle_code": p["code"]}})
    return acts


# Only durable things the customer says about themselves become memories
# ("we need a child seat", "my wife prefers an SUV"). Plain questions don't, which
# also keeps repeat questions' prompts stable for the LLM cache.
STATEMENT_RE = re.compile(r"\b(i|we)('m|'re| am| are| love| like| prefer| hate| don't| do not| want| need| always| never)\b"
                          r"|\bmy (wife|husband|partner|kids?|son|daughter|mom|dad|family)\b|\ballerg", re.I)


async def _remember(customer_id: str, message: str, reply: str, intent: str, session_id: str):
    if not aom.enabled or not STATEMENT_RE.search(message):
        return
    try:
        await aom.memory_add(customer_id, f"Customer said ({intent}): {message.strip()[:500]}", session_id=session_id,
                             metadata={"intent": intent, "app": "cbcars-mobile"})
    except AOMError as exc:
        log.info("memory add skipped: %s", exc)


async def _recall(customer_id: str, message: str) -> list[str]:
    if not aom.enabled:
        return []
    try:
        res = await aom.memory_search(customer_id, message, top_k=3)
        return [e.get("content", "") for e in res.get("entries", []) if e.get("content")]
    except AOMError:
        return []


async def _ask_rag_app(message: str, intent: str, profile: dict) -> dict | None:
    """Playbook questions go to the concierge's AOM RAG Application: one call
    that runs AOM's Context Cache (retrieval), the KB search scoped to today's
    playbook, and the LLM Cache, and is counted on the RAG Applications page."""
    if not rag_app.usable():
        return None
    l0 = time.perf_counter()
    try:
        res = await aom.rag_query(config.RAG_APP_ID, message)
    except AOMError as exc:
        rag_app.query_failed(exc)
        log.info("RAG app query failed, answering on the concierge's own path: %s", exc)
        return None
    ms = round((time.perf_counter() - l0) * 1000, 1)
    retrieval = res.get("retrieval") or {}
    llm_res = res.get("llm") or {}
    cache = llm_res.get("cache") or {}
    srcs = res.get("sources") or []
    chunks = [{"title": c.get("document_title"), "content": c.get("preview"), "source": "aom-rag"} for c in srcs]
    reply = (res.get("answer") or "").strip()
    llm = {"status": cache.get("status", "skipped" if not res.get("llm") else "miss"), "similarity": cache.get("similarity"),
           "namespace": f"rag:{config.RAG_APP_ID}", "provider": llm_res.get("provider"), "model": llm_res.get("model"),
           "latency_ms": ms, "stub": bool(llm_res.get("stub")), "tokens_saved": llm_res.get("tokens_saved") or 0,
           "cost_saved_usd": llm_res.get("cost_saved_usd") or 0, "rag_app": config.RAG_APP_ID}
    if not res.get("llm") or llm["stub"] or not reply:
        # No LLM provider key in AOM (stub) or nothing retrieved: answer from
        # the same playbook deterministically.
        reply = compose_fallback(intent, False, message, {"kb_playbook": chunks}, profile)
        llm["composed_locally"] = True
    return {
        "reply": reply, "llm": llm,
        "sources": [{"title": c["title"], "snippet": (c.get("content") or "")[:160], "kind": "aom-rag"} for c in chunks[:3]],
        "context": {"status": retrieval.get("cache", "miss"), "latency_ms": retrieval.get("latency_ms", 0),
                    "source": "aom-rag", "rag_app": config.RAG_APP_ID, "chunks": retrieval.get("chunks"),
                    "export_date": profile.get("export_date"), "kb_mode": "aom"},
        "trace_id": (res.get("trace") or {}).get("trace_id"),
    }


async def ask(customer_id: str, message: str, session_id: str | None = None) -> dict:
    session_id = session_id or f"app-{customer_id}"
    trace_id = uuid.uuid4().hex
    token = current_trace.set({"trace_id": trace_id, "session_id": session_id})
    t0 = time.perf_counter()
    try:
        profile = await store.get("profiles", profile_id(customer_id))
        if not profile:
            raise ValueError("unknown customer")
        intent, personal = classify(message)
        if not personal:
            via_rag = await _ask_rag_app(message, intent, profile)
            if via_rag:
                result = {
                    "reply": via_rag["reply"], "intent": intent, "personal": False, "actions": [],
                    "sources": via_rag["sources"], "context": via_rag["context"], "memory_recalled": 0,
                    "llm": via_rag["llm"], "trace_id": via_rag["trace_id"] or trace_id, "governed": True,
                    "total_ms": round((time.perf_counter() - t0) * 1000, 1), "export_date": STATE.get("export_date"),
                }
                metrics.concierge(result)
                await _append_chat(customer_id, message, result)
                return result
        ctx = await get_context(customer_id, intent, profile, personal)
        memories = await _recall(customer_id, message) if personal else []
        prompt = build_prompt(message, personal, ctx, profile, memories)
        namespace = config.LLM_NAMESPACE_PERSONAL if personal else config.LLM_NAMESPACE_PLAYBOOK
        llm = {"status": "local", "namespace": namespace, "provider": None, "model": None, "similarity": None,
               "latency_ms": None, "stub": False, "tokens_saved": 0}
        reply = None
        if aom.enabled:
            try:
                l0 = time.perf_counter()
                res = await aom.complete(prompt, namespace=namespace)
                cache = res.get("cache") or {}
                llm.update({"status": cache.get("status", "miss"), "similarity": cache.get("similarity"),
                            "provider": res.get("provider"), "model": res.get("model"),
                            "latency_ms": round((time.perf_counter() - l0) * 1000, 1), "stub": bool(res.get("stub")),
                            "tokens_saved": res.get("tokens_saved", 0), "cost_saved_usd": res.get("cost_saved_usd", 0)})
                if not res.get("stub") and (res.get("response") or "").strip():
                    reply = res["response"].strip()
            except AOMError as exc:
                llm["status"] = "error"
                llm["error"] = str(exc)[:200]
        if not reply:
            reply = compose_fallback(intent, personal, message, ctx, profile)
            llm["composed_locally"] = True
        actions = suggest_actions(intent, ctx, profile, message) if personal else []
        sources = ([{"title": c["title"], "snippet": (c.get("content") or "")[:160], "kind": c.get("source")}
                    for c in (ctx.get("kb_profile", []) if personal else [])[:2]]
                   + [{"title": c["title"], "snippet": (c.get("content") or "")[:160], "kind": c.get("source")}
                      for c in ctx.get("kb_playbook", [])[:2]])
        result = {
            "reply": reply, "intent": intent, "personal": personal, "actions": actions, "sources": sources,
            "context": {"status": ctx["_cache"]["status"], "latency_ms": ctx["_cache"]["latency_ms"],
                        "source": ctx["_cache"].get("source"),
                        "built_at": ctx.get("built_at"), "build_ms": ctx.get("build_ms"), "kb_mode": ctx.get("kb_mode"),
                        "export_date": ctx.get("export_date"),
                        "redshift": ({"mode": ctx["redshift"].get("mode"), "latency_ms": ctx["redshift"].get("latency_ms"),
                                   "segments": [m["name"] for m in ctx["redshift"].get("segments", [])]}
                                  if ctx.get("redshift") else None)},
            "memory_recalled": len(memories), "llm": llm, "trace_id": trace_id if aom.enabled else None,
            "governed": aom.enabled, "total_ms": round((time.perf_counter() - t0) * 1000, 1),
            "export_date": STATE.get("export_date"),
        }
        metrics.concierge(result)
        await _append_chat(customer_id, message, result)
        await _remember(customer_id, message, reply, intent, session_id)
        return result
    finally:
        current_trace.reset(token)


async def _append_chat(customer_id: str, message: str, result: dict):
    doc = await store.get("concierge", chat_id(customer_id)) or {
        "type": "concierge", "customer_id": customer_id, "messages": [], "answers": {}, "channels": [customer_channel(customer_id)]}
    now = now_iso()
    doc["messages"] = (doc["messages"] + [
        {"id": uuid.uuid4().hex[:12], "role": "customer", "text": message, "at": now},
        {"id": uuid.uuid4().hex[:12], "role": "concierge", "text": result["reply"], "at": now,
         "intent": result["intent"], "actions": result["actions"], "context": result["context"], "llm": result["llm"],
         "sources": result["sources"]},
    ])[-40:]
    # Answer cache the phone can reuse offline for the same (normalized) question.
    doc["answers"][_norm(message)[:120]] = {"reply": result["reply"], "intent": result["intent"], "at": now}
    if len(doc["answers"]) > 60:
        doc["answers"] = dict(list(doc["answers"].items())[-60:])
    doc["updated_at"] = now
    await store.upsert("concierge", chat_id(customer_id), doc)
