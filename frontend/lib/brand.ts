/**
 * The handful of brand values that have to exist outside Tailwind.
 *
 * Everything on the site is styled with Tailwind classes, which resolve in a
 * browser. Two things cannot use them: the generated social image and the
 * generated Apple icon, both of which are rendered by satori at build time from
 * inline styles and never see a stylesheet. Writing the hex codes into those
 * two files would be two more places for the palette to drift, so they are here
 * once, named after the Tailwind colours they mirror.
 *
 * These are the colours already used across the site: `slate-900`/`slate-950`
 * for the dark surfaces, `sky-500`/`sky-400`/`sky-300` for the accent, and
 * `slate-300`/`slate-400` for secondary text.
 */
export const BRAND_COLORS = {
  slate950: '#020617',
  slate900: '#0f172a',
  slate800: '#1e293b',
  slate400: '#94a3b8',
  slate300: '#cbd5e1',
  white: '#ffffff',
  sky300: '#7dd3fc',
  sky400: '#38bdf8',
  sky500: '#0ea5e9',
} as const;

/**
 * The three ascending bars of the site mark, in the 64-unit grid
 * `app/icon.svg` draws them on. Heights are the drawn height of each bar.
 */
export const ICON_BARS = [
  { height: 16, fill: BRAND_COLORS.sky300 },
  { height: 26, fill: BRAND_COLORS.sky400 },
  { height: 36, fill: BRAND_COLORS.sky500 },
] as const;
