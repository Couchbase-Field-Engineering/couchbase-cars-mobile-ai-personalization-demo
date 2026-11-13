import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { theme } from '@/src/theme';
import type { UpgradeOption } from '@/src/types';
import { Button, Card, Empty, Pill, SectionTitle, money } from '@/src/ui/components';
import { RequestTracker } from '@/src/ui/RequestTracker';

export default function Upgrade() {
  const params = useLocalSearchParams<{ class_code?: string; offer?: string }>();
  const { snap, request } = useData();
  const p = snap.profile;
  const upgradeOffer = snap.offers?.offers.find((o) => o.kind === 'upgrade');
  const options: UpgradeOption[] = upgradeOffer?.options ?? (snap.contexts.upgrade?.facts?.data?.offers as UpgradeOption[]) ?? [];
  const initial = options.find((o) => o.class_code === params.class_code) ?? options.find((o) => o.recommended) ?? options[0];
  const [code, setCode] = useState(initial?.class_code);
  const sel = options.find((o) => o.class_code === code);
  const [mode, setMode] = useState<'offer' | 'instant'>('offer');
  const [amount, setAmount] = useState<number>(Number(params.offer) || sel?.recommended_offer_pd || sel?.upgrade_offer_min_pd || 50);
  const [reqId, setReqId] = useState<string | null>(null);

  if (!p) return null;
  if (!options.length) return <Empty icon="car-outline" title="No upgrades available" body="You're in our best available car class for this rental - or the upgrade inventory for your pickup day is gone." />;
  const r = p.reservation;
  const n = r.days;
  const clampOffer = (v: number) => Math.max(sel?.upgrade_offer_min_pd ?? 0, Math.min((sel?.instant_price_pd ?? v) - 5, v));

  const submit = async () => {
    if (!sel) return;
    const req = mode === 'offer'
      ? await request('place_upgrade_offer', { class_code: sel.class_code, offer_per_day_usd: clampOffer(amount) }, `Couchbase Cars Upgrade offer · ${sel.class_name} · $${clampOffer(amount)}/day`)
      : await request('purchase_vehicle_upgrade', { class_code: sel.class_code }, `Upgrade to ${sel.class_name}`);
    setReqId(req._id);
  };

  return (
    <ScrollView contentContainerStyle={styles.body}>
      <Card style={{ padding: 16, gap: 4 }}>
        <Text style={styles.meta}>CURRENT VEHICLE</Text>
        <Text style={styles.h2}>{r.vehicle.class_name} · space {r.vehicle.space_number}</Text>
        <Text style={styles.meta}>{r.vehicle.example ?? ''}{r.vehicle.example ? ' · ' : ''}Level {r.vehicle.level} · {r.vehicle.lot} · {r.days} day{r.days === 1 ? '' : 's'} · {r.party_size} traveler{r.party_size === 1 ? '' : 's'}</Text>
      </Card>

      {reqId ? (
        <RequestTracker id={reqId} onRetry={() => setReqId(null)} />
      ) : (
        <>
          <SectionTitle title="Choose your upgrade" />
          {options.map((o) => (
            <Pressable key={o.class_code} onPress={() => { setCode(o.class_code); setAmount(o.recommended_offer_pd ?? o.upgrade_offer_min_pd); }} disabled={o.available <= 0}>
              <Card style={[styles.opt, code === o.class_code && styles.optSel, o.available <= 0 && { opacity: 0.45 }]}>
                <View style={{ flex: 1, gap: 4 }}>
                  <View style={{ flexDirection: 'row', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                    <Text style={styles.h3}>{o.class_name}</Text>
                    {o.recommended ? <Pill label="Recommended for you" tone="accent" icon="sparkles" /> : null}
                    <Pill label={o.available > 0 ? `${o.available} on the lot` : 'None left'} tone={o.available <= 2 ? 'warn' : 'neutral'} />
                  </View>
                  <Text style={styles.meta}>{[o.example, ...o.perks].filter(Boolean).join(' · ')}</Text>
                  <Text style={styles.meta}>Standby offer from {money(o.upgrade_offer_min_pd)}/day · or {money(o.instant_price_pd)}/day instantly</Text>
                </View>
                <Ionicons name={code === o.class_code ? 'radio-button-on' : 'radio-button-off'} size={22} color={theme.color.brand} />
              </Card>
            </Pressable>
          ))}

          {sel ? (
            <>
              <View style={styles.seg}>
                {(['offer', 'instant'] as const).map((m) => (
                  <Pressable key={m} onPress={() => setMode(m)} style={[styles.segBtn, mode === m && styles.segOn]}>
                    <Text style={[styles.segText, mode === m && { color: theme.color.navy }]}>{m === 'offer' ? 'Standby offer' : 'Upgrade now'}</Text>
                  </Pressable>
                ))}
              </View>
              <Card style={{ padding: 16, gap: 10 }}>
                {mode === 'offer' ? (
                  <>
                    <Text style={styles.meta}>Your standby offer per day. Charged only if a car in this class is on the lot when you arrive.</Text>
                    <View style={styles.stepper}>
                      <Pressable onPress={() => setAmount((b) => clampOffer(b - 5))} style={styles.step}><Ionicons name="remove" size={22} color={theme.color.navy} /></Pressable>
                      <Text style={styles.offer}>{money(clampOffer(amount))}</Text>
                      <Pressable onPress={() => setAmount((b) => clampOffer(b + 5))} style={styles.step}><Ionicons name="add" size={22} color={theme.color.navy} /></Pressable>
                    </View>
                    <Text style={[styles.meta, { textAlign: 'center' }]}>
                      Total if accepted: {money(clampOffer(amount) * n)} · min {money(sel.upgrade_offer_min_pd)}
                      {sel.recommended_offer_pd ? ` · suggested ${money(sel.recommended_offer_pd)}` : ''}
                    </Text>
                  </>
                ) : (
                  <>
                    <Text style={styles.meta}>Confirmed instantly, subject to availability.</Text>
                    <Text style={styles.offer}>{money(sel.instant_total_usd)}</Text>
                    <Text style={[styles.meta, { textAlign: 'center' }]}>{money(sel.instant_price_pd)} × {r.days} day{r.days === 1 ? '' : 's'}</Text>
                  </>
                )}
                <Button label={mode === 'offer' ? 'Place my offer' : 'Upgrade now'} icon="flash" onPress={() => void submit()} />
                <Text style={styles.tiny}>Works offline: your request is saved in Couchbase Lite and sent when you reconnect.</Text>
              </Card>
            </>
          ) : null}
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  body: { padding: 16, maxWidth: 640, width: '100%', alignSelf: 'center', paddingBottom: 40 },
  h2: { fontSize: theme.type.xl, fontWeight: '700', fontFamily: theme.font.display, color: theme.color.brand },
  h3: { fontSize: theme.type.lg, fontWeight: '800', color: theme.color.navy },
  meta: { color: theme.color.muted, fontSize: theme.type.sm },
  tiny: { color: theme.color.faint, fontSize: theme.type.xs, textAlign: 'center' },
  opt: { flexDirection: 'row', alignItems: 'center', gap: 10, padding: 14, marginBottom: 10, borderWidth: 2, borderColor: 'transparent' },
  optSel: { borderColor: theme.color.brand },
  seg: { flexDirection: 'row', backgroundColor: theme.color.surface, borderRadius: 999, padding: 4, marginVertical: 12, borderWidth: 1, borderColor: theme.color.border },
  segBtn: { flex: 1, paddingVertical: 10, borderRadius: 999, alignItems: 'center' },
  segOn: { backgroundColor: theme.color.brand },
  segText: { fontWeight: '800', color: theme.color.muted },
  stepper: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 22 },
  step: { width: 44, height: 44, borderRadius: 22, backgroundColor: theme.color.oceanSoft, alignItems: 'center', justifyContent: 'center' },
  offer: { fontSize: 38, fontWeight: '900', color: theme.color.navy, textAlign: 'center' },
});
