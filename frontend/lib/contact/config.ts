/**
 * Server-side configuration for the contact form.
 *
 * Nothing in this module may ever be imported by a client component. It reads
 * `SMTP_APP_PASSWORD`, the Turnstile secret and the rate-limit HMAC key, and a
 * single import from a `'use client'` file would compile all three into the
 * browser bundle. `components/ContactForm.tsx` therefore receives everything it
 * needs as props from a server component, and `tests/contact-config.test.ts`
 * asserts the import graph stays that way.
 *
 * Every value is read inside a function rather than at module scope. Reading at
 * module scope would freeze the configuration at import time, which breaks two
 * things at once: tests that set `process.env` per case, and the standalone
 * server, where these variables arrive at run time rather than at build time.
 *
 * The one exception is `NEXT_PUBLIC_TURNSTILE_SITE_KEY`, which is public by
 * definition and is *inlined by `next build`*. It is referenced as a complete
 * literal expression below because that is the only form the compiler
 * substitutes - destructuring `process.env` or building the name dynamically
 * yields `undefined` in the browser. It follows that changing the site key
 * requires rebuilding the image, exactly as `NEXT_PUBLIC_DEMO_URL` does.
 */

/** How the form is allowed to fail: absent configuration, never a partial one. */
export type ContactReadiness =
  | { ready: true; config: ContactConfig }
  | { ready: false; missing: readonly string[] };

export type ContactConfig = {
  readonly recipient: string;
  readonly smtp: {
    readonly host: string;
    readonly port: number;
    readonly secure: boolean;
    readonly user: string;
    readonly password: string;
    readonly from: string;
  };
  readonly turnstile: {
    readonly secret: string;
    /**
     * Hostnames a token may legitimately have been solved on.
     *
     * Cloudflare reports the hostname the widget ran on, and checking it is
     * what stops a token minted on an attacker's own page - using this site
     * key, which is public by design - being replayed here. Empty means the
     * check is skipped, which is the local-development case.
     */
    readonly expectedHostnames: readonly string[];
    /** The `action` the widget declares, or `''` to skip the check. */
    readonly expectedAction: string;
  };
  readonly rateLimit: {
    readonly maxPerWindow: number;
    readonly windowMs: number;
    readonly secret: string;
  };
};

/** Window length when `CONTACT_RATE_LIMIT_WINDOW_SECONDS` is unset. */
export const DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 3600;

/** Requests per window per bucket when `CONTACT_RATE_LIMIT_MAX` is unset. */
export const DEFAULT_RATE_LIMIT_MAX = 5;

function trimmed(value: string | undefined): string {
  return value?.trim() ?? '';
}

/**
 * Read a boolean flag, treating blank as absent.
 *
 * Mirrors `flagFromEnv` in `lib/site.ts` deliberately rather than importing it:
 * that module is imported by client components, and this one must never be.
 */
function flag(value: string | undefined, fallback: boolean): boolean {
  const normalised = value?.trim().toLowerCase();
  if (!normalised) {
    return fallback;
  }
  return !['false', '0', 'no', 'off'].includes(normalised);
}

/**
 * Whether the operator has asked for the form at all.
 *
 * Defaults to `false`. The deployed site keeps its `mailto:` behaviour until
 * somebody sets this, so merging the form changes nothing that is already
 * running until the deployment opts in.
 */
export function isContactFormRequested(): boolean {
  return flag(process.env.CONTACT_FORM_ENABLED, false);
}

/**
 * The public Turnstile site key, or `''` when the image was built without one.
 *
 * Build-time inlined - see the note at the top of this file.
 */
export function turnstileSiteKey(): string {
  return trimmed(process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY);
}

/**
 * Parse a positive integer, falling back rather than reinterpreting.
 *
 * A malformed value falls back to the default rather than to "no limit". The
 * failure mode of a typo in an environment file must not be an open endpoint.
 *
 * The digits-only test is not redundant with `Number.parseInt`. `parseInt`
 * stops at the first character it does not understand and reports success on
 * what it read, so `'3.5'` becomes `3` and `'5 per hour'` becomes `5`. Both are
 * a silent reinterpretation of something the operator wrote deliberately, and
 * the limit they end up running is not the one in their environment file.
 * Requiring the whole string to be digits makes that a fallback instead.
 */
