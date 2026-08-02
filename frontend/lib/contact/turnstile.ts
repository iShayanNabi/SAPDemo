/**
 * Server-side Cloudflare Turnstile verification.
 *
 * The widget in the browser proves nothing. It hands the page a token, and the
 * only thing that establishes the token is real, unexpired and unspent is this
 * call to Cloudflare's `siteverify` endpoint from the server, holding a secret
 * the browser never sees.
 *
 * ## Fail closed, in every environment, without exception
 *
 * Every path out of this module that is not an explicit `success: true` from
 * Cloudflare returns `verified: false`:
 *
 * * no secret configured;
 * * no token in the request, or one longer than Cloudflare will ever issue;
 * * the request times out or the network fails;
 * * a non-2xx response;
 * * a body that is not JSON, or is JSON of the wrong shape.
 *
 * There is deliberately **no `NODE_ENV` branch**. A bypass that is unreachable
 * in production is still one edit, one mis-set variable or one mistaken build
 * away from being reachable, and its absence is the only version of this that
 * can be verified by reading the file. Local development and the test suite use
 * Cloudflare's published test keys or a stubbed `fetch`, both of which exercise
 * the real code path rather than skipping it.
 *
 * The token is never logged, never stored and never included in the delivered
 * message. It is a bearer credential for one submission.
 */

import { siteverifyTimeoutMs } from '@/lib/contact/config';

const SITEVERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify';

/** Cloudflare tokens are well under this; anything longer is not worth a round trip. */
const MAX_TOKEN_LENGTH = 2048;

export type TurnstileResult = {
  readonly verified: boolean;
  /**
   * Cloudflare's machine-readable reason, or a local one, for server-side
   * diagnosis. Never returned to the browser: the response to a failed
   * challenge is a generic retry message, because naming the reason tells an
   * attacker whether the secret is wrong, the token was replayed or the
   * hostname did not match.
   */
  readonly reason: string;
};

type SiteverifyResponse = {
  success?: unknown;
  'error-codes'?: unknown;
  hostname?: unknown;
  action?: unknown;
};

export type TurnstileExpectations = {
  /** Hostnames a token may legitimately have been solved on. Empty skips the check. */
  readonly expectedHostnames: readonly string[];
  /** The `action` the widget declares. Empty skips the check. */
  readonly expectedAction: string;
};

/**
 * Verify one token against Cloudflare.
 *
 * `remoteIp` is passed through when Cloudflare gave us one. It is used for this
 * single call and never retained - see `lib/contact/rate-limit.ts` for why no
 * raw address survives the request.
 *
 * `fetchImpl` exists so tests can stub the network without a global monkeypatch
 * leaking between cases. The endpoint always uses the real `fetch`.
 */
export async function verifyTurnstileToken(
  token: unknown,
  secret: string,
  remoteIp: string | null,
  expectations: TurnstileExpectations = { expectedHostnames: [], expectedAction: '' },
  fetchImpl: typeof fetch = fetch,
): Promise<TurnstileResult> {
  if (!secret) {
    return { verified: false, reason: 'secret-not-configured' };
  }
  if (typeof token !== 'string' || token.trim().length === 0) {
    return { verified: false, reason: 'missing-token' };
  }
  if (token.length > MAX_TOKEN_LENGTH) {
    return { verified: false, reason: 'token-too-long' };
  }

  const body = new URLSearchParams({ secret, response: token.trim() });
  if (remoteIp) {
    body.set('remoteip', remoteIp);
  }

  let response: Response;
  try {
    response = await fetchImpl(SITEVERIFY_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
      // Read per call rather than at module scope: this is a runtime variable,
      // and freezing it at import time would mean the standalone server used
      // whatever was set when the module was first loaded.
      signal: AbortSignal.timeout(siteverifyTimeoutMs()),
      cache: 'no-store',
    });
  } catch {
    // Covers the timeout, DNS failure and connection reset alike. The error is
    // swallowed rather than rethrown because none of its detail may reach the
    // visitor, and the outcome is identical whichever it was: not verified.
    return { verified: false, reason: 'verification-unreachable' };
  }

  if (!response.ok) {
    return { verified: false, reason: `verification-http-${response.status}` };
  }

  let payload: SiteverifyResponse;
  try {
    payload = (await response.json()) as SiteverifyResponse;
  } catch {
    return { verified: false, reason: 'verification-malformed' };
  }

  // Strictly `true`. A truthy string such as `"false"` must not pass, which is
  // exactly what a loose check would let through.
  if (payload?.success !== true) {
    const codes = Array.isArray(payload?.['error-codes'])
      ? (payload['error-codes'] as unknown[]).filter((c) => typeof c === 'string').join(',')
      : '';
    return { verified: false, reason: codes || 'verification-rejected' };
  }

  /*
   * A `success: true` is not on its own proof the token belongs to *this*
   * form on *this* site.
   *
   * The site key is public - it is read straight out of the page source - so
   * anyone can embed the same widget on a page they control, have a real
   * person or a solver service solve a real challenge, and post the resulting
   * token here. Cloudflare will happily confirm that token is genuine, because
   * it is. What it also reports is where it was solved and which action it was
   * solved for, and those are the two fields that make the confirmation
   * specific to this endpoint rather than to the key.
   *
   * Both checks are configuration-driven rather than keyed off `NODE_ENV`.
   * That is deliberate and follows the rule the rest of this module obeys: an
   * environment-dependent branch in security-critical code is one mis-set
   * variable away from being live in the wrong place. A deployment sets the
   * hostnames and the action and gets the checks; local development leaves
   * them blank, because Cloudflare's test keys report neither meaningfully.
   */
  if (expectations.expectedHostnames.length > 0) {
    const hostname = typeof payload.hostname === 'string' ? payload.hostname.toLowerCase() : '';
    if (!expectations.expectedHostnames.includes(hostname)) {
      return { verified: false, reason: 'hostname-mismatch' };
    }
  }

  if (expectations.expectedAction) {
    const action = typeof payload.action === 'string' ? payload.action.toLowerCase() : '';
    if (action !== expectations.expectedAction) {
      return { verified: false, reason: 'action-mismatch' };
    }
  }

  return { verified: true, reason: 'ok' };
}
