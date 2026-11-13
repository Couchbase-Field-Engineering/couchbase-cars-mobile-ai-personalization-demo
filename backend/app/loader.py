"""Daily Amazon Redshift customer-profile unload -> Couchbase + AOM Knowledge Base.

Run by the backend on startup and every REDSHIFT_POLL_SECONDS (it only does work
when a newer `dt=YYYYMMDD/manifest` partition lands), or by hand:

    python -m app.loader [--export-dir PATH] [--force] [--no-kb]

1. Stream every JSON Lines part file of the newest complete partition - the
   Redshift UNLOAD of `customer_profile_personalization`
   (redshift/unload/README.md).
2. Upsert one `profiles` document per customer (all ~100MB in Couchbase
   mode). Live state the customer changed since the last export (vehicle moves,
   check-in, purchases) is carried forward - in production that state would
   already be in the next day's profile.
3. Index bookings for login, publish the catalog, re-rank offers for customers
   inside the planning window.
4. Publish to the AOM Knowledge Base: the Customer Care Playbook, rendered
   from the Redshift playbook table (redshift/playbook/README.md), and one profile
   document per customer rental within KB_WINDOW_DAYS (demo personas always),
   replacing yesterday's version of each. The concierge's AOM RAG Application
   is then re-scoped to the new playbook document.

Context caches need no sweep: every cached context records the unload date it
was built from, so the new export makes them all stale at once.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import glob
import hashlib
import json
import logging
import os
import time

from . import catalog as C
from . import redshift, config, knowledge, personalization, rag_app
from .aom_client import AOMError, aom
from .docs import CATALOG_CHANNEL, CATALOG_ID, STATE, customer_channel, now_iso, profile_id
from .store import store

log = logging.getLogger("cbcars.loader")
PERSONAS = ["C00000101", "C00000201", "C00000301"]
LIVE_FIELDS_RES = ("vehicle", "checkin_status", "pickup_slot", "upgrade_history")
STATUS = {"state": "idle"}
_TASKS: list = []  # keep a reference so background KB publishing is not garbage-collected


PARTITION_PREFIX = "dt="


def partition_date(partition: str) -> str:
    """dt=20261104 -> 2026-11-04 (dt=2026-11-04 works too)."""
    stamp = os.path.basename(partition).split("=", 1)[1]
    digits = "".join(ch for ch in stamp if ch.isdigit())
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}" if len(digits) >= 8 else stamp


def latest_partition(export_dir: str) -> str | None:
    # UNLOAD ... MANIFEST writes the manifest last, so its presence means the
    # partition is complete.
    parts = [p for p in glob.glob(os.path.join(export_dir, PARTITION_PREFIX + "*"))
             if os.path.exists(os.path.join(p, "manifest"))]
    parts.sort(key=lambda p: (partition_date(p), os.path.basename(p)))
    return parts[-1] if parts else None


def part_files(partition: str) -> list[str]:
    """The UNLOAD part files of a partition, in order (NNNN_part_MM[.json];
    the manifest lists them, but a plain glob keeps the mock and a real S3
    sync interchangeable)."""
    return sorted(p for p in glob.glob(os.path.join(partition, "*part*")) if not p.endswith("manifest"))


def partition_id(partition: str) -> str:
    """Identifies one export's contents: folder name, part file names and
    sizes. A re-exported partition (new generator, new catalog, same date -
    even with the same deterministic file names) gets a different id, so the
    backend reloads it instead of trusting the previous load."""
    parts = part_files(partition)
    sig = [os.path.basename(partition)] + [f"{os.path.basename(p)}:{os.path.getsize(p)}" for p in parts]
    return hashlib.sha1("|".join(sig).encode()).hexdigest()[:12]


def read_rows(partition: str):
    for path in part_files(partition):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)


async def mark_live(customer_id: str):
    """Called after an action - remembers which customers have state newer than the export."""
    doc = await store.get("lookups", "live_customers") or {"customers": []}
    if customer_id not in doc["customers"]:
        doc["customers"].append(customer_id)
        await store.upsert("lookups", "live_customers", doc)


async def load(export_dir: str | None = None, force=False, kb=True) -> dict:
    export_dir = os.path.abspath(export_dir or config.REDSHIFT_UNLOAD_DIR)
    part = latest_partition(export_dir)
    if not part:
        log.warning("No complete Redshift unload (dt=*/manifest) under %s", export_dir)
        STATUS.update(state="no_export", export_dir=export_dir)
        return STATUS
    export_date = partition_date(part)
    state = await store.get("lookups", "load_state") or {}
    pid = partition_id(part)
    if (state.get("export_date") == export_date and state.get("partition_id") == pid and not force
            and state.get("driver") == store.driver and store.driver == "couchbase"):
        STATE["export_date"] = export_date
        STATUS.update(state="loaded", **state)
        log.info("Export %s already loaded", export_date)
        pb = await store.get("lookups", "kbdoc::playbook") or {}
        if kb and config.KB_ENABLED and aom.admin_enabled and pb.get("export_date") != export_date:
            # Loaded before AOM was configured (first run) - publish the KB now.
            _TASKS.append(asyncio.create_task(publish_kb(export_date, await _kb_window())))
        elif kb and aom.admin_enabled and pb.get("document_id"):
            # KB is current; make sure the RAG application points at it.
            _TASKS.append(asyncio.create_task(rag_app.sync(pb["document_id"])))
        return STATUS

    t0 = time.time()
    STATE["export_date"] = export_date
    STATUS.update(state="loading", export_date=export_date, partition=part, started_at=now_iso())
    live = set((await store.get("lookups", "live_customers") or {}).get("customers", []))
    today = dt.date.fromisoformat(config.DEMO_TODAY or export_date)
    bookings: dict[str, dict] = {}
    batch: dict[str, dict] = {}
    rows = skipped = carried = 0
    planning: list[tuple[int, str]] = []
    nbytes = sum(os.path.getsize(p) for p in part_files(part))

    for row in read_rows(part):
        gid = row["customer_id"]
        dts = (dt.date.fromisoformat(row["reservation"]["pickup_date"]) - today).days
        if store.driver == "memory" and dts > config.MEMORY_WINDOW_DAYS and gid not in PERSONAS:
            skipped += 1
            continue
        doc = {**row, "type": "profile", "rev": 0, "channels": [customer_channel(gid)], "loaded_at": now_iso()}
        if gid in live:
            prev = await store.get("profiles", profile_id(gid))
            if prev and prev["reservation"]["booking_id"] == row["reservation"]["booking_id"]:
                for f in LIVE_FIELDS_RES:
                    if f in prev["reservation"]:
                        doc["reservation"][f] = prev["reservation"][f]
                doc["purchased_for_rental"] = prev.get("purchased_for_rental", doc["purchased_for_rental"])
                doc["rev"] = int(prev.get("rev", 0)) + 1
                carried += 1
        batch[profile_id(gid)] = doc
        b = bookings.setdefault(row["reservation"]["booking_id"], {"type": "booking_index", "customers": [], "last_names": []})
        b["customers"].append(gid)
        ln = row["last_name"].lower()
        if ln not in b["last_names"]:
            b["last_names"].append(ln)
        if dts <= 45:
            planning.append((dts, gid))
        rows += 1
        if len(batch) >= 1000:
            await store.upsert_many("profiles", batch)
            batch = {}
            STATUS["rows"] = rows
    await store.upsert_many("profiles", batch)
    await store.upsert_many("lookups", {f"booking::{k}": v for k, v in bookings.items()})

    cat = C.public_catalog()
    cat.update({"type": "catalog", "faq": [{"q": f["q"], "a": f["a"], "keywords": f["keywords"]} for f in knowledge.FAQ],
                "export_date": export_date, "channels": [CATALOG_CHANNEL], "updated_at": now_iso()})
    await store.upsert("catalog", CATALOG_ID, cat)

    for _, gid in sorted(planning):
        await personalization.refresh_offers(gid)

    summary = {"export_date": export_date, "partition": part, "partition_id": pid, "rows": rows, "bookings": len(bookings),
               "skipped_outside_window": skipped, "carried_live_state": carried, "bytes": nbytes,
               "offers_ranked": len(planning), "load_seconds": round(time.time() - t0, 1),
               "driver": store.driver, "loaded_at": now_iso()}
    await store.upsert("lookups", "load_state", summary)
    STATUS.update(state="loaded", **summary)
    log.info("Loaded Redshift unload %s: %s rows (%s bookings) in %.1fs", export_date, rows, len(bookings), time.time() - t0)

    if kb and config.KB_ENABLED and aom.admin_enabled:
        window = PERSONAS + [g for d, g in sorted(planning) if 0 <= d <= config.KB_WINDOW_DAYS and g not in PERSONAS]
        _TASKS.append(asyncio.create_task(publish_kb(export_date, window[: max(config.KB_PROFILE_LIMIT, len(PERSONAS))])))
    elif kb and config.KB_ENABLED:
        STATUS["kb"] = {"state": "skipped", "reason": "AOM_URL / AOM_ADMIN_PASSWORD not set"}
    return STATUS


async def _replace_kb_doc(key: str, title: str, content: str, metadata: dict, source: str = "redshift-unload"):
    prev = await store.get("lookups", f"kbdoc::{key}")
    res = await aom.kb_ingest(title, content, metadata, source=source)
    new_id = res["document"]["document_id"]
    await store.upsert("lookups", f"kbdoc::{key}", {"type": "kb_index", "document_id": new_id, "title": title,
                                                    "export_date": metadata.get("export_date"), "at": now_iso()})
    if prev and prev.get("document_id") and prev["document_id"] != new_id:
        await aom.kb_delete(prev["document_id"])
    return new_id


async def publish_kb(export_date: str, customer_ids: list[str]):
    t0 = time.time()
    STATUS["kb"] = {"state": "publishing", "total": len(customer_ids) + 1, "done": 0, "errors": 0}
    try:
        entries, playbook_mode = await redshift.playbook_entries(export_date)
        playbook_id = await _replace_kb_doc("playbook", f"Customer Care Playbook {export_date}",
                                            knowledge.playbook_markdown(export_date, entries),
                                            {"type": "playbook", "export_date": export_date, "pii": False,
                                             "source": "redshift-playbook-table", "playbook_mode": playbook_mode},
                                            source="redshift-playbook-table")
        STATUS["kb"]["playbook_mode"] = playbook_mode
        STATUS["kb"]["done"] += 1
        # Re-point the AOM RAG application at today's playbook document.
        await rag_app.sync(playbook_id)
    except AOMError as exc:
        log.error("KB playbook publish failed: %s", exc)
        STATUS["kb"].update(state="error", error=str(exc)[:300])
        return
    sem = asyncio.Semaphore(4)

    async def one(gid):
        async with sem:
            p = await store.get("profiles", profile_id(gid))
            if not p:
                return
            try:
                await _replace_kb_doc(gid, f"Customer profile {gid} {export_date}", knowledge.customer_profile_markdown(p),
                                      {"type": "customer_profile", "customer_id": gid, "export_date": export_date,
                                       "booking_id": p["reservation"]["booking_id"], "pii": True,
                                       "source": "redshift-unload"})
                STATUS["kb"]["done"] += 1
            except AOMError as exc:
                STATUS["kb"]["errors"] += 1
                log.warning("KB publish for %s failed: %s", gid, exc)

    await asyncio.gather(*(one(g) for g in customer_ids))
    STATUS["kb"].update(state="published", seconds=round(time.time() - t0, 1), export_date=export_date)
    log.info("Published %d KB documents to AOM in %.1fs", STATUS["kb"]["done"], time.time() - t0)


async def poll_forever():
    while True:
        await asyncio.sleep(config.REDSHIFT_POLL_SECONDS)
        try:
            part = latest_partition(os.path.abspath(config.REDSHIFT_UNLOAD_DIR))
            if part and partition_date(part) != STATE.get("export_date"):
                log.info("New Redshift unload detected: %s", part)
                await load()
        except Exception as exc:  # noqa: BLE001
            log.warning("export poll failed: %s", exc)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--export-dir", "--dump-dir", dest="export_dir")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-kb", action="store_true")
    args = ap.parse_args()

    async def run():
        await store.connect()
        await load(args.export_dir, force=args.force, kb=False)
        if not args.no_kb and config.KB_ENABLED and aom.admin_enabled:
            state = await store.get("lookups", "load_state")
            await publish_kb(state["export_date"], await _kb_window())
        print(json.dumps({k: v for k, v in STATUS.items()}, indent=2, default=str))

    asyncio.run(run())


async def _kb_window() -> list[str]:
    """KB targets when run from the CLI (Couchbase mode): personas + customers in the window."""
    from .docs import days_to_pickup
    out = list(PERSONAS)
    if store.driver == "memory":
        for key in list(store.data["profiles"]):
            p = store.data["profiles"][key]
            if p["customer_id"] not in out and 0 <= days_to_pickup(p) <= config.KB_WINDOW_DAYS:
                out.append(p["customer_id"])
    else:
        rows = await store._query(
            f"SELECT RAW p.customer_id FROM {store._ks('profiles')} p WHERE p.reservation.pickup_date <= $d "
            f"AND p.reservation.pickup_date >= $t ORDER BY p.reservation.pickup_date LIMIT $n",
            d=(dt.date.fromisoformat(STATE['export_date']) + dt.timedelta(days=config.KB_WINDOW_DAYS)).isoformat(),
            t=STATE["export_date"], n=config.KB_PROFILE_LIMIT)
        out += [g for g in rows if g not in out]
    return out[: max(config.KB_PROFILE_LIMIT, len(PERSONAS))]


if __name__ == "__main__":
    main()
