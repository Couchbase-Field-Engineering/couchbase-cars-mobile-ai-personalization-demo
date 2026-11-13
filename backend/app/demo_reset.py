"""Reset the demo: put customers back to the state of today's Amazon Redshift unload
and clear what they left behind, here and in AOM.

`POST /api/demo/reset` (the story page's **Reset demo** button, or
scripts/reset_demo.py). For each customer - by default the three personas plus
every customer who changed something since the unload loaded:

1. **Couchbase**: delete their `requests` (the upgrade/booking queue the phone
   shows), `concierge` chat, `context_cache` and `bookings` documents; reload
   their `profiles` document from the unload partition (vehicle, check-in,
   purchases, `rev` back to the export); release the sold vehicles of their
   rental (`inventory`, rebuilt from the catalog on next use); re-rank their
   offers; drop them from `live_customers` so the next daily load doesn't carry
   the old state forward. Sync Gateway replicates the deletes and the fresh
   profile to the phone, so Couchbase Lite ends up in the same state.
2. **AOM Agent Memory**: delete every memory entry for the customer (what they
   told the concierge, and what the Vehicle Upgrade Agent remembered).
3. **AOM caches** (optional, default on): purge the concierge's LLM Cache
   namespaces and its Context Cache namespace, so the next demo starts with a
   visible `miss` again. Everything else in AOM (traces, audit log, approvals
   history) is left alone - that is the record.
4. The backend's in-process counters and the last fleet-workload report.

Nothing here touches the export files, the Knowledge Base or the RAG application.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

from . import concierge, config, loader, metrics, personalization, workload
from .aom_client import AOMError, aom
from .docs import (STATE, bookings_id, chat_id, customer_channel, inventory_id, now_iso, offers_id,
                   profile_id)
from .store import store

log = logging.getLogger("cbcars.reset")
LAST: dict = {"state": "never"}


async def default_customers() -> list[str]:
    live = (await store.get("lookups", "live_customers") or {}).get("customers", [])
    return list(dict.fromkeys(loader.PERSONAS + list(live)))


def _export_rows(customer_ids: set[str]) -> dict[str, dict]:
    """The export rows of these customers (personas are first in 0000_part_00)."""
    part = loader.latest_partition(os.path.abspath(config.REDSHIFT_UNLOAD_DIR))
    found: dict[str, dict] = {}
    if not part:
        return found
    for row in loader.read_rows(part):
        if row["customer_id"] in customer_ids:
            found[row["customer_id"]] = row
            if len(found) == len(customer_ids):
                break
    return found


async def _reset_customer(gid: str, row: dict | None, aom_memory: bool) -> dict:
    out = {"customer_id": gid, "requests": 0, "docs": [], "profile": "kept", "memories": 0, "inventory": None}
    for d in await store.requests_for_customer(gid):
        await store.remove("requests", d["_id"])
        out["requests"] += 1
    for col, key in (("concierge", chat_id(gid)), ("bookings", bookings_id(gid)), ("offers", offers_id(gid))):
        if await store.get(col, key):
            await store.remove(col, key)
            out["docs"].append(col)
    await concierge.invalidate_context(gid)
    prev = await store.get("profiles", profile_id(gid))
    if row:
        doc = {**row, "type": "profile", "rev": 0, "channels": [customer_channel(gid)], "loaded_at": now_iso()}
        await store.upsert("profiles", profile_id(gid), doc)
        out["profile"] = "reloaded"
        rental = (prev or row)["reservation"].get("rental_id")
        if rental and await store.get("inventory", inventory_id(rental)):
            await store.remove("inventory", inventory_id(rental))   # rebuilt from the catalog on next use
            out["inventory"] = rental
    elif prev:
        out["profile"] = "not in export"
    if await store.get("profiles", profile_id(gid)):
        await personalization.refresh_offers(gid)
    if aom_memory and aom.enabled:
        try:
            for m in await aom.memory_list(gid):
                if m.get("memory_id") and await aom.memory_delete(m["memory_id"]):
                    out["memories"] += 1
        except AOMError as exc:
            out["memory_error"] = str(exc)[:200]
    return out


async def _purge_aom_caches() -> dict:
    """Purge every AOM cache namespace that belongs to the concierge: the
    namespaces it calls directly (`rag:<app>:playbook|personal|customer-context`)
    and the ones AOM's RAG application made for it (`rag:<app>` and
    `rag:<app>:<fingerprint>`). AOM purges by exact namespace, so list first."""
    prefix = f"rag:{config.RAG_APP_ID}"
    out: dict = {}
    try:
        llm_ns = {config.LLM_NAMESPACE_PLAYBOOK, config.LLM_NAMESPACE_PERSONAL}
        ctx_ns = {config.CONTEXT_NAMESPACE}
        for _ in range(4):  # the listing is capped at 500 entries; look again until nothing is left
            more_llm = await aom.llm_cache_namespaces(prefix) - llm_ns
            more_ctx = await aom.context_cache_namespaces(prefix) - ctx_ns
            llm_ns |= more_llm
            ctx_ns |= more_ctx
            for ns in sorted(llm_ns):
                out.setdefault(ns, {})["llm_purged"] = out.get(ns, {}).get("llm_purged", 0) + await aom.purge_llm_cache(ns)
            for ns in sorted(ctx_ns):
                out.setdefault(ns, {})["context_purged"] = out.get(ns, {}).get("context_purged", 0) + await aom.purge_context_cache(ns)
            if not more_llm and not more_ctx:
                break
    except AOMError as exc:
        out["error"] = str(exc)[:200]
    return out


async def run(customers: list[str] | None = None, aom_memory: bool = True, aom_caches: bool = True,
              counters: bool = True) -> dict:
    t0 = time.time()
    gids = list(dict.fromkeys(customers)) if customers else await default_customers()
    rows = await asyncio.to_thread(_export_rows, set(gids))
    results = [await _reset_customer(g, rows.get(g), aom_memory) for g in gids]
    live = await store.get("lookups", "live_customers")
    if live:
        live["customers"] = [g for g in live.get("customers", []) if g not in gids]
        await store.upsert("lookups", "live_customers", live)
    caches: dict = {}
    if aom_caches and aom.admin_enabled:
        caches = await _purge_aom_caches()
    elif aom_caches:
        caches = {"skipped": "AOM admin password not configured" if aom.enabled else "AOM not configured"}
    if counters:
        metrics.reset()
        if workload.RUN.get("state") != "running":
            workload.RUN.clear()
            workload.RUN["state"] = "idle"
    LAST.clear()
    LAST.update(state="done", at=now_iso(), seconds=round(time.time() - t0, 1), export_date=STATE.get("export_date"),
                customers=results, aom_memory=aom_memory, aom_caches=caches, counters=counters,
                summary={"customers": len(results), "requests_removed": sum(r["requests"] for r in results),
                         "profiles_reloaded": sum(r["profile"] == "reloaded" for r in results),
                         "memories_deleted": sum(r["memories"] for r in results)})
    log.info("Demo reset: %s", LAST["summary"])
    return dict(LAST)
