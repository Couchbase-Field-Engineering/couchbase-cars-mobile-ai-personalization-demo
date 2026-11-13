import { Platform, type ViewStyle } from 'react-native';

/**
 * Styled after couchbase.com (Nov 2026): black ink and black hero surfaces,
 * Couchbase red (#EC1218) for the primary call to action, links and brand
 * accents, white cards on a warm peach-tinted page (#FFF0DA family), orange
 * (#FC9D0C) as the secondary accent, and 12-15px rounded corners. The site
 * sets body copy in Inter and headlines in Centra No2; Centra is a licensed
 * face, so Inter (loaded on web) and the platform sans stand in for it.
 * `gold` is the site's orange, kept for Couchbase Cars Preferred loyalty pills.
 */
const shadowCard: ViewStyle = Platform.select({
  ios: { shadowColor: '#000000', shadowOpacity: 0.12, shadowRadius: 14, shadowOffset: { width: 0, height: 6 } },
  android: { elevation: 3 },
  default: { boxShadow: '0 6px 18px rgba(0,0,0,0.12)' } as ViewStyle,
}) as ViewStyle;

export const theme = {
  color: {
    navy: '#000000',          // couchbase.com black (dark surfaces, hero)
    navyDeep: '#000000',
    brand: '#EC1218',         // Couchbase red: brand accents, icons, links
    brandBright: '#FF3B40',
    accent: '#EC1218',        // couchbase.com call-to-action red
    accentSoft: '#FDE5E6',
    gold: '#FC9D0C',          // couchbase.com orange: Preferred loyalty only
    goldSoft: '#FFF0DA',      // couchbase.com peach
    ocean: '#333333',         // dark grey: informational pills and sync chips
    oceanSoft: '#F3ECE0',     // pale cream panels
    bg: '#FFF8EC',            // light tint of couchbase.com peach
    surface: '#FFFFFF',
    text: '#000000',          // couchbase.com ink
    muted: '#555555',
    faint: '#858585',
    border: '#EAD8BE',        // couchbase.com mid cream
    ok: '#13804B',
    okSoft: '#E6F6EE',
    warn: '#B26200',
    warnSoft: '#FFF0DA',
    danger: '#7C0206',        // couchbase.com dark red
    dangerSoft: '#FBE4E4',
    onDark: '#FFFFFF',
    onDarkMuted: 'rgba(255,255,255,0.74)',
  },
  gradient: {
    hero: ['#000000', '#7C0206'] as const,
    luxury: ['#7C0206', '#EC1218'] as const,
    road: ['#000000', '#555555'] as const,
    protection: ['#0E4F3A', '#2F9E6B'] as const,
    fuel: ['#EC1218', '#FC9D0C'] as const,
    service: ['#333333', '#9B9382'] as const,
    counter: ['#000000', '#333333'] as const,
  },
  // couchbase.com: Inter for body, Centra No2 (licensed) for headlines.
  font: {
    display: Platform.select({ ios: 'System', android: 'sans-serif', default: "Inter, 'Helvetica Neue', Helvetica, Arial, sans-serif" }) as string,
  },
  space: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 },
  type: { xs: 11, sm: 13, md: 15, lg: 17, xl: 20, title: 26, hero: 34 },
  radius: 15,
  radiusSm: 10,
  shadow: { card: shadowCard },
} as const;

export type GradientKey = keyof typeof theme.gradient;
