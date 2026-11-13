import { router } from 'expo-router';
import type { Offer, SuggestedAction } from '../types';
import type { IconName } from './components';

export const KIND_ICON: Record<string, IconName> = {
  upgrade: 'car-sport',
  extra: 'cube',
  protection: 'shield-checkmark',
  bundle: 'speedometer',
  service: 'hand-left',
  checkin: 'qr-code',
};

export const KIND_LABEL: Record<string, string> = {
  upgrade: 'Vehicle upgrade',
  extra: 'Extra',
  protection: 'Protection',
  bundle: 'Bundle',
  service: 'Couchbase Cars Services',
  checkin: 'Before you pick up',
};

/** Open the screen behind an offer or concierge suggestion. */
export function openAction(a: SuggestedAction | Offer['cta'], title?: string, price?: string) {
  if (a.screen) {
    router.push({ pathname: `/${a.screen}` as never, params: Object.fromEntries(Object.entries(a.args ?? {}).map(([k, v]) => [k, String(v)])) });
    return;
  }
  if (a.tool) {
    router.push({
      pathname: '/confirm',
      params: { tool: a.tool, args: JSON.stringify(a.args ?? {}), title: title ?? a.label, price: price ?? '' },
    });
  }
}
