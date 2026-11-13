"""Fleet chatbot workload - a demo of AOM's LLM Cache and Context Cache under
a realistic Couchbase Cars rental-concierge load.

`POST /api/demo/workload` (or scripts/run_chatbot_workload.py) plays a crowd
of customers from every airport location in the fleet against the concierge,
exactly the way the mobile app does: each customer gets a session, asks the
things a renter asks before and during a rental, and every turn runs the real
concierge path - AOM RAG Application for playbook questions, AOM Context
Cache + Knowledge Base + governed MCP tools for personal ones, AOM Agent
Memory for what the customer says about themselves, and AOM `/v1/llm/complete`
in the `rag:cbcars-rental-concierge:*` namespaces for generation. Nothing is
stubbed here; the point is to make AOM's LLM Cache, Context Cache, RAG
Applications and Traces pages fill up with a workload that looks like
production.

How the traffic is shaped (what makes the caches hit the way they would in
production):

* **Playbook questions** (bundles, check-in, tolls, fuel, ...) are drawn
  Zipf-style from USE_CASES, so a few questions dominate - as in a real
  support queue. Most customers use the canonical wording (exact hits once
  the first customer has paid for the answer), a minority reword it (semantic
  hits), and the long tail misses.
* **Personal questions** build a per-customer, per-intent context once
  (`Context cache: built`) and the follow-up in the same intent reuses it
  (`hit`). Asking the very same thing again in a session is an exact LLM hit;
  a reworded follow-up shares the context but needs a (semantically cached)
  completion.
* **Statements** ("we need a child seat", "my wife prefers an SUV") go to
  Agent Memory and are recalled on that customer's later turns.

The run is in-process (it calls `concierge.ask` directly), so it needs no
app sessions, and it reports per location, per use case and per cache outcome.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import math
import random
import time
from zoneinfo import ZoneInfo

from . import catalog as C
from . import concierge, config
from .aom_client import aom
from .docs import STATE, profile_id
from .store import store

log = logging.getLogger("cbcars.workload")

# --------------------------------------------------------------------------
# What renters ask. `personal` questions take the customer's own data path
# (context cache); the rest go to the RAG application over the playbook.
# `weight` is the share of the queue (Zipf-ish), `variants[0]` is the wording
# most customers use; the others are paraphrases for semantic hits.
# --------------------------------------------------------------------------
USE_CASES: list[dict] = [
    # --- before pickup: documents, check-in, the counter ---------------------------
    {"id": "checkin_how", "intent": "checkin", "personal": False, "weight": 10,
     "variants": ["What do I need for check-in?", "How does mobile check-in work?",
                  "What is Skip the Counter and how do I complete it?", "Is there anything to do before pickup day?"]},
    {"id": "checkin_mine", "intent": "checkin", "personal": True, "weight": 8,
     "variants": ["Am I checked in for my rental?", "Have we finished check-in yet?",
                  "Can you check my check-in status and pickup window?"]},
    {"id": "arrival_time", "intent": "checkin", "personal": False, "weight": 8,
     "variants": ["What time should I arrive at the rental counter?", "When can I pick up the car on pickup day?",
                  "How early should we get to the Couchbase Cars lot?"]},
    {"id": "documents", "intent": "checkin", "personal": False, "weight": 6,
     "variants": ["What documents do I need to pick up the car?", "Do I need a credit card to rent?",
                  "Is a digital driver's license accepted?"]},
    {"id": "preferred_row", "intent": "bundle", "personal": False, "weight": 5,
     "variants": ["What is the Preferred Row?", "How does Couchbase Cars Preferred skip the counter?",
                  "Where do I find my car as a Preferred member?"]},
    {"id": "luggage", "intent": "general", "personal": False, "weight": 4,
     "variants": ["How much luggage fits in a full-size car?", "Can I get a car with a bigger trunk?",
                  "Will four suitcases fit in an SUV?"]},
    {"id": "parking", "intent": "general", "personal": False, "weight": 3,
     "variants": ["Where do I return the car at the airport?", "Is there a return lane for Preferred members?"]},
    # --- vehicles & upgrades ---------------------------------------------------
    {"id": "upgrade_how", "intent": "upgrade", "personal": False, "weight": 9,
     "variants": ["How does Couchbase Cars Upgrade work?", "How do standby upgrade offers work?",
                  "Can you explain the Couchbase Cars Upgrade standby program?"]},
    {"id": "upgrade_mine", "intent": "upgrade", "personal": True, "weight": 9,
     "variants": ["Can we upgrade to a luxury car?", "Is there a bigger vehicle available for my rental?",
                  "What would it cost to move my car up a class?"]},
    {"id": "upgrade_followup", "intent": "upgrade", "personal": True, "weight": 7, "followup_of": "upgrade_mine",
     "variants": ["What would the Premium cost for my rental?", "How much is the SUV upgrade for us?",
                  "What is the minimum standby offer I can make?"]},
    {"id": "premium_perks", "intent": "upgrade", "personal": False, "weight": 4,
     "variants": ["What are the Premium class perks?", "What is included with a Luxury car?",
                  "Do Luxury rentals include e-Toll?"]},
    # --- extras & equipment ----------------------------------------------------------
    {"id": "extra_mine", "intent": "extra", "personal": True, "weight": 9,
     "variants": ["What extras do you recommend for my trip?", "What can we add to our rental?",
                  "Which add-ons match what we like?"]},
    {"id": "extra_kids", "intent": "extra", "personal": True, "weight": 4, "followup_of": "extra_mine",
     "variants": ["Which car seats do my kids need?", "Anything for our trip that works for a family?",
                  "What's the best setup for a road trip with kids?"]},
    {"id": "child_seat", "intent": "extra", "personal": False, "weight": 6,
     "variants": ["Can I add a child seat?", "Do you have booster seats?", "Is a car seat installed before I arrive?"]},
    {"id": "extra_cancel", "intent": "extra", "personal": False, "weight": 3,
     "variants": ["Can I cancel an extra?", "What is the cancellation policy for equipment?",
                  "Do I get a refund if the GPS isn't in the car?"]},
    # --- protection ---------------------------------------------------------------------
    {"id": "protection_mine", "intent": "protection", "personal": True, "weight": 8,
     "variants": ["Which protection should we add for our anniversary trip?", "Which coverage do you suggest for us?",
                  "Can you add protection for my family's rental?"]},
    {"id": "ldw", "intent": "protection", "personal": False, "weight": 6,
     "variants": ["Do I need the Loss Damage Waiver?", "Does my credit card cover rental damage?",
                  "What is the deductible without LDW?"]},
    {"id": "roadside", "intent": "protection", "personal": False, "weight": 5,
     "variants": ["What does Roadside SafetyNet cover?", "What happens if I get a flat tire?",
                  "Who do I call if I lock the keys in the car?"]},
    {"id": "young_driver", "intent": "general", "personal": False, "weight": 7,
     "variants": ["What is the minimum age to rent?", "Is there a young driver fee?",
                  "Can my 22-year-old be an additional driver?"]},
    # --- bundles: fuel, tolls, Wi-Fi, Peace of Mind / Total ---------------------------------------
    {"id": "total", "intent": "bundle", "personal": False, "weight": 10,
     "variants": ["What's included in Couchbase Cars Total Protection?", "What do I get with the Total Protection bundle?",
                  "Total Protection vs Peace of Mind - what is the difference?"]},
    {"id": "fuel", "intent": "bundle", "personal": False, "weight": 8,
     "variants": ["What are the fuel options?", "Is prepaid fuel worth it?",
                  "What happens if I return the car with less fuel?"]},
    {"id": "wifi", "intent": "bundle", "personal": False, "weight": 7,
     "variants": ["Is Wi-Fi available in the car?", "How good is the Couchbase Cars Wi-Fi hotspot for video calls?",
                  "Can the kids stream in the back seat?"]},
    {"id": "bundle_mine", "intent": "bundle", "personal": True, "weight": 6,
     "variants": ["Which bundle makes sense for us?", "Should I add Couchbase Cars Peace of Mind to my booking?",
                  "Do we already have tolls included?"]},
    {"id": "tolls", "intent": "bundle", "personal": False, "weight": 3,
     "variants": ["How do tolls work?", "What does e-Toll Unlimited include?"]},
    # --- services ----------------------------------------------------------------
    {"id": "service_delivery", "intent": "service", "personal": False, "weight": 5,
     "variants": ["Are services cheaper mid-rental?", "Does Couchbase Cars deliver the car to my hotel?",
                  "When is the best time to book a refuel service?"]},
    {"id": "service_mine", "intent": "service", "personal": True, "weight": 4,
     "variants": ["Can you book a hotel delivery for my pickup day?", "I'd like the car collected from our hotel - options?",
                  "Which service would you suggest for me?"]},
    {"id": "ev", "intent": "service", "personal": False, "weight": 3,
     "variants": ["Do you rent electric cars?", "Is charging included with an EV?", "Where do I charge the car?"]},
    # --- the trip & the location -----------------------------------------------------------
    {"id": "trip_mine", "intent": "trip", "personal": True, "weight": 8,
     "variants": ["What's my trip plan?", "Which stops are on our route and when?", "When is our first driving day?"]},
    {"id": "return_time", "intent": "trip", "personal": True, "weight": 5, "followup_of": "trip_mine",
     "variants": ["What time do we need to return the car?", "How long is each stop on my trip?",
                  "Can I return the car at a different location?"]},
    {"id": "kids", "intent": "general", "personal": False, "weight": 6,
     "variants": ["Are kids allowed as additional drivers?", "What's the child seat law in Florida?", "Is there a family car class?"]},
    {"id": "fees", "intent": "general", "personal": False, "weight": 6,
     "variants": ["What fees are added at the airport?", "Is the concession recovery fee included in my rate?",
                  "Can I prepay the whole rental?"]},
    {"id": "smoking", "intent": "general", "personal": False, "weight": 2,
     "variants": ["Can I smoke in the rental car?", "Is there a cleaning fee for vaping?"]},
    {"id": "mileage", "intent": "general", "personal": False, "weight": 2,
     "variants": ["Is mileage unlimited?", "Can I drive the car into Canada or Mexico?"]},
    {"id": "one_way", "intent": "general", "personal": False, "weight": 2,
     "variants": ["Can I do a one-way rental?", "Is there a drop fee for returning to another city?"]},
    {"id": "payment", "intent": "general", "personal": False, "weight": 3,
     "variants": ["What payment methods are accepted?", "Can I pay with a debit card?",
                  "How much is the security deposit hold?"]},
    {"id": "accident", "intent": "general", "personal": False, "weight": 3,
     "variants": ["What do I do if I have an accident?", "Who do I call if the car breaks down?",
                  "What if I get a parking ticket in the rental?"]},
    {"id": "accessibility", "intent": "general", "personal": False, "weight": 2,
     "variants": ["Do you have cars with hand controls?", "Can I rent a wheelchair-accessible van?"]},
    {"id": "loyalty", "intent": "general", "personal": False, "weight": 4,
     "variants": ["What are the Couchbase Cars Preferred benefits?", "What do President’s Club members get?",
                  "How do I reach Preferred Plus?"]},
    {"id": "celebration", "intent": "protection", "personal": False, "weight": 3,
     "variants": ["Can you arrange something for a birthday road trip?", "Do you offer anniversary upgrades?",
                  "How do I get a convertible for our honeymoon?"]},
    {"id": "roadside_app", "intent": "bundle", "personal": False, "weight": 3,
     "variants": ["What is Couchbase Cars Roadside?", "Can I request help from the app?",
                  "Is roadside assistance included with Peace of Mind?"]},
    {"id": "cancellation", "intent": "general", "personal": False, "weight": 3,
     "variants": ["What is the cancellation policy?", "Can I change my pickup date?",
                  "When is the pay-now rate charged?"]},
    # --- service recovery (approval-tier goodwill upgrade) ---------------------------------
    {"id": "service_recovery", "intent": "service_recovery", "personal": True, "weight": 2,
     "variants": ["The car they assigned us smells of smoke and the trunk is dirty, can you help?",
                  "The check engine warning light is on in my car.",
                  "My car was scratched and the AC isn't working when we picked it up, I'm disappointed."]},
]
USE_CASE_BY_ID = {u["id"]: u for u in USE_CASES}

# What customers tell the concierge about themselves - written to AOM Agent
# Memory, recalled on their later personal turns.
STATEMENTS = [
    "We need two child seats, so please keep that in mind for our car.", "My wife prefers an SUV.",
    "I'm celebrating my 40th birthday on this trip.", "We always want a car with Apple CarPlay.",
    "My son gets car sick in the back seat.", "I don't like early mornings, so no 6am pickups please.",
    "We love national parks and anything outdoors.", "My husband needs hand controls.",
    "I never buy prepaid fuel.", "We prefer electric or hybrid cars.",
]

RUN: dict = {"state": "idle"}
_TASK: asyncio.Task | None = None


def _normalize_outcome(llm: dict) -> str:
    """AOM reports `hit_exact`, `hit_semantic` or `miss` (plus bypass/error)."""
    st = (llm or {}).get("status") or "local"
    if st.startswith("hit"):
        return "exact_hit" if st in ("hit", "hit_exact") or (llm.get("similarity") or 0) >= 0.999 else "semantic_hit"
    if st == "miss":
        return "miss"
    return st  # local / error / skipped / bypass


class _Plan:
    """The renters and their questions, before anything runs."""

    def __init__(self, customers: list[dict], turns_per_customer: int, seed: int, repeat_ratio: float, paraphrase_ratio: float):
        self.rng = random.Random(seed)
        self.customers = customers
        self.turns = turns_per_customer
        self.repeat_ratio = repeat_ratio
        self.paraphrase_ratio = paraphrase_ratio
        self.playbook = [u for u in USE_CASES if not u["personal"]]
        self.personal_openers = [u for u in USE_CASES if u["personal"] and not u.get("followup_of")]
        self.followups = {}
        for u in USE_CASES:
            if u.get("followup_of"):
                self.followups.setdefault(u["followup_of"], []).append(u)

    def _phrase(self, uc: dict) -> str:
        v = uc["variants"]
        if len(v) > 1 and self.rng.random() < self.paraphrase_ratio:
            return self.rng.choice(v[1:])
        return v[0]

    def _pick_playbook(self) -> dict:
        return self.rng.choices(self.playbook, weights=[u["weight"] for u in self.playbook])[0]

    def session(self, customer: dict) -> list[dict]:
        """One customer's conversation: a statement, a personal thread (open +
        follow-up + maybe repeat), the rest playbook questions."""
        rng = self.rng
        turns: list[dict] = []
        if rng.random() < 0.5:
            turns.append({"use_case": "statement", "intent": "memory", "personal": True, "message": rng.choice(STATEMENTS)})
        opener = rng.choices(self.personal_openers, weights=[u["weight"] for u in self.personal_openers])[0]
        first = self._phrase(opener)
        turns.append({"use_case": opener["id"], "intent": opener["intent"], "personal": True, "message": first})
        fu = self.followups.get(opener["id"])
        if fu:
            f = rng.choice(fu)
            turns.append({"use_case": f["id"], "intent": f["intent"], "personal": True, "message": self._phrase(f)})
        if rng.random() < self.repeat_ratio:
            turns.append({"use_case": opener["id"], "intent": opener["intent"], "personal": True, "message": first,
                          "repeat": True})
        while len(turns) < self.turns:
            uc = self._pick_playbook()
            turns.append({"use_case": uc["id"], "intent": uc["intent"], "personal": False, "message": self._phrase(uc)})
        return turns[: max(self.turns, 2)]


async def pick_customers(customers_per_location: int, locations: list[str] | None, window_days: int, seed: int) -> list[dict]:
    export_date = STATE.get("export_date")
    if not export_date:
        raise RuntimeError("no Redshift unload loaded yet")
    today = dt.date.fromisoformat(config.DEMO_TODAY or export_date)
    rows = await store.customers_renting_between(today.isoformat(), (today + dt.timedelta(days=window_days)).isoformat())
    rng = random.Random(seed)
    rng.shuffle(rows)
    want = set(locations or C.LOCATIONS)
    by_location: dict[str, list[dict]] = {}
    # Lead customers first (they hold the reservation), then anyone.
    for r in sorted(rows, key=lambda r: not r.get("lead_customer")):
        code = r.get("location_code")
        if code in want and len(by_location.setdefault(code, [])) < customers_per_location:
            by_location[code].append(r)
    out = []
    for code in C.LOCATIONS:
        for r in by_location.get(code, []):
            out.append({"customer_id": r["customer_id"], "location_code": code, "location_name": C.LOCATIONS[code]["name"],
                        "pickup_date": r.get("pickup_date")})
    return out


def plan(customers: list[dict], turns_per_customer=6, seed=7, repeat_ratio=0.5, paraphrase_ratio=0.3) -> list[dict]:
    p = _Plan(customers, turns_per_customer, seed, repeat_ratio, paraphrase_ratio)
    return [{**g, "turns": p.session(g)} for g in customers]


def _empty_bucket() -> dict:
    return {"turns": 0, "llm_exact_hit": 0, "llm_semantic_hit": 0, "llm_miss": 0, "llm_other": 0,
            "context_hit": 0, "context_miss": 0, "rag_app": 0, "memory_writes": 0, "errors": 0,
            "tokens_saved": 0, "cost_saved_usd": 0.0, "latency_ms_total": 0.0}


def _count(bucket: dict, rec: dict):
    bucket["turns"] += 1
    o = rec["llm_outcome"]
    bucket[{"exact_hit": "llm_exact_hit", "semantic_hit": "llm_semantic_hit", "miss": "llm_miss"}.get(o, "llm_other")] += 1
    if rec.get("context") == "hit":
        bucket["context_hit"] += 1
    elif rec.get("context") in ("miss", "built"):
        bucket["context_miss"] += 1
    if rec.get("path") == "rag_app":
        bucket["rag_app"] += 1
    if rec.get("use_case") == "statement":
        bucket["memory_writes"] += 1
    if rec.get("error"):
        bucket["errors"] += 1
    bucket["tokens_saved"] += rec.get("tokens_saved") or 0
    bucket["cost_saved_usd"] = round(bucket["cost_saved_usd"] + (rec.get("cost_saved_usd") or 0), 6)
    bucket["latency_ms_total"] += rec.get("latency_ms") or 0


def _finish_bucket(b: dict) -> dict:
    cacheable = b["llm_exact_hit"] + b["llm_semantic_hit"] + b["llm_miss"]
    ctx = b["context_hit"] + b["context_miss"]
    b["llm_hit_rate"] = round(100 * (b["llm_exact_hit"] + b["llm_semantic_hit"]) / cacheable, 1) if cacheable else None
    b["context_hit_rate"] = round(100 * b["context_hit"] / ctx, 1) if ctx else None
    b["avg_latency_ms"] = round(b["latency_ms_total"] / b["turns"], 1) if b["turns"] else None
    return b


async def _one_turn(customer: dict, turn: dict, session_id: str) -> dict:
    t0 = time.perf_counter()
    rec = {"customer_id": customer["customer_id"], "location_code": customer["location_code"], "location_name": customer["location_name"],
           "use_case": turn["use_case"], "expected_intent": turn["intent"], "message": turn["message"],
           "repeat": bool(turn.get("repeat"))}
    try:
        res = await concierge.ask(customer["customer_id"], turn["message"], session_id)
        llm = res.get("llm") or {}
        ctx = res.get("context") or {}
        rec.update({
            "intent": res.get("intent"), "personal": res.get("personal"),
            "path": "rag_app" if ctx.get("source") == "aom-rag" else ("personal" if res.get("personal") else "playbook"),
            "llm_status": llm.get("status"), "llm_outcome": _normalize_outcome(llm), "similarity": llm.get("similarity"),
            "stub": bool(llm.get("stub")), "provider": llm.get("provider"), "model": llm.get("model"),
            "tokens_saved": llm.get("tokens_saved") or 0, "cost_saved_usd": llm.get("cost_saved_usd") or 0,
            "context": ctx.get("status"), "context_source": ctx.get("source"),
            "memory_recalled": res.get("memory_recalled", 0), "trace_id": res.get("trace_id"),
            "reply": (res.get("reply") or "")[:160],
        })
    except Exception as exc:  # noqa: BLE001 - one failing turn must not stop the fleet
        rec.update({"error": str(exc)[:200], "llm_outcome": "error", "path": "error"})
    rec["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return rec


# A day in a customer-care queue: relative traffic per local hour (0-23).
# Quiet overnight, a morning ramp as flights land, steady afternoon, peak in
# the evening when customers plan the next day, tailing off late. Used when a
# run is spread over `duration_hours` so the AOM charts look like a real
# queue, not a metronome.
DIURNAL = [0.25, 0.18, 0.15, 0.15, 0.2, 0.35, 0.6, 0.85, 1.0, 1.1, 1.15, 1.15,
           1.1, 1.05, 1.0, 1.0, 1.1, 1.3, 1.5, 1.6, 1.5, 1.2, 0.8, 0.45]
WORKLOAD_TZ = ZoneInfo("America/New_York")


def _traffic_integral(start: dt.datetime, hours: float) -> float:
    """Area under the diurnal curve from `start` for `hours` (hour-weights)."""
    total, t = 0.0, start
    remaining = hours
    while remaining > 1e-9:
        step = min(remaining, 1.0 - (t.minute * 60 + t.second) / 3600.0)
        total += DIURNAL[t.hour] * step
        t += dt.timedelta(hours=step)
        remaining -= step
    return total


class _Pacer:
    """Holds the fleet to a schedule: by `elapsed` hours the run should have
    completed total_turns * (traffic so far / traffic over the whole run)."""

    def __init__(self, total_turns: int, duration_hours: float):
        self.total = total_turns
        self.hours = duration_hours
        self.start = dt.datetime.now(WORKLOAD_TZ)
        self.whole = _traffic_integral(self.start, duration_hours) or 1.0

    def target(self, now: dt.datetime | None = None) -> int:
        now = now or dt.datetime.now(WORKLOAD_TZ)
        elapsed = min(self.hours, max(0.0, (now - self.start).total_seconds() / 3600.0))
        return int(self.total * _traffic_integral(self.start, elapsed) / self.whole)

    async def wait(self, done: int):
        """Sleep until the schedule allows the next turn (polling, so Stop works)."""
        while done >= self.target() and not RUN.get("cancel"):
            if (dt.datetime.now(WORKLOAD_TZ) - self.start).total_seconds() / 3600.0 >= self.hours:
                return
            await asyncio.sleep(2)


async def _run(sessions: list[dict], concurrency: int, pace_ms: int, duration_hours: float | None = None):
    sem = asyncio.Semaphore(max(1, concurrency))
    by_location = {s["location_code"]: _empty_bucket() | {"location_name": s["location_name"], "customers": 0} for s in sessions}
    by_use_case: dict[str, dict] = {}
    by_path: dict[str, dict] = {}
    total = _empty_bucket()
    recent: list[dict] = []
    RUN.update(by_location=by_location, by_use_case=by_use_case, by_path=by_path, total=total, recent=recent, done_turns=0,
               done_customers=0)
    pacer = _Pacer(RUN["total_turns"], duration_hours) if duration_hours else None
    if pacer:
        RUN["ends_at"] = (pacer.start + dt.timedelta(hours=duration_hours)).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    async def one_customer(s: dict):
        async with sem:
            by_location[s["location_code"]]["customers"] += 1
            session_id = f"workload-{RUN['run_id']}-{s['customer_id']}"
            for turn in s["turns"]:
                if RUN.get("cancel"):
                    return
                if pacer:
                    await pacer.wait(RUN["done_turns"])
                    if RUN.get("cancel"):
                        return
                rec = await _one_turn(s, turn, session_id)
                for b in (total, by_location[s["location_code"]], by_use_case.setdefault(rec["use_case"], _empty_bucket()),
                          by_path.setdefault(rec["path"], _empty_bucket())):
                    _count(b, rec)
                recent.append(rec)
                del recent[:-40]
                RUN["done_turns"] += 1
                if pace_ms:
                    await asyncio.sleep(pace_ms / 1000)
            RUN["done_customers"] += 1

    t0 = time.time()
    try:
        await asyncio.gather(*(one_customer(s) for s in sessions))
        RUN["state"] = "cancelled" if RUN.get("cancel") else "done"
    except asyncio.CancelledError:
        RUN["state"] = "cancelled"
        raise
    except Exception as exc:  # noqa: BLE001
        RUN.update(state="error", error=str(exc)[:300])
        log.exception("workload failed")
    finally:
        RUN["seconds"] = round(time.time() - t0, 1)
        RUN["finished_at"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for b in [total, *by_location.values(), *by_use_case.values(), *by_path.values()]:
            _finish_bucket(b)
        log.info("Fleet workload %s: %s turns in %.1fs - LLM hit rate %s%%, context hit rate %s%%", RUN["state"],
                 total["turns"], RUN["seconds"], total["llm_hit_rate"], total["context_hit_rate"])


async def start(customers_per_location=3, turns_per_customer=6, concurrency=4, locations: list[str] | None = None, seed: int = 7,
                repeat_ratio=0.5, paraphrase_ratio=0.3, window_days=45, pace_ms=0,
                duration_hours: float | None = None) -> dict:
    """`duration_hours` spreads the run over that long (e.g. 24) following the
    DIURNAL curve; otherwise it runs as fast as `concurrency` allows."""
    global _TASK
    if RUN.get("state") == "running":
        raise RuntimeError("a workload is already running - stop it first (DELETE /api/demo/workload)")
    unknown = [s for s in (locations or []) if s not in C.LOCATIONS]
    if unknown:
        raise ValueError(f"unknown location code(s): {', '.join(unknown)}; fleet is {', '.join(C.LOCATIONS)}")
    customers = await pick_customers(customers_per_location, locations, window_days, seed)
    if not customers:
        raise RuntimeError(f"no customers picking up within {window_days} days of {STATE.get('export_date')}")
    sessions = plan(customers, turns_per_customer, seed, repeat_ratio, paraphrase_ratio)
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    RUN.clear()
    RUN.update(state="running", run_id=run_id, started_at=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               params={"customers_per_location": customers_per_location, "turns_per_customer": turns_per_customer, "concurrency": concurrency,
                       "locations": locations or sorted(C.LOCATIONS), "seed": seed, "repeat_ratio": repeat_ratio,
                       "paraphrase_ratio": paraphrase_ratio, "window_days": window_days, "pace_ms": pace_ms,
                       "duration_hours": duration_hours},
               total_customers=len(sessions), total_turns=sum(len(s["turns"]) for s in sessions),
               locations_covered=sorted({s["location_code"] for s in sessions}), fleet_size=len(C.LOCATIONS),
               aom={"configured": aom.enabled, "url": config.AOM_URL or None, "dashboard_url": config.AOM_DASHBOARD_URL or None,
                    "rag_app": config.RAG_APP_ID, "llm_namespaces": [config.LLM_NAMESPACE_PLAYBOOK, config.LLM_NAMESPACE_PERSONAL],
                    "context_namespace": config.CONTEXT_NAMESPACE},
               export_date=STATE.get("export_date"))
    if duration_hours:
        RUN["ends_at"] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=duration_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _TASK = asyncio.create_task(_run(sessions, concurrency, pace_ms, duration_hours))
    return status()


def status() -> dict:
    out = dict(RUN)
    out.pop("cancel", None)
    if out.get("state") == "running":
        if out.get("params", {}).get("duration_hours") and out.get("started_at"):
            started = dt.datetime.strptime(out["started_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
            out["elapsed_hours"] = round((dt.datetime.now(dt.timezone.utc) - started).total_seconds() / 3600, 2)
        # live rates while it runs
        out["total"] = _finish_bucket(dict(out.get("total") or _empty_bucket()))
        out["by_location"] = {k: _finish_bucket(dict(v)) for k, v in (out.get("by_location") or {}).items()}
    return out


async def stop() -> dict:
    if RUN.get("state") == "running":
        RUN["cancel"] = True
        if _TASK:
            try:
                await asyncio.wait_for(asyncio.shield(_TASK), timeout=30)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                _TASK.cancel()
    return status()


def catalog() -> dict:
    """The scenario, for the story page and the CLI: locations and use cases."""
    return {
        "fleet": [{"code": c, "name": s["name"], "class": s["class"], "hub": s["city"],
                   "trips": [C.TRIPS[i]["name"] for i in C.LOCATION_TRIPS[c]]} for c, s in C.LOCATIONS.items()],
        "use_cases": [{k: v for k, v in u.items()} for u in USE_CASES],
        "statements": STATEMENTS,
    }
