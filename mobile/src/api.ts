import { API_URL } from './config';

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

export async function api<T>(path: string, opts: { method?: string; body?: unknown; token?: string | null; timeoutMs?: number } = {}): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), opts.timeoutMs ?? 30000);
  try {
    const res = await fetch(`${API_URL}${path}`, {
      method: opts.method ?? (opts.body ? 'POST' : 'GET'),
      headers: {
        'Content-Type': 'application/json',
        ...(opts.token ? { Authorization: `Bearer ${opts.token}` } : {}),
      },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      signal: ctrl.signal,
    });
    const text = await res.text();
    const data = text ? JSON.parse(text) : {};
    if (!res.ok) throw new ApiError(typeof data.detail === 'string' ? data.detail : `HTTP ${res.status}`, res.status);
    return data as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new ApiError("Can't reach Couchbase Cars right now - you're offline.", 0);
  } finally {
    clearTimeout(timer);
  }
}

export type Persona = {
  customer_id: string;
  name: string;
  last_name: string;
  booking_id: string;
  location: string;
  pickup_date: string;
  days_to_pickup: number;
  tier: string;
  vehicle: string;
  blurb: string;
};

export type LoginResponse = {
  token: string;
  customer_id: string;
  customer: { first_name: string; last_name: string; tier: string; email: string | null };
  channels: string[];
  sync_gateway: { session_id: string; cookie_name: string; expires: string; db: string; url: string | null } | null;
  export_date: string;
};
