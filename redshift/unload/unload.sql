-- Daily customer-profile unload for the Couchbase Cars mobile personalization demo.
-- Scheduled with the Redshift query scheduler (EventBridge rule) at 05:00
-- America/New_York, after the nightly segmentation job and the Redshift ML
-- scoring job have run. The backend loader picks up the new dt= partition
-- as soon as the manifest appears (MANIFEST is written last).
--
-- The IAM role needs s3:PutObject on the prefix; the backend host syncs the
-- prefix into REDSHIFT_UNLOAD_DIR (aws s3 sync ... --exclude "*" --include "dt=*").

UNLOAD ('
  SELECT row_json
  FROM analytics.customer_profile_personalization
  ORDER BY is_demo_persona DESC, location_code, pickup_date, customer_id
')
TO 's3://cbcars-analytics-unload/customer_profile_personalization/dt={{ run_date_yyyymmdd }}/'
IAM_ROLE 'arn:aws:iam::123456789012:role/cbcars-analytics-unload'
FORMAT AS JSON          -- one JSON object per line (JSON Lines)
MANIFEST                -- <prefix>manifest lists the part files; written last = partition complete
PARALLEL ON             -- one part per slice: 0000_part_00, 0001_part_00, ...
MAXFILESIZE 25 MB       -- keep each part comfortably under 50 MB
ALLOWOVERWRITE;

-- The view the unload reads. `row_json` is the nested profile the app and the
-- AOM Knowledge Base consume: identity, loyalty, the upcoming reservation
-- (trip stops, vehicle, party), preferences, rental history, ancillary spend
-- mix, what is already on the rental, segments and ml_scores.
--
-- CREATE OR REPLACE VIEW analytics.customer_profile_personalization AS
-- SELECT c.customer_id,
--        c.is_demo_persona,
--        r.location_code,
--        r.pickup_date,
--        JSON_SERIALIZE(OBJECT(
--          'export_date',           CURRENT_DATE,
--          'schema_version',        'customer_profile_personalization_v3',
--          'customer_id',           c.customer_id,
--          'wizard_number',         c.wizard_number,
--          'first_name',            c.first_name,
--          'last_name',             c.last_name,
--          'loyalty',               l.loyalty_json,
--          'reservation',           r.reservation_json,
--          'preferences',           p.preferences_json,
--          'history',               h.history_json,
--          'ancillary_spend_mix',   h.spend_mix_json,
--          'purchased_for_rental',  r.purchased_json,
--          'ml_scores',             m.scores_json,        -- Redshift ML: ml.customer_propensity
--          'identity',              i.identity_json,      -- customer 360 identity graph
--          'segments',              s.segments_json,      -- analytics.customer_segments
--          'consent',               c.consent_json,
--          '_ingest',               OBJECT('system', 'amazon-redshift', 'source_view',
--                                          'analytics.customer_profile_personalization',
--                                          'job', 'redshift-daily-unload')
--        )) AS row_json
-- FROM crm.customer c
-- JOIN reservations.upcoming_reservation_json r USING (customer_id)
-- LEFT JOIN analytics.customer_loyalty_json      l USING (customer_id)
-- LEFT JOIN analytics.customer_preferences_json  p USING (customer_id)
-- LEFT JOIN analytics.customer_history_json      h USING (customer_id)
-- LEFT JOIN ml.customer_propensity_json          m USING (customer_id)
-- LEFT JOIN analytics.customer_360_identity_json i USING (customer_id)
-- LEFT JOIN analytics.customer_segments_json     s USING (customer_id);
--
-- The Redshift ML model behind ml.customer_propensity:
-- CREATE MODEL ml.upgrade_propensity FROM (SELECT ... FROM analytics.rental_training_set)
--   TARGET accepted_upgrade FUNCTION ml.predict_upgrade_propensity
--   IAM_ROLE 'arn:aws:iam::123456789012:role/cbcars-redshift-ml'
--   SETTINGS (S3_BUCKET 'cbcars-redshift-ml', MAX_RUNTIME 3600);
-- (one model per propensity; the scoring job writes the PREDICT output and
--  the derived next_best_action / recommended_upgrade_class to ml.customer_propensity,
--  model_version 'redshift-ml-propensity-v2')
