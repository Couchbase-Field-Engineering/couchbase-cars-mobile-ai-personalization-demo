/** Document shapes replicated from Couchbase (scope `rental`) into Couchbase Lite. */

export type Stop = {
  day: number;
  date: string;
  stop_code: string;
  stop: string;
  arrive: string | null;
  depart: string | null;
  type: 'pickup' | 'dropoff' | 'drive' | 'stop';
};

export type Vehicle = {
  space_number: string;
  level: number;
  class_code: string;
  class_name: string;
  lot: string;
  location: string;
  example?: string;
};

export type Profile = {
  type: 'profile';
  customer_id: string;
  export_date: string;
  rev: number;
  first_name: string;
  last_name: string;
  email: string | null;
  age_band: string;
  home_city: string;
  loyalty: { program: string; tier: string; points: number; rentals_completed: number; member_since: string };
  reservation: {
    booking_id: string;
    rental_id: string;
    location_code: string;
    location_name: string;
    trip_name: string;
    trip_purpose?: string;
    days: number;
    pickup_location: string;
    pickup_date: string;
    return_date: string;
    stops: Stop[];
    party_size: number;
    party: { customer_id: string; name: string; age_band: string; relationship: string }[];
    vehicle: Vehicle;
    checkin_status: 'complete' | 'not_started';
    pickup_slot: string | null;
    fuel_option: string;
  };
  preferences: {
    interests: string[];
    driving_needs: string[];
    celebration: string | null;
    transmission?: string;
    fuel_type?: string;
    vehicle_pref?: string | null;
    travels_with_kids: boolean;
  };
  history: { avg_ancillary_spend_usd: number; lifetime_value_usd: number; past_rentals: unknown[] };
  purchased_for_rental: { bundles: string[]; extras: string[]; protection: string[]; services: string[] };
  ml_scores: Record<string, number | string | null> & { model_version: string; segment: string; next_best_action: string };
  // Amazon Redshift customer 360: resolved identity and realized segment memberships
  identity?: { ecid?: string; customer_id: string; crm_id?: string; namespace?: string };
  segments?: { id: string; name: string; status?: string }[];
};

export type UpgradeOption = {
  class_code: string;
  class_name: string;
  example?: string;
  available: number;
  instant_price_pd: number;
  instant_total_usd: number;
  upgrade_offer_min_pd: number;
  perks: string[];
  recommended: boolean;
  recommended_offer_pd: number | null;
};

export type Offer = {
  offer_id: string;
  kind: 'upgrade' | 'extra' | 'protection' | 'bundle' | 'service' | 'checkin';
  palette: string;
  title: string;
  subtitle: string;
  reason: string;
  price_label: string;
  score: number;
  rank: number;
  cta: { label: string; screen?: string; tool?: string; args?: Record<string, unknown> };
  options?: UpgradeOption[];
  days?: number;
  party_size?: number;
};

export type OffersDoc = {
  type: 'offers';
  offers: Offer[];
  model_version: string;
  segment: string;
  export_date: string;
  generated_at: string;
  /** Which protection plans the pickup location offers: {plan_id: boolean}. */
  protection_available?: Record<string, boolean>;
};

export type BookingItem = {
  item_id: string;
  kind: string;
  title: string;
  status: string;
  date?: string;
  time?: string;
  charge_usd?: number;
  booked_at: string;
};

export type RequestStatus = 'pending' | 'processing' | 'awaiting_approval' | 'confirmed' | 'accepted' | 'submitted' | 'failed';

export type ActionRequest = {
  _id: string;
  type: 'request';
  customer_id: string;
  tool: string;
  args: Record<string, unknown>;
  title: string;
  status: RequestStatus;
  created_at: string;
  summary?: string;
  charge_usd?: number;
  governed?: boolean;
  trace_id?: string | null;
  /** Couchbase Labs Agent Operations Manager agent identity that ran it: the concierge, or the Vehicle Upgrade Agent for upgrades. */
  agent?: 'cbcars-rental-concierge' | 'cbcars-upgrade-agent' | string;
  memories_recalled?: number;
  remembered?: boolean;
  approval_id?: string | null;
  completed_at?: string | null;
  _local?: boolean; // created on this device, not yet acknowledged by the server
};

export type ChatMessage = {
  id: string;
  role: 'customer' | 'concierge';
  text: string;
  at: string;
  intent?: string;
  actions?: SuggestedAction[];
  context?: {
    status: string; latency_ms: number; kb_mode?: string; build_ms?: number;
    // the Redshift Data API round trip made while building this context
    redshift?: { mode: string; latency_ms: number; segments: string[] } | null;
  };
  llm?: { status: string; namespace?: string; similarity?: number | null; latency_ms?: number | null; stub?: boolean; composed_locally?: boolean };
  sources?: { title: string; snippet: string; kind: string }[];
  offline?: boolean;
  pending?: boolean;
};

export type SuggestedAction = { label: string; tool?: string; screen?: string; args?: Record<string, unknown> };

export type ChatDoc = { type: 'concierge'; messages: ChatMessage[]; answers: Record<string, { reply: string; intent: string; at: string }> };

export type ContextDoc = {
  type: 'context_cache';
  intent: string;
  personal: boolean;
  export_date: string;
  built_at: string;
  build_ms: number;
  kb_mode: string;
  kb_profile: { title: string; content: string }[];
  kb_playbook: { title: string; content: string; answer?: string }[];
  facts: { tool?: string; data?: any };
};

export type Catalog = {
  type: 'catalog';
  export_date: string;
  car_classes: { code: string; name: string; rank: number; base_pd: number; perks: string[] }[];
  extras: { id: string; name: string; price: number; per: string; locations: string[] | '*'; stops?: string[]; tags: string[] }[];
  protection: { id: string; name: string; covers: string; price_pd: number; locations: string[] | '*'; tags: string[] }[];
  protection_terms: string[];
  bundles: { code: string; name: string; price_per_day: number; per: string; blurb: string }[];
  services: { id: string; name: string; price: number; minutes: number; when: 'pickup' | 'return' | 'any'; tags: string[] }[];
  pickup_slots: string[];
  stops: Record<string, string>;
  locations: Record<string, { name: string; city: string; lots: string[] }>;
  loyalty_tiers: string[];
  faq: { q: string; a: string; keywords: string[] }[];
};

export type SyncState = {
  engine: 'couchbase-lite' | 'preview';
  status: 'connecting' | 'connected' | 'idle' | 'busy' | 'offline' | 'paused' | 'error' | 'stopped';
  lastSyncAt: number | null;
  pendingPush: number;
  detail?: string;
  endpoint?: string;
};
