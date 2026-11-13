/**
 * Offline concierge: answers from what Couchbase Lite already holds.
 *
 *  1. this customer's earlier answers (`concierge` doc `answers`, keyed by normalized question)
 *  2. the playbook FAQ synced in the `catalog` doc
 *  3. the customer's context cache (`context_cache` docs the server assembled
 *     from the AOM Knowledge Base + tool facts) - e.g. upgrade options
 *
 * Mirrors backend/app/concierge.py's intent keywords so the same question
 * lands on the same cached context offline as online.
 */
import type { ChatMessage, SuggestedAction } from '../../types';
import type { Snapshot } from '../../db/localDb';

const KEYWORDS: Record<string, string[]> = {
  service_recovery: ['smells', 'smell', 'dirty', 'broken', 'warning light', 'complain', 'disappointed', 'upset', 'not working', 'scratched', 'damaged', 'wrong car'],
  upgrade: ['upgrade', 'luxury', 'couchbase cars upgrade', 'upgrade offer', 'standby', 'bigger car', 'suv', 'premium', 'convertible', 'car class'],
  extra: ['extra', 'child seat', 'car seat', 'booster', 'gps', 'navigation', 'roof box', 'ski rack', 'bike rack', 'additional driver', 'parks pass', 'equipment'],
  protection: ['protection', 'insurance', 'ldw', 'damage waiver', 'coverage', 'liability', 'deductible', 'roadside', 'safetynet'],
  bundle: ['fuel', 'gas', 'prepaid', 'wifi', 'wi-fi', 'internet', 'hotspot', 'toll', 'tolls', 'e-toll', 'total protection', 'peace of mind', 'bundle'],
  service: ['service', 'deliver', 'delivery', 'collect', 'collection', 'late return', 'swap', 'refuel', 'car wash', 'charging'],
  checkin: ['check-in', 'check in', 'checkin', 'pickup time', 'pickup window', 'skip the counter', 'counter', 'rental agreement', 'license', 'documents'],
  trip: ['trip', 'itinerary', 'route', 'schedule', 'what day', 'which day', 'stops', 'my rental', 'my trip', 'return date'],
};

export function classify(q: string): string {
  const m = q.toLowerCase();
  let best = 'general';
  let score = 0;
  for (const [intent, kws] of Object.entries(KEYWORDS)) {
    const s = kws.filter((k) => m.includes(k)).length;
    if (s > score) {
      best = intent;
      score = s;
    }
  }
  return best;
}

export const normalize = (q: string) => q.toLowerCase().replace(/[^a-z0-9 ]/g, '').trim().slice(0, 120);

export function answerOffline(q: string, snap: Snapshot): Omit<ChatMessage, 'id' | 'at' | 'role'> {
  const intent = classify(q);
  const prior = snap.chat?.answers?.[normalize(q)];
  if (prior) {
    return { text: prior.reply, intent, offline: true, context: { status: 'device', latency_ms: 0 } };
  }
  const m = q.toLowerCase();
  const faq = (snap.catalog?.faq ?? [])
    .map((f) => ({ f, s: f.keywords.filter((k) => m.includes(k)).length }))
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s)[0];

  const p = snap.profile;
  const ctx = snap.contexts[intent];
  const actions: SuggestedAction[] = [];
  let text: string | null = null;

  if (p && (intent === 'upgrade' || intent === 'service_recovery')) {
    const opts = (snap.offers?.offers.find((o) => o.kind === 'upgrade')?.options ?? ctx?.facts?.data?.offers ?? []) as any[];
    const rec = opts.find((o) => o.recommended) ?? opts[0];
    if (rec) {
      text = `You're offline, but I have your upgrade options on this device: ${rec.class_name} (${rec.example ?? 'or similar'}) has ${rec.available} on the lot - Couchbase Cars Upgrade standby offers start at $${rec.upgrade_offer_min_pd}/day, or upgrade instantly for $${rec.instant_price_pd}/day. Tap below and I'll send it the moment you're back online.`;
      actions.push({ label: 'See upgrade options', screen: 'upgrade' });
    }
  } else if (p && intent === 'trip') {
    text = `${p.reservation.location_name}, ${p.reservation.trip_name}: ` +
      p.reservation.stops.map((d) => `${d.date.slice(5)} ${d.stop.split(',')[0]}`).join(' · ');
  } else if (p && intent === 'checkin' && !faq) {
    text = p.reservation.checkin_status === 'complete'
      ? `You're checked in - pickup window ${p.reservation.pickup_slot} on ${p.reservation.pickup_date}. Go straight to your space.`
      : `You haven't checked in yet. You can do it now - it'll sync as soon as you're online.`;
    if (p.reservation.checkin_status !== 'complete') actions.push({ label: 'Check in', screen: 'checkin' });
  } else if (p && intent === 'extra' && ctx?.facts?.data?.extras) {
    const ex = (ctx.facts.data.extras as any[]).slice(0, 3);
    text = 'From your saved picks: ' + ex.map((e) => `${e.name} ($${e.price}/${e.per})`).join('; ') + '.';
  }
  if (!text && faq) text = faq.f.a;
  if (!text && ctx?.kb_playbook?.[0]) text = ctx.kb_playbook[0].answer ?? ctx.kb_playbook[0].content;
  if (!text) {
    text = "You're offline right now, so I can only answer from what's saved on your phone. Ask me again when you're connected - or browse For You, which works offline.";
  }
  return {
    text,
    intent,
    actions,
    offline: true,
    context: { status: ctx ? 'device' : 'none', latency_ms: 0 },
    sources: faq ? [{ title: 'Customer Care Playbook (on device)', snippet: faq.f.q, kind: 'couchbase-lite' }] : [],
  };
}
