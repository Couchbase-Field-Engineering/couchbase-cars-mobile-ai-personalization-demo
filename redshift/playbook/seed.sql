-- Seed rows for content.customer_care_playbook: the entries the demo ships with
-- (identical to backend/app/knowledge.py FAQ). Re-run after editing: upserts by entry_id.
BEGIN;
DELETE FROM content.customer_care_playbook WHERE entry_id = 'what-time-should-i-arrive-at-the-rental-counter';
INSERT INTO content.customer_care_playbook (entry_id, section, question, answer, keywords, sort_order, updated_by)
VALUES ('what-time-should-i-arrive-at-the-rental-counter', 'checkin', 'What time should I arrive at the rental counter?',
        'Arrive in the pickup window you chose when you completed Skip the Counter check-in - it''s on your mobile rental agreement in the app. Couchbase Cars Preferred members go straight to the Preferred Row: your name and space number are on the board, the keys are in the car, and you show your license at the exit booth.',
        JSON_PARSE('["arrive", "arrival", "counter", "pickup", "pick up", "what time", "exit booth"]'), 10, 'customer-care@cbcars.example');
DELETE FROM content.customer_care_playbook WHERE entry_id = 'how-does-cbcars-upgrade-work';
INSERT INTO content.customer_care_playbook (entry_id, section, question, answer, keywords, sort_order, updated_by)
VALUES ('how-does-cbcars-upgrade-work', 'upgrades', 'How does Couchbase Cars Upgrade work?',
        'Couchbase Cars Upgrade lets you make a standby offer per day for a move to a higher car class. You''re only charged if a car in that class is on the lot when you arrive, and you can change or cancel the offer until 24 hours before pickup. If you''d rather not wait, an instant upgrade confirms right away at the listed price.',
        JSON_PARSE('["cbcars upgrade", "upgrade offer", "standby", "upgrade", "how does"]'), 20, 'customer-care@cbcars.example');
DELETE FROM content.customer_care_playbook WHERE entry_id = 'do-i-need-the-loss-damage-waiver';
INSERT INTO content.customer_care_playbook (entry_id, section, question, answer, keywords, sort_order, updated_by)
VALUES ('do-i-need-the-loss-damage-waiver', 'protection', 'Do I need the Loss Damage Waiver?',
        'The Loss Damage Waiver (LDW) covers damage to or theft of the Couchbase Cars car. Many personal auto policies and credit cards include rental coverage, so check yours first; if you''d like Couchbase Cars to carry the risk, add LDW on its own or as part of Peace of Mind or Total Protection. Every listed driver is covered.',
        JSON_PARSE('["ldw", "damage waiver", "insurance", "coverage", "protection", "cover", "deductible"]'), 30, 'customer-care@cbcars.example');
DELETE FROM content.customer_care_playbook WHERE entry_id = 'whats-included-in-cbcars-total-protection';
INSERT INTO content.customer_care_playbook (entry_id, section, question, answer, keywords, sort_order, updated_by)
VALUES ('whats-included-in-cbcars-total-protection', 'bundles', 'What''s included in Couchbase Cars Total Protection?',
        'Couchbase Cars Total Protection bundles the Loss Damage Waiver, Personal Accident & Effects, Additional Liability up to $1 million, Tire & Windshield Protection, e-Toll Unlimited and a prepaid tank of fuel. Couchbase Cars Peace of Mind is the lighter bundle: LDW, Personal Accident & Effects and Roadside SafetyNet.',
        JSON_PARSE('["total", "total protection", "peace of mind", "bundle"]'), 40, 'customer-care@cbcars.example');
DELETE FROM content.customer_care_playbook WHERE entry_id = 'is-wi-fi-available-in-the-car';
INSERT INTO content.customer_care_playbook (entry_id, section, question, answer, keywords, sort_order, updated_by)
VALUES ('is-wi-fi-available-in-the-car', 'bundles', 'Is Wi-Fi available in the car?',
        'Yes - the Couchbase Cars Wi-Fi hotspot is a 4G LTE device for up to five devices. It''s included with Couchbase Cars Total Protection or added per day in the app; it''s cheaper before you pick up than at the counter.',
        JSON_PARSE('["wifi", "wi-fi", "internet", "hotspot", "online", "connect"]'), 50, 'customer-care@cbcars.example');
