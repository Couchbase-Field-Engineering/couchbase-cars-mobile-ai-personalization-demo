import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { ScrollView, StyleSheet, Text } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { theme } from '@/src/theme';
import { Button, Card, Pill, SectionTitle, money } from '@/src/ui/components';
import { ChoiceRow } from '@/src/ui/Choice';
import { RequestTracker } from '@/src/ui/RequestTracker';

const KIDS = new Set(['0-2', '3-5', '6-11', '12-17']);

export default function Protection() {
  const params = useLocalSearchParams<{ plan_id?: string }>();
  const { snap, request } = useData();
  const p = snap.profile;
  const cat = snap.catalog;
  const [pid, setPid] = useState<string | undefined>(params.plan_id);
  const [term, setTerm] = useState<string | undefined>();
  const [drivers, setDrivers] = useState<string | undefined>();
  const [reqId, setReqId] = useState<string | null>(null);
  if (!p || !cat) return null;
  const r = p.reservation;
  // Plans this location offers, synced with the offers so it works offline too.
  const avail = snap.offers?.protection_available;
  const list = cat.protection.filter((d) => (avail ? avail[d.id] !== false : d.locations === '*' || (d.locations as string[]).includes(r.location_code)));
  const sel = list.find((d) => d.id === pid) ?? list[0];
  const adults = Math.max(1, r.party.filter((m) => !KIDS.has(m.age_band)).length);
  const n = Math.min(adults, Number(drivers ?? adults));
  const chosenTerm = term ?? cat.protection_terms[0];
  const coveredDays = chosenTerm === 'whole rental' ? r.days : chosenTerm === 'pickup day only' ? 1 : Math.min(3, r.days);
  const owned = new Set(p.purchased_for_rental?.protection ?? []);
  const bundles = p.purchased_for_rental?.bundles ?? [];
  const bundled = new Set(bundles.includes('PEACE') || bundles.includes('TOTAL') ? ['LDW', 'PAI', 'PEC', 'RSN'] : []);
  if (!sel) return null;

  const submit = async () => {
    const req = await request('select_protection_plan', { plan_id: sel.id, term: chosenTerm, drivers: n }, `${sel.name} · ${chosenTerm}`);
    setReqId(req._id);
  };

  return (
    <ScrollView contentContainerStyle={styles.body}>
      {reqId ? (
        <RequestTracker id={reqId} onRetry={() => setReqId(null)} retryLabel="Pick another plan" />
      ) : (
        <>
          <SectionTitle title={`Protection at ${r.location_name}`} />
          <ChoiceRow options={list.map((d) => ({ value: d.id, label: d.name.replace(/ \(.*\)$/, ''), disabled: owned.has(d.id) || bundled.has(d.id) }))} value={sel.id} onChange={setPid} />
          <Card style={{ padding: 16, gap: 6, marginTop: 10 }}>
            <Text style={styles.h2}>{sel.name}</Text>
            <Text style={styles.meta}>{sel.covers} · {money(sel.price_pd)} per day</Text>
            {p.preferences.celebration && sel.tags.includes('celebration') ? <Pill label={`Great for your ${p.preferences.celebration}`} tone="accent" icon="gift" /> : null}
            {owned.has(sel.id) ? <Pill label="Already on your rental" tone="ok" icon="checkmark" /> : null}
            {bundled.has(sel.id) ? <Pill label="Included in your bundle" tone="ok" icon="checkmark" /> : null}
            {p.preferences.driving_needs?.length ? <Text style={styles.meta}>On file: {p.preferences.driving_needs.join(', ')}</Text> : null}
          </Card>
          <SectionTitle title="Term" />
          <ChoiceRow options={cat.protection_terms.map((t) => ({ value: t, label: t }))} value={chosenTerm} onChange={setTerm} />
          <Text style={styles.tiny}>{coveredDays} of your {r.days} rental day{r.days === 1 ? '' : 's'} covered.</Text>
          <SectionTitle title="Covered drivers" />
          <ChoiceRow options={Array.from({ length: adults }, (_, i) => String(i + 1)).map((v) => ({ value: v, label: v }))} value={String(n)} onChange={setDrivers} />
          <Text style={styles.tiny}>Every listed driver on the agreement is covered; {adults} adult{adults === 1 ? '' : 's'} on this reservation.</Text>
          <Card style={{ padding: 16, marginTop: 18, gap: 10 }}>
            <Text style={styles.total}>{money(sel.price_pd * coveredDays)}</Text>
            <Button label="Add protection" icon="shield-checkmark" disabled={owned.has(sel.id) || bundled.has(sel.id)} onPress={() => void submit()} />
            <Text style={styles.tiny}>Saved to Couchbase Lite first - confirmed when it syncs.</Text>
          </Card>
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  body: { padding: 16, maxWidth: 640, width: '100%', alignSelf: 'center', paddingBottom: 40 },
  h2: { fontSize: theme.type.xl, fontWeight: '700', fontFamily: theme.font.display, color: theme.color.brand },
  meta: { color: theme.color.muted, fontSize: theme.type.sm },
  total: { fontSize: 30, fontWeight: '900', color: theme.color.navy, textAlign: 'center' },
  tiny: { color: theme.color.faint, fontSize: theme.type.xs, textAlign: 'center' },
});
