import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { ScrollView, StyleSheet, Text } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { theme } from '@/src/theme';
import { Button, Card, fmtDate, Pill, SectionTitle, money } from '@/src/ui/components';
import { ChoiceRow } from '@/src/ui/Choice';
import { RequestTracker } from '@/src/ui/RequestTracker';

const TIMES = ['07:00', '08:00', '10:00', '12:00', '14:00', '16:00', '18:00'];

export default function Service() {
  const params = useLocalSearchParams<{ service_id?: string }>();
  const { snap, request } = useData();
  const [sid, setSid] = useState<string | undefined>(params.service_id);
  const [date, setDate] = useState<string | undefined>();
  const [time, setTime] = useState<string | undefined>('10:00');
  const [reqId, setReqId] = useState<string | null>(null);
  const p = snap.profile;
  const cat = snap.catalog;
  if (!p || !cat) return null;
  const all = p.reservation.stops;
  const sel = cat.services.find((s) => s.id === sid) ?? cat.services[0];
  // Delivery is a pickup-day service, collection and late return are return-day services; the rest can be any day.
  const days = sel.when === 'pickup' ? all.slice(0, 1) : sel.when === 'return' ? all.slice(-1) : all;
  const day = days.find((d) => d.date === date) ?? days[0];
  const peak = day.type === 'pickup' || day.type === 'dropoff';
  const price = peak ? sel.price : Math.round(sel.price * 0.8);
  const label = (d: typeof all[number]) =>
    `${fmtDate(d.date, { weekday: 'short', day: 'numeric' })} · ${d.type === 'drive' ? 'On the road' : d.type === 'pickup' ? 'Pickup day' : d.type === 'dropoff' ? 'Return day' : d.stop.split(',')[0]}`;

  const submit = async () => {
    const req = await request('book_rental_service', { service_id: sel.id, date: day.date, time }, `${sel.name} · ${fmtDate(day.date)} ${time}`);
    setReqId(req._id);
  };

  return (
    <ScrollView contentContainerStyle={styles.body}>
      {reqId ? <RequestTracker id={reqId} onRetry={() => setReqId(null)} /> : (
        <>
          <SectionTitle title="Service" />
          <ChoiceRow options={cat.services.map((s) => ({ value: s.id, label: s.name }))} value={sel.id} onChange={setSid} />
          <SectionTitle title="Day" />
          <ChoiceRow options={days.map((d) => ({ value: d.date, label: label(d) }))} value={day.date} onChange={setDate} />
          <SectionTitle title="Time" />
          <ChoiceRow options={TIMES.map((t) => ({ value: t, label: t }))} value={time} onChange={setTime} />
          <Card style={{ padding: 16, marginTop: 18, gap: 10 }}>
            <Text style={styles.total}>{money(price)}</Text>
            {!peak ? <Pill label="Mid-rental price · 20% off" tone="ok" icon="pricetag" /> : null}
            <Button label="Book service" icon="hand-left" onPress={() => void submit()} />
            <Text style={styles.tiny}>Saved to Couchbase Lite first - confirmed when it syncs.</Text>
          </Card>
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  body: { padding: 16, maxWidth: 640, width: '100%', alignSelf: 'center', paddingBottom: 40 },
  total: { fontSize: 30, fontWeight: '900', color: theme.color.navy, textAlign: 'center' },
  tiny: { color: theme.color.faint, fontSize: theme.type.xs, textAlign: 'center' },
});