function positiveInt(value: string | undefined, fallback: number): number {
  const raw = trimmed(value);
  if (!/^\d+$/.test(raw)) {
    return fallback;
  }
  const parsed = Number.parseInt(raw, 10);
  return parsed > 0 ? parsed : fallback;
}

/**
 * Split a comma-separated list, dropping blanks.
 *
 * Used for the expected Turnstile hostnames, where `a.com,,b.com` and a
 * trailing comma are both things a hand-edited environment file contains.
 */
function commaList(value: string | undefined): string[] {
  return trimmed(value)
    .split(',')
    .map((entry) => entry.trim().toLowerCase())
    .filter(Boolean);
}

/** Digits-only for the same reason as `parseRateLimit` - `'587x'` is a typo, not port 587. */
function parsePort(value: string | undefined): number | null {
  const raw = trimmed(value);
  if (!/^\d+$/.test(raw)) {
    return null;
  }
  const parsed = Number.parseInt(raw, 10);
  return parsed > 0 && parsed <= 65535 ? parsed : null;
}

/**
 * Collect the server configuration, or report what is missing.
 *
 * This is the fail-closed gate. A deployment that sets `CONTACT_FORM_ENABLED`
 * but forgets the Turnstile secret does not get an unprotected form - it gets
 * the `mailto:` page, because `ready` is false and the page and the endpoint
 * both key off it.
 *
 * `missing` names variables for the server log at startup and for tests. It is
 * never returned to a browser: telling an anonymous visitor which secret is
 * absent describes the deployment's gaps to whoever asks.
 */
export function readContactConfig(): ContactReadiness {
  const missing: string[] = [];

  const recipient = trimmed(process.env.CONTACT_RECIPIENT_EMAIL);
  if (!recipient) missing.push('CONTACT_RECIPIENT_EMAIL');

  const host = trimmed(process.env.SMTP_HOST);
  if (!host) missing.push('SMTP_HOST');

  const port = parsePort(process.env.SMTP_PORT);
  if (port === null) missing.push('SMTP_PORT');

  const user = trimmed(process.env.SMTP_USER);
  if (!user) missing.push('SMTP_USER');

  const password = trimmed(process.env.SMTP_APP_PASSWORD);
  if (!password) missing.push('SMTP_APP_PASSWORD');

  const turnstileSecret = trimmed(process.env.TURNSTILE_SECRET_KEY);
  if (!turnstileSecret) missing.push('TURNSTILE_SECRET_KEY');

  const rateLimitSecret = trimmed(process.env.CONTACT_RATE_LIMIT_SECRET);
  if (!rateLimitSecret) missing.push('CONTACT_RATE_LIMIT_SECRET');

  if (!turnstileSiteKey()) missing.push('NEXT_PUBLIC_TURNSTILE_SITE_KEY');

  if (missing.length > 0 || port === null) {
    return { ready: false, missing };
  }

  return {
    ready: true,
    config: {
      recipient,
      smtp: {
        host,
        port,
        // Implicit TLS on 465; STARTTLS upgrade on 587 and everything else.
        secure: flag(process.env.SMTP_SECURE, port === 465),
        user,
        password,
        // Gmail rewrites a From it does not own, so the authenticated user is
        // the honest default rather than the visitor's address.
        from: trimmed(process.env.SMTP_FROM) || user,
      },
      turnstile: {
        secret: turnstileSecret,
        expectedHostnames: commaList(process.env.TURNSTILE_EXPECTED_HOSTNAMES),
        expectedAction: trimmed(process.env.TURNSTILE_EXPECTED_ACTION).toLowerCase(),
      },
      rateLimit: {
        maxPerWindow: positiveInt(process.env.CONTACT_RATE_LIMIT_MAX, DEFAULT_RATE_LIMIT_MAX),
        windowMs:
          positiveInt(
            process.env.CONTACT_RATE_LIMIT_WINDOW_SECONDS,
            DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
          ) * 1000,
        secret: rateLimitSecret,
      },
    },
  };
}

/**
 * The single question the page and the endpoint both ask.
 *
 * Requested *and* fully configured. Anything less renders and behaves exactly
 * as the site did before the form existed.
 */
export function isContactFormAvailable(): boolean {
  return isContactFormRequested() && readContactConfig().ready;
}