DELETE FROM content.customer_care_playbook WHERE entry_id = 'how-do-tolls-work';
INSERT INTO content.customer_care_playbook (entry_id, section, question, answer, keywords, sort_order, updated_by)
VALUES ('how-do-tolls-work', 'bundles', 'How do tolls work?',
        'e-Toll lets you drive every cashless toll road and express lane without stopping; the transponder is in the car. Pay per toll plus a daily convenience fee on the days you use it, or add e-Toll Unlimited for one flat rate for the whole rental.',
        JSON_PARSE('["toll", "tolls", "e-toll", "etoll", "express lane", "transponder", "sunpass"]'), 60, 'customer-care@cbcars.example');
DELETE FROM content.customer_care_playbook WHERE entry_id = 'what-do-i-need-for-check-in';
INSERT INTO content.customer_care_playbook (entry_id, section, question, answer, keywords, sort_order, updated_by)
VALUES ('what-do-i-need-for-check-in', 'checkin', 'What do I need for check-in?',
        'Complete Skip the Counter in the app: confirm your driver''s license, add a payment card, choose a pickup window and accept the rental terms. Your mobile rental agreement is ready in the app; bring the same license and card with you to the exit booth.',
        JSON_PARSE('["check-in", "check in", "checkin", "documents", "license", "skip the counter", "rental agreement"]'), 70, 'customer-care@cbcars.example');
DELETE FROM content.customer_care_playbook WHERE entry_id = 'can-i-add-a-child-seat';
INSERT INTO content.customer_care_playbook (entry_id, section, question, answer, keywords, sort_order, updated_by)
VALUES ('can-i-add-a-child-seat', 'extras', 'Can I add a child seat?',
        'Yes - infant, toddler and booster seats are available at every location for a daily fee and are installed in the car before you arrive when you add them in the app. State law requires a child seat for children under 8 in most of the US.',
        JSON_PARSE('["child seat", "car seat", "booster", "infant", "kids", "children"]'), 80, 'customer-care@cbcars.example');
DELETE FROM content.customer_care_playbook WHERE entry_id = 'what-is-the-preferred-row';
INSERT INTO content.customer_care_playbook (entry_id, section, question, answer, keywords, sort_order, updated_by)
VALUES ('what-is-the-preferred-row', 'loyalty', 'What is the Preferred Row?',
        'Couchbase Cars Preferred members skip the counter entirely: your name and space number are on the Preferred board, the keys are in the car and the rental agreement is in the app. Preferred Plus and President''s Club members are parked on the Preferred Row nearest the exit and get complimentary one-class upgrades when available.',
        JSON_PARSE('["preferred row", "preferred", "skip the counter", "president''s club", "chairman''s club", "loyalty"]'), 90, 'customer-care@cbcars.example');
DELETE FROM content.customer_care_playbook WHERE entry_id = 'are-services-cheaper-mid-rental';
INSERT INTO content.customer_care_playbook (entry_id, section, question, answer, keywords, sort_order, updated_by)
VALUES ('are-services-cheaper-mid-rental', 'services', 'Are services cheaper mid-rental?',
        'Yes. Hotel delivery, collection, mobile refuel and vehicle swaps booked for a day that isn''t your pickup or return day are typically discounted - this app applies a 20% mid-rental price automatically.',
        JSON_PARSE('["service", "delivery", "collection", "refuel", "swap", "discount", "mid-rental"]'), 100, 'customer-care@cbcars.example');
DELETE FROM content.customer_care_playbook WHERE entry_id = 'what-are-the-fuel-options';
INSERT INTO content.customer_care_playbook (entry_id, section, question, answer, keywords, sort_order, updated_by)
VALUES ('what-are-the-fuel-options', 'bundles', 'What are the fuel options?',
        'Return the car full and pay nothing, buy a prepaid tank at our discounted pump price and return it at any level, or let us refuel on return at the per-gallon rate on your rental agreement.',
        JSON_PARSE('["fuel", "gas", "refuel", "prepaid", "tank", "return full", "charge"]'), 110, 'customer-care@cbcars.example');
COMMIT;
