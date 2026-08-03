/**
 * Where a Launch Demo button points, and which module it opens.
 *
 * One helper, used by every demonstration link on the site, so that the ten
 * module destinations are ten *values* rather than ten URLs scattered through
 * the components. `buildDemoUrl()` is the general demonstration home page;
 * `buildDemoUrl('po-risk')` is one module.
 *
 * Three things this module is deliberately strict about:
 *
 * * **The module identifier is an allowlist, never a passthrough.** The value
 *   ends up in a URL that a visitor follows, and the Streamlit application on
 *   the other end turns it into a page. Neither end may accept an arbitrary
 *   string, and the frontend half of that agreement is `DEMO_MODULE_IDS`.
 * * **The origin is validated, not trusted.** `NEXT_PUBLIC_DEMO_URL` is a
 *   build argument, and a build argument is one mis-set environment file away
 *   from being `javascript:alert(1)` in the `href` of a button on every page.
 *   Anything that is not `https:` - or `http:` on a loopback host, which is
 *   what `npm run dev` really uses - is refused and the placeholder is used
 *   instead.
 * * **The identifier is navigation, and nothing else.** It says which page to
 *   open. It is not authentication, it is not authorisation, and it proves
 *   nothing about who is following the link. Cloudflare Access protects the
 *   whole demonstration hostname, in front of the application, and it is what
 *   decides whether the request reaches Streamlit at all.
 *
 * @see `streamlit_app/components/routing.py` - the other half of the contract.
 * @see `tests/integration/test_demo_module_contract.py` - the test that keeps
 *   the two lists identical.
 */

import { PUBLIC_DEMO_ORIGIN, siteConfig } from '@/lib/site';

/**
 * The query parameter the protected application reads.
 *
 * Named here rather than written into a template string, because the Python
 * side names it too and a test compares the two.
 */
export const DEMO_MODULE_PARAM = 'module';

/**
 * The ten public module identifiers.
 *
 * Stable public values, and that is their whole job: an identifier appears in
 * a URL somebody may bookmark or paste into an email, so it may not be derived
 * from a display name, a slug, a file name or a Python import path - all four
 * of which are free to change without the URL changing meaning.
 *
 * `as const` makes this a union type rather than `string[]`, so a component
 * asking for a module the platform does not have fails `npm run typecheck`
 * rather than rendering a link the application will refuse.
 */
export const DEMO_MODULE_IDS = [
  'po-risk',
  'spend-analytics',
  'supplier-recommendation',
  'invoice-validator',
  'supplier-risk',
  'contract-assistant',
  'inventory-predictor',
  'test-case-generator',
  'blueprint-generator',
  'interview-coach',
] as const;

/** One of the ten identifiers above. */
export type DemoModuleId = (typeof DEMO_MODULE_IDS)[number];

/**
 * Where a demonstration link points when the configured value cannot be used.
 *
 * The production origin, and **never a loopback placeholder**. The usual
 * argument for a placeholder default - that a wrong domain is worse than a
 * visibly unconfigured link - does not hold for this one value, because there
 * is nothing visible about the failure it produces. A public page whose Launch
 * Demo button says `http://localhost:8501` does not read as unconfigured to the
 * visitor who clicks it: it is a link to *their own machine*, which either
 * refuses the connection or opens whatever they happen to be running on that
 * port. A missing variable in a deployment must send people to the real
 * demonstration.
 *
 * Note what this is not: it is not a claim that the demonstration is
 * unprotected, and it is not a canonical address. `lib/metadata.ts` refuses
 * this hostname for canonicals, and Cloudflare Access stands in front of it.
 */
export const DEFAULT_DEMO_ORIGIN = PUBLIC_DEMO_ORIGIN;

/**
 * Hosts that may still be reached over plain `http:`.
 *
 * `npm run dev` runs the Streamlit application on `http://localhost:8501`, and
 * refusing that would mean the local site could not link to the local demo. So
 * a loopback address is *accepted when it is configured* - it is never reached
 * by default, which is the whole distinction: localhost is a destination
 * somebody asked for, never one this file falls back to.
 *
 * Everything else must be `https:`. This is a property of the *address*, not of
 * `NODE_ENV`, because an environment-dependent branch in a security check is
 * one mis-set variable away from being live in the wrong place.
 */
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]', '::1']);

