# The Customer Care Playbook in Amazon Redshift

The concierge's product and policy knowledge - the *Customer Care Playbook*
- is content, not code. Customer Care owns it in a Redshift table,
`content.customer_care_playbook` (`schema.sql`), one row per entry with a
section, the question customers ask, the answer, the keywords that drive the
offline FAQ match on the phone, and effective dates so an entry can be
published ahead of a policy change.

Every morning, after the customer-profile unload loads, the backend reads
the rows in effect today over the Redshift Data API:

    SELECT entry_id, section, question, answer, keywords
    FROM content.customer_care_playbook
    WHERE effective_from <= :today AND (effective_to IS NULL OR effective_to > :today) AND published
    ORDER BY sort_order

and renders them, with the catalog, into the *Customer Care Playbook <date>*
document it publishes to the Couchbase Labs Agent Operations Manager Knowledge Base (`backend/app/knowledge.py`,
`playbook_markdown`). The RAG application is re-scoped to that document, and
the same entries are synced to the phone inside the `catalog` document so
the app can answer the common questions from Couchbase Lite offline.

`seed.sql` loads the entries the demo ships with (the same text as
`knowledge.FAQ`). With no Redshift workgroup configured the backend serves
those bundled entries in the same shape (`playbook_mode: mock` in
`/api/status`).
