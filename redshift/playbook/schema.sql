-- Customer Care Playbook: the concierge's product and policy knowledge,
-- owned by Customer Care. Read daily by the demo backend over the Redshift
-- Data API (backend/app/redshift.py, playbook_entries).
CREATE SCHEMA IF NOT EXISTS content;

CREATE TABLE IF NOT EXISTS content.customer_care_playbook (
    entry_id        VARCHAR(64)   NOT NULL,          -- stable id, e.g. 'cbcars-upgrade-how'
    section         VARCHAR(64)   NOT NULL,          -- check-in, upgrades, protection, bundles, extras, services, loyalty
    question        VARCHAR(512)  NOT NULL,          -- the question as customers ask it
    answer          VARCHAR(4000) NOT NULL,          -- plain-text answer the concierge is grounded in
    keywords        SUPER         NOT NULL,          -- JSON array of strings: drives the offline FAQ match on the phone
    sort_order      INTEGER       NOT NULL DEFAULT 100,
    published       BOOLEAN       NOT NULL DEFAULT TRUE,
    effective_from  DATE          NOT NULL DEFAULT CURRENT_DATE,
    effective_to    DATE,                            -- NULL = still in effect
    updated_by      VARCHAR(128),
    updated_at      TIMESTAMP     NOT NULL DEFAULT GETDATE(),
    PRIMARY KEY (entry_id)
)
DISTSTYLE ALL
SORTKEY (sort_order);