/** Whether a value is one of the ten identifiers this site may link to. */
export function isDemoModuleId(value: unknown): value is DemoModuleId {
  return typeof value === 'string' && (DEMO_MODULE_IDS as readonly string[]).includes(value);
}

/**
 * Reduce a configured demonstration address to the one form links are built
 * from, or report that it cannot be used.
 *
 * Returns `null` rather than a repaired guess, exactly as
 * `normalizePublicOrigin` in `lib/metadata.ts` does: the caller then falls back
 * to a known-good value instead of this function inventing one from input it
 * has already decided to distrust.
 *
 * What normalisation means here:
 *
 * * a scheme other than `https:` - or `http:` on a loopback host - is refused,
 *   which is what rules out `javascript:`, `data:` and `file:`;
 * * credentials in the URL are refused: `https://user:pass@host/` in a public
 *   button is either a mistake or an attempt to make a link read as one host
 *   while reaching another;
 * * a fragment is dropped, because the demonstration has no anchors and a `#`
 *   arriving from configuration is a stray character;
 * * the path is collapsed and always ends in a single `/`, so that a value
 *   given with a trailing slash and one given without produce the same link.
 */
export function normalizeDemoOrigin(value: string): string | null {
  let parsed: URL;
  try {
    parsed = new URL(value.trim());
  } catch {
    return null;
  }

  const isLoopback = LOOPBACK_HOSTS.has(parsed.hostname.toLowerCase());
  if (parsed.protocol !== 'https:' && !(parsed.protocol === 'http:' && isLoopback)) {
    return null;
  }
  if (parsed.username || parsed.password) {
    return null;
  }

  parsed.hash = '';
  const path = parsed.pathname.replace(/\/{2,}/g, '/').replace(/\/*$/, '/');
  parsed.pathname = path;
  return parsed.toString();
}

/**
 * The demonstration address every link on this site is built from, resolved
 * once at module load.
 *
 * Two layers, and both fall back to the same public origin. `siteConfig.demoUrl`
 * has already turned "blank", "whitespace" and "absent" into
 * `PUBLIC_DEMO_ORIGIN`; this turns "malformed", "wrong scheme" and "carries
 * credentials" into it as well. Nothing reaches a visitor's own machine unless
 * a loopback address was explicitly configured.
 *
 * The second `normalizeDemoOrigin` call cannot fail - `DEFAULT_DEMO_ORIGIN` is
 * a literal `https:` origin - and the `??` after it exists only so the type is
 * `string` rather than `string | null`.
 */
export const demoBaseUrl: string =
  normalizeDemoOrigin(siteConfig.demoUrl) ??
  normalizeDemoOrigin(DEFAULT_DEMO_ORIGIN) ??
  `${DEFAULT_DEMO_ORIGIN}/`;

/**
 * The URL of the protected demonstration, optionally for one module.
 *
 * ```
 * buildDemoUrl()            https://demo.solveaihub.com/
 * buildDemoUrl('po-risk')   https://demo.solveaihub.com/?module=po-risk
 * ```
 *
 * Built with the URL API rather than by concatenation, so the query value is
 * encoded by something that knows how to encode query values, and any query
 * string already present in the configured address is preserved rather than
 * being overwritten by a hand-written `?`.
 *
 * An unrecognised identifier produces the *general* demonstration URL rather
 * than an error. TypeScript already rejects one at the call site; this is the
 * runtime half, for a value that arrives from somewhere the compiler cannot
 * see. Dropping it is the safe direction - the visitor reaches the
 * demonstration home page, which is a working destination, instead of a link
 * carrying a value the application will refuse anyway.
 */
export function buildDemoUrl(module?: DemoModuleId | null): string {
  const url = new URL(demoBaseUrl);
  if (isDemoModuleId(module)) {
    url.searchParams.set(DEMO_MODULE_PARAM, module);
  }
  return url.toString();
}
