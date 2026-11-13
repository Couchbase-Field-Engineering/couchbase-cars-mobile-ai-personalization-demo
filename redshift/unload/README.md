# Amazon Redshift: the customer context behind the app

Couchbase Cars' customer context lives in Amazon Redshift: the **customer 360**
(identity resolved across the reservation system, the app and the web), the
**segment memberships** a nightly segmentation job writes, and the
**propensity scores** Redshift ML produces. The demo uses it two ways.

## 1. Daily UNLOAD (batch) -> Couchbase

A scheduled `UNLOAD` of the `analytics.customer_profile_personalization`
view writes one JSON Lines part file set per day to S3, in a date partition
with a manifest:

    s3://cbcars-analytics-unload/customer_profile_personalization/dt=20261106/
        0000_part_00.json       # one customer on one upcoming reservation per line
        0001_part_00.json
        ...
        manifest                # written last: the part files and their sizes

`unload.sql` is the statement, run by the Redshift query scheduler
(EventBridge) at 05:00 America/New_York after the segmentation and Redshift
ML scoring jobs. The backend's loader watches `REDSHIFT_UNLOAD_DIR` (an S3
sync of that prefix, or the mock generator's output) for a newer `dt=*`
partition whose `manifest` exists - `MANIFEST` is written last, so it is the
completion marker - and loads every row into Couchbase, re-ranks the offers
and publishes the Knowledge Base. `redshift/generate_mock_unload.py` writes
a 100 MiB mock of that unload so the demo runs without a Redshift workgroup.

The view joins:

| Source table | Contributes |
|---|---|
| `crm.customer` + `analytics.customer_360_identity` | identity (`customer_id`, `crm_id`, Wizard number), name, home city, loyalty program and tier |
| `reservations.reservation` + `reservations.reservation_party` + `fleet.vehicle_assignment` | the upcoming rental: location, trip plan with daily stops, vehicle and space, party, check-in status, fuel option |
| `analytics.customer_preferences` | interests, driving needs, celebration, transmission / fuel-type / vehicle preferences |
| `analytics.customer_rental_history` | past rentals, ancillary spend, upgrades accepted, standby offers placed |
| `analytics.customer_segments` | the `segments` array: the segments the customer is in as of the run |
| `ml.customer_propensity` (Redshift ML `PREDICT` output) | `ml_scores`: upgrade, fuel, protection, extras, services, Wi-Fi, toll and Total Protection propensities, price sensitivity, segment, next best action, recommended upgrade class and standby offer |
| `crm.customer_consent` | `consent` |

## 2. Redshift Data API (live) -> the concierge's context

Segment memberships and scores can change during the day as the customer
browses, books or is re-scored. When the concierge assembles a customer's
context (a Couchbase Labs Agent Operations Manager Context Cache miss), it reads the customer's *current* row
over the **Redshift Data API** - no JDBC driver, IAM or Secrets Manager
auth, and the call is traceable in CloudTrail:

    ExecuteStatement  SELECT customer_id, crm_id, loyalty_tier, loyalty_points, segments, ml_scores, consent, updated_at
                      FROM analytics.customer_360_current WHERE customer_id = :cid
    DescribeStatement / GetStatementResult

That round trip (roughly 120-350 ms) is the `source_latency_ms` the Context
Cache records: the context is stored in Couchbase Labs Agent Operations Manager and in Couchbase with the real
build time, keyed by the unload date and the profile revision, so a booking
or the next unload invalidates it, and the next question is a cache hit
instead of another query. The same Data API serves the playbook table
(`redshift/playbook/README.md`).

With no `REDSHIFT_WORKGROUP` / `REDSHIFT_CLUSTER_ID` configured the backend
answers the same calls from the unloaded profile with a realistic latency
(`REDSHIFT_MOCK_LATENCY_MS`), so the cache economics show either way.

## Configuration

| Variable | |
|---|---|
| `REDSHIFT_UNLOAD_DIR` | where the daily unload lands (default `data/redshift-unload`) |
| `REDSHIFT_POLL_SECONDS` | how often the loader looks for a newer partition (default 600) |
| `REDSHIFT_WORKGROUP` *or* `REDSHIFT_CLUSTER_ID` (+ `REDSHIFT_DB_USER`) | Redshift Serverless workgroup, or a provisioned cluster, for the Data API; blank = mock mode |
| `REDSHIFT_DATABASE`, `REDSHIFT_SECRET_ARN`, `AWS_REGION` | database, optional Secrets Manager credentials, region (the task's IAM role otherwise) |
| `REDSHIFT_CUSTOMER_VIEW` | the customer 360 view (default `analytics.customer_360_current`) |
| `REDSHIFT_PLAYBOOK_TABLE` | the playbook table (default `content.customer_care_playbook`) |
| `REDSHIFT_MOCK_LATENCY_MS` | mock-mode latency range (default `120,350`) |

Live mode needs `boto3` in the backend image (`pip install boto3`); it is
not installed by default because the demo runs in mock mode.
