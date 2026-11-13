import { Ionicons } from '@expo/vector-icons';
import { ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { API_URL } from '@/src/config';
import { useData } from '@/src/data/DataContext';
import { useAuth } from '@/src/session/AuthContext';
import { theme } from '@/src/theme';
import { Button, Card, Pill, SectionTitle, SyncBadge, type IconName } from '@/src/ui/components';

const SCORES: [string, string][] = [
  ['upgrade_propensity', 'Vehicle upgrade'],
  ['extras_propensity', 'Extras'],
  ['protection_propensity', 'Protection'],
  ['services_propensity', 'Services'],
  ['fuel_propensity', 'Prepaid fuel'],
  ['toll_propensity', 'e-Toll'],
  ['wifi_propensity', 'Wi-Fi hotspot'],
];

export default function Profile() {
  const { snap, sync, offline, setOffline, dbLocation } = useData();
  const { signOut, session } = useAuth();
  const insets = useSafeAreaInsets();
  const p = snap.profile;
  const s = p?.ml_scores;

  return (
    <ScrollView style={{ flex: 1, backgroundColor: theme.color.bg }} contentContainerStyle={[styles.body, { paddingTop: insets.top + 12 }]}>
      <Text style={styles.h1}>Profile</Text>
      {p ? (
        <Card style={{ padding: 16, marginTop: 12, gap: 6 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
            <View style={styles.avatar}><Text style={{ fontWeight: '900', color: theme.color.navy, fontSize: 18 }}>{p.first_name[0]}{p.last_name[0]}</Text></View>
            <View style={{ flex: 1 }}>
              <Text style={styles.name}>{p.first_name} {p.last_name}</Text>
              <Text style={styles.meta}>{p.email ?? 'Customer'} · {p.home_city}</Text>
            </View>
          </View>
          <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
            <Pill label={`${p.loyalty.tier}`} tone="gold" icon="star" />
            <Pill label={`${p.loyalty.points} points`} tone="neutral" />
            <Pill label={`${p.loyalty.rentals_completed} rentals`} tone="neutral" />
            <Pill label={`Member since ${p.loyalty.member_since}`} tone="neutral" />
          </View>
        </Card>
      ) : null}

      {p ? (
        <>
          <SectionTitle title="What you love" />
          <Card style={{ padding: 16, gap: 10 }}>
            <View style={styles.wrap}>{p.preferences.interests.map((i) => <Pill key={i} label={i} tone="ocean" />)}</View>
            <Row icon="car-outline" label="Driving needs" value={(p.preferences.driving_needs ?? []).join(', ') || 'None noted'} />
            <Row icon="flash-outline" label="Fuel type" value={p.preferences.fuel_type ?? 'any'} />
            <Row icon="gift-outline" label="Celebrating" value={p.preferences.celebration ?? '—'} />
            <Row icon="people-outline" label="Traveling with kids" value={p.preferences.travels_with_kids ? 'Yes' : 'No'} />
          </Card>

          <SectionTitle title="How we personalize" />
          <Card style={{ padding: 16, gap: 8 }}>
            <Row icon="analytics-outline" label="Source" value={`Amazon Redshift unload · ${p.export_date}`} />
            <Row icon="git-branch-outline" label="Scores" value={`Redshift ML · ${String(s?.model_version)}`} />
            {p.segments?.length ? (
              <Row icon="layers-outline" label="Segments" value={p.segments.map((a) => a.name).join(' · ')} />
            ) : null}
            <Row icon="people-circle-outline" label="Segment" value={String(s?.segment)} />
            <Row icon="navigate-outline" label="Next best action" value={String(s?.next_best_action).replace(/_/g, ' ')} />
            {SCORES.map(([k, label]) => {
              const v = Number(s?.[k] ?? 0);
              return (
                <View key={k} style={{ gap: 3 }}>
                  <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                    <Text style={styles.meta}>{label}</Text>
                    <Text style={[styles.meta, { fontWeight: '700' }]}>{Math.round(v * 100)}%</Text>
                  </View>
                  <View style={styles.bar}><View style={[styles.barFill, { width: `${Math.round(v * 100)}%` }]} /></View>
                </View>
              );
            })}
            <Text style={styles.tiny}>Profile revision {p.rev} - bumps with every booking, which invalidates your concierge context cache.</Text>
          </Card>
        </>
      ) : null}

      <SectionTitle title="Offline & sync" />
      <Card style={{ padding: 16, gap: 10 }}>
        <SyncBadge sync={sync} />
        <Row icon="server-outline" label="Local database" value={sync.engine === 'couchbase-lite' ? 'Couchbase Lite' : 'Browser preview (in-memory)'} />
        <Row icon="folder-outline" label="Location" value={dbLocation ?? '—'} />
        <Row icon="swap-vertical-outline" label="Replicating with" value={sync.endpoint ?? '—'} />
        <Row icon="time-outline" label="Last sync" value={sync.lastSyncAt ? new Date(sync.lastSyncAt).toLocaleTimeString() : '—'} />
        <Row icon="cloud-upload-outline" label="Waiting to send" value={String(sync.pendingPush)} />
        {sync.detail ? <Text style={[styles.tiny, { color: theme.color.danger }]}>{sync.detail}</Text> : null}
        <View style={styles.switchRow}>
          <View style={{ flex: 1 }}>
            <Text style={{ fontWeight: '800', color: theme.color.text }}>In the garage - no signal</Text>
            <Text style={styles.meta}>Pause replication to demo the airport garage dead zone: browse, add extras, make an upgrade offer and ask the concierge from Couchbase Lite. Requests queue and send when you switch back.</Text>
          </View>
          <Switch value={offline} onValueChange={setOffline} trackColor={{ true: theme.color.brand, false: theme.color.border }} thumbColor={theme.color.surface} />
        </View>
      </Card>

      <SectionTitle title="Couchbase Labs Agent Operations Manager" />
      <Card style={{ padding: 16, gap: 8 }}>
        <Text style={styles.meta}>
          Every booking you make here becomes a request that the Couchbase Cars Rental Concierge agent runs through Couchbase Labs Agent Operations Manager: RBAC and tool scope,
          human approval for goodwill upgrades, a trace and an audit entry. Concierge answers use Couchbase Labs Agent Operations Manager's Knowledge Base, memory and LLM cache.
        </Text>
        <Row icon="link-outline" label="Backend" value={API_URL} />
        <Row icon="finger-print-outline" label="Customer ID" value={session?.customer_id ?? '—'} />
      </Card>

      <View style={{ marginVertical: 24 }}>
        <Button label="Sign out" kind="ghost" icon="log-out-outline" onPress={() => void signOut()} />
      </View>
    </ScrollView>
  );
}

function Row({ icon, label, value }: { icon: IconName; label: string; value: string }) {
  return (
    <View style={{ flexDirection: 'row', gap: 10, alignItems: 'flex-start' }}>
      <Ionicons name={icon} size={16} color={theme.color.brand} style={{ marginTop: 1 }} />
      <Text style={[styles.meta, { width: 120 }]}>{label}</Text>
      <Text style={{ flex: 1, color: theme.color.text, fontWeight: '600' }} selectable>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  body: { padding: 16, maxWidth: 640, width: '100%', alignSelf: 'center' },
  h1: { fontSize: theme.type.title, fontWeight: '900', color: theme.color.navy },
  avatar: { width: 52, height: 52, borderRadius: 26, backgroundColor: theme.color.oceanSoft, alignItems: 'center', justifyContent: 'center' },
  name: { fontSize: theme.type.xl, fontWeight: '900', color: theme.color.navy },
  meta: { color: theme.color.muted, fontSize: theme.type.sm },
  tiny: { color: theme.color.faint, fontSize: theme.type.xs },
  wrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  bar: { height: 6, borderRadius: 3, backgroundColor: theme.color.bg, overflow: 'hidden' },
  barFill: { height: 6, borderRadius: 3, backgroundColor: theme.color.ocean },
  switchRow: { flexDirection: 'row', gap: 12, alignItems: 'center', borderTopWidth: 1, borderTopColor: theme.color.border, paddingTop: 12, marginTop: 4 },
});
