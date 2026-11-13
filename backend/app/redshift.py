"""Amazon Redshift clients: the customer 360 (customer context) and the
Customer Care Playbook table (content). See redshift/unload/README.md and
redshift/playbook/README.md.

Two sources, two modes each, both over the **Redshift Data API**
(`redshift-data:ExecuteStatement` / `GetStatementResult`, no JDBC driver,
IAM or Secrets Manager auth):

* **Customer 360 view** (`REDSHIFT_CUSTOMER_VIEW`, default
  `analytics.customer_360_current`) - the customer's *current* row: segment
  memberships from the segmentation job and the Redshift ML propensity
  scores (`SELECT ... WHERE customer_id = :id`). Called when the concierge
  assembles a customer's context (an AOM Context Cache miss); the round
  trip is the `source_latency_ms` the Context Cache records. With a
  workgroup / cluster and database configured it runs the query; without
  them (`mock`) it answers from the profile the daily unload loaded into
  Couchbase, with the latency such a query has in practice, so the demo
  shows the same cache economics.
* **Playbook table** (`REDSHIFT_PLAYBOOK_TABLE`, default
  `content.customer_care_playbook`) - the Customer Care Playbook entries
  (section, question, answer, keywords, effective dates). Live it runs a
  `SELECT` for the rows in effect today; mock serves the bundled entries in
  knowledge.FAQ in the same shape.

The daily batch (UNLOAD -> loader.py) is the third Redshift touchpoint and
needs no client here: the part files and manifest simply land in
REDSHIFT_UNLOAD_DIR (an S3 sync of the UNLOAD prefix).
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time

from . import config

log = logging.getLogger("cbcars.redshift")

STATUS: dict = {"customer_view": {"mode": "mock", "calls": 0, "errors": 0, "last_latency_ms": None},
                "playbook": {"mode": "mock", "calls": 0, "errors": 0}}


class RedshiftError(Exception):
    pass


# --------------------------------------------------------------------------
# Redshift Data API (boto3 is optional: only needed in live mode)
# --------------------------------------------------------------------------
class _DataAPI:
    def __init__(self):
        self._client = None

    @property
    def configured(self) -> bool:
        return bool((config.REDSHIFT_WORKGROUP or config.REDSHIFT_CLUSTER_ID) and config.REDSHIFT_DATABASE)

    def _target(self) -> dict:
        t = {"Database": config.REDSHIFT_DATABASE}
        if config.REDSHIFT_WORKGROUP:
            t["WorkgroupName"] = config.REDSHIFT_WORKGROUP          # Redshift Serverless
        else:
            t["ClusterIdentifier"] = config.REDSHIFT_CLUSTER_ID     # provisioned cluster
            if config.REDSHIFT_DB_USER:
                t["DbUser"] = config.REDSHIFT_DB_USER
        if config.REDSHIFT_SECRET_ARN:
            t["SecretArn"] = config.REDSHIFT_SECRET_ARN
        return t

    def _boto(self):
        if self._client is None:
            try:
                import boto3  # noqa: WPS433 - optional dependency
            except ImportError as exc:  # pragma: no cover
                raise RedshiftError("boto3 is not installed (pip install boto3) - needed for live Redshift Data API calls") from exc
            self._client = boto3.client("redshift-data", region_name=config.AWS_REGION or None)
        return self._client

    def _query_sync(self, sql: str, params: list[dict]) -> list[dict]:
        c = self._boto()
        res = c.execute_statement(Sql=sql, Parameters=params, **self._target())
        sid = res["Id"]
        deadline = time.time() + config.REDSHIFT_TIMEOUT_SECONDS
        while True:
            d = c.describe_statement(Id=sid)
            st = d["Status"]
            if st == "FINISHED":
                break
            if st in ("FAILED", "ABORTED"):
                raise RedshiftError(f"Data API statement {st}: {d.get('Error', '')[:200]}")
            if time.time() > deadline:
                raise RedshiftError("Data API statement timed out")
            time.sleep(0.05)
        if not d.get("HasResultSet"):
            return []
        out = c.get_statement_result(Id=sid)
        cols = [m["name"] for m in out["ColumnMetadata"]]
        rows = []
        for rec in out["Records"]:
            row = {}
            for name, cell in zip(cols, rec):
                row[name] = None if cell.get("isNull") else next(iter(cell.values()))
            rows.append(row)
        return rows

    async def query(self, sql: str, params: list[dict] | None = None) -> list[dict]:
        return await asyncio.to_thread(self._query_sync, sql, params or [])


_api = _DataAPI()


def _json(v, default):
    if v is None:
        return default
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# Customer 360: the customer's current segments and scores
# --------------------------------------------------------------------------
def _mock_profile_view(profile: dict) -> dict:
    """What the customer 360 query returns for this customer, from the
    unloaded profile: identity, realized segments, Redshift ML scores."""
    s = profile.get("ml_scores") or {}
    return {
        "identity": profile.get("identity") or {"customer_id": profile["customer_id"]},
        "segments": [{"id": a["id"], "name": a["name"], "status": a.get("status", "realized")}
                     for a in (profile.get("segments") or [])],
        "propensity": {k: v for k, v in s.items() if k.endswith("_propensity") or k in ("price_sensitivity", "segment",
                                                                                          "next_best_action", "model_version")},
        "loyalty": profile.get("loyalty"),
        "consent": profile.get("consent"),
        "profile_updated_at": f"{profile.get('export_date')}T05:00:00Z",
    }


async def profile_view(customer_id: str, profile: dict | None) -> dict:
    """The customer's current Redshift customer-360 row + how long it took.
    `profile` is the unloaded profile from Couchbase (used by the mock, and
    as the fallback if the live query fails)."""
    t0 = time.perf_counter()
    st = STATUS["customer_view"]
    st["calls"] += 1
    if _api.configured:
        st["mode"] = "live"
        try:
            rows = await _api.query(
                f"SELECT customer_id, crm_id, loyalty_tier, loyalty_points, segments, ml_scores, consent, updated_at "
                f"FROM {config.REDSHIFT_CUSTOMER_VIEW} WHERE customer_id = :cid",
                [{"name": "cid", "value": customer_id}])
            if not rows:
                raise RedshiftError(f"no customer_360 row for {customer_id}")
            row = rows[0]
            scores = _json(row.get("ml_scores"), {})
            view = {
                "identity": {"customer_id": row["customer_id"], "crm_id": row.get("crm_id")},
                "segments": [{"id": m.get("id"), "name": m.get("name", m.get("id")), "status": m.get("status", "realized")}
                             for m in _json(row.get("segments"), [])],
                "propensity": {k: v for k, v in scores.items() if k.endswith("_propensity") or k in ("price_sensitivity", "segment",
                                                                                                        "next_best_action", "model_version")},
                "loyalty": {"tier": row.get("loyalty_tier"), "points": row.get("loyalty_points")} if row.get("loyalty_tier") else (profile or {}).get("loyalty"),
                "consent": _json(row.get("consent"), None),
                "profile_updated_at": row.get("updated_at"),
            }
        except Exception as exc:  # noqa: BLE001 - any Data API / boto failure falls back to the unloaded profile
            st["errors"] += 1
            log.warning("Redshift customer-360 lookup failed (%s); using the unloaded profile", exc)
            view = _mock_profile_view(profile) if profile else {"identity": {"customer_id": customer_id}, "segments": [], "propensity": {}}
            view["fallback"] = str(exc)[:120]
    else:
        st["mode"] = "mock"
        # A Data API round trip (ExecuteStatement + poll + GetStatementResult)
        # takes roughly 120-350 ms; that latency is the point of caching the
        # assembled context.
        await asyncio.sleep(random.uniform(config.REDSHIFT_MOCK_LATENCY_MS[0], config.REDSHIFT_MOCK_LATENCY_MS[1]) / 1000)
        view = _mock_profile_view(profile) if profile else {"identity": {"customer_id": customer_id}, "segments": [], "propensity": {}}
    view["source"] = "redshift"
    view["mode"] = st["mode"]
    view["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    st["last_latency_ms"] = view["latency_ms"]
    return view


def audiences_text(view: dict) -> str:
    names = [m["name"] for m in view.get("segments", []) if m.get("status", "realized") == "realized"]
    return ", ".join(names) if names else "no segment memberships"


# --------------------------------------------------------------------------
# Playbook table: Customer Care Playbook entries
# --------------------------------------------------------------------------
async def playbook_entries(today: str) -> tuple[list[dict], str]:
    """The playbook's rows in effect today: [{section, q, a, keywords}], mode."""
    from . import knowledge  # late import: knowledge renders with these entries
    st = STATUS["playbook"]
    st["calls"] += 1
    if _api.configured:
        st["mode"] = "live"
        try:
            rows = await _api.query(
                f"SELECT entry_id, section, question, answer, keywords FROM {config.REDSHIFT_PLAYBOOK_TABLE} "
                f"WHERE effective_from <= :d AND (effective_to IS NULL OR effective_to > :d) AND published ORDER BY sort_order",
                [{"name": "d", "value": today}])
            entries = [{"section": r.get("section"), "q": r.get("question"), "a": r.get("answer") or "",
                        "keywords": _json(r.get("keywords"), []), "entry_id": r.get("entry_id")} for r in rows]
            if entries:
                return entries, "live"
        except Exception as exc:  # noqa: BLE001
            st["errors"] += 1
            log.warning("Redshift playbook query failed (%s); using the bundled entries", exc)
    st["mode"] = "mock"
    return [dict(f) for f in knowledge.FAQ], "mock"
