"""End-to-end checks of the demo backend in memory mode (no Couchbase, no AOM).

    cd backend && pytest -q
"""
import time
import uuid

# The `client` fixture (memory store, generated mock dump, no AOM) lives in conftest.py.


def login(client, booking, last):
    r = client.post("/api/auth/login", json={"booking_id": booking, "last_name": last})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["customer_id"]


def pull(client, h):
    docs = client.get("/api/sync/pull", headers=h).json()["docs"]
    return {(d["collection"], d["id"]): d["doc"] for d in docs}


def push(client, h, gid, tool, args):
    rid = f"req::{gid}::{uuid.uuid4().hex[:12]}"
    r = client.post("/api/sync/push", headers=h, json={"docs": [{"collection": "requests", "id": rid, "doc": {
        "type": "request", "customer_id": gid, "tool": tool, "args": args, "created_at": "2026-10-09T15:00:00Z"}}]})
    assert r.status_code == 200, r.text
    for _ in range(40):
        d = pull(client, h).get(("requests", rid))
        if d and d["status"] not in ("pending", "processing"):
            return d
        time.sleep(0.1)
    raise AssertionError("request never processed")


def test_personas_and_login(client):
    ps = client.get("/api/demo/personas").json()["personas"]
    assert [p["customer_id"] for p in ps] == ["C00000101", "C00000201", "C00000301"]
    assert client.post("/api/auth/login", json={"booking_id": "4810101", "last_name": "Nope"}).status_code == 401


def test_offers_are_personalized(client):
    h, gid = login(client, "4810101", "Bennett")
    docs = pull(client, h)
    offers = docs[("offers", f"offers::{gid}")]["offers"]
    kinds = [o["kind"] for o in offers]
    assert "checkin" in kinds and "upgrade" in kinds
    up = next(o for o in offers if o["kind"] == "upgrade")
    assert "anniversary" in up["reason"]
    assert ("catalog", "catalog::v1") in docs


def test_concierge_context_cache_and_playbook(client):
    h, gid = login(client, "4830303", "Natarajan")
    a = client.post("/api/concierge", headers=h, json={"message": "Can I upgrade my car?"}).json()
    assert a["intent"] == "upgrade" and a["personal"] and a["context"]["status"] == "miss"
    # the context was built with the customer's current Amazon Redshift profile view
    assert a["context"]["redshift"]["mode"] == "mock" and "Convenience seekers" in a["context"]["redshift"]["segments"]
    assert any(x["tool"] == "place_upgrade_offer" for x in a["actions"])
    b = client.post("/api/concierge", headers=h, json={"message": "What would an upgrade cost me?"}).json()
    assert b["context"]["status"] == "hit"
    g = client.post("/api/concierge", headers=h, json={"message": "What's included in Couchbase Cars Total Protection?"}).json()
    assert g["personal"] is False and "protection" in g["reply"].lower()
    assert ("context_cache", f"ctx::{gid}::upgrade") in pull(client, h)


def test_offline_request_flow_upgrade_and_invalidation(client):
    h, gid = login(client, "4810101", "Bennett")
    client.post("/api/concierge", headers=h, json={"message": "upgrade options for my vehicle?"})
    assert ("context_cache", f"ctx::{gid}::upgrade") in pull(client, h)
    r = push(client, h, gid, "purchase_vehicle_upgrade", {"class_code": "SFAR"})
    assert r["status"] == "confirmed", r
    docs = pull(client, h)
    assert docs[("profiles", f"profile::{gid}")]["reservation"]["vehicle"]["class_code"] == "SFAR"
    # partner's profile moved too
    assert ("context_cache", f"ctx::{gid}::upgrade") not in docs  # invalidated by the booking
    up = [o for o in docs[("offers", f"offers::{gid}")]["offers"] if o["kind"] == "upgrade"]
    assert not up or up[0]["offer_id"] != "upgrade-SFAR"


def test_business_rule_failures_come_back_on_the_request(client):
    h, gid = login(client, "4820202", "Rivera")
    # Zero Deductible Premium Protection isn't offered at Orlando Airport
    r = push(client, h, gid, "select_protection_plan", {"plan_id": "ZERO", "term": "whole rental"})
    assert r["status"] == "failed" and "isn't offered" in r["summary"]
    # a toddler seat for the family, priced per day for the 3-day rental
    r = push(client, h, gid, "add_rental_extra", {"extra_id": "SEAT-TODDLER"})
    assert r["status"] == "confirmed" and r["charge_usd"] == 15 * 3
    # a parks pass needs a national park on the plan - Orlando's doesn't have one
    r = push(client, h, gid, "add_rental_extra", {"extra_id": "PARKS-PASS"})
    assert r["status"] == "failed" and "national park" in r["summary"]
    r = push(client, h, gid, "get_upgrade_offers", {})
    assert r["status"] == "failed"


def test_push_rejects_other_customers(client):
    h, gid = login(client, "4820202", "Rivera")
    r = client.post("/api/sync/push", headers=h, json={"docs": [{"collection": "requests", "id": "req::C00000101::x",
                                                                 "doc": {"customer_id": "C00000101", "tool": "add_bundle"}}]})
    assert r.status_code == 403


def test_protection_availability_matches_bookings(client):
    """The phone only offers the protection plans the offers doc lists for the
    location; every offered one adds, every other one is refused."""
    h, gid = login(client, "4830303", "Natarajan")
    docs = pull(client, h)
    offers = docs[("offers", f"offers::{gid}")]
    avail = offers["protection_available"]
    plans = docs[("catalog", "catalog::v1")]["protection"]
    assert set(avail) == {p["id"] for p in plans}
    open_ = [pid for pid, ok in avail.items() if ok]
    assert "LDW" in open_ and "ZERO" in open_       # SFO offers the premium plan
    ok = push(client, h, gid, "select_protection_plan", {"plan_id": "TWP", "term": "first 3 days"})
    assert ok["status"] == "confirmed" and ok["charge_usd"] == 9 * 3, ok
    again = push(client, h, gid, "select_protection_plan", {"plan_id": "TWP", "term": "whole rental"})
    assert again["status"] == "failed" and "already" in again["summary"]


def test_personas_pick_up_on_schedule(client):
    """Persona rentals are pinned to the unload date: 9, 3 and 2 days out."""
    for booking, last, days in (("4810101", "Bennett", 9), ("4820202", "Rivera", 3), ("4830303", "Natarajan", 2)):
        h, gid = login(client, booking, last)
        r = pull(client, h)[("profiles", f"profile::{gid}")]["reservation"]
        import datetime as dt
        assert (dt.date.fromisoformat(r["pickup_date"]) - dt.date(2026, 10, 9)).days == days, (last, r["pickup_date"])
