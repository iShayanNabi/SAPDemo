/**
 * The contact form's submission endpoint.
 *
 * This is the only endpoint on the public website that accepts a write from an
 * anonymous visitor, so the order of the checks below is the design, not an
 * implementation detail. Each one is arranged to reject before anything more
 * expensive than itself runs:
 *
 * 1. **Is the form switched on and fully configured?** If not, `404` - the same
 *    response a URL that was never routed would give.
 * 2. **Is the body a small, well-formed JSON object?** Rejected before parsing
 *    anything large.
 * 3. **Was the honeypot filled in?** Answered with the success response a real
 *    submission gets, and nothing is sent.
 * 4. **Do the fields validate?** Server-side, on input assumed hostile.
 * 5. **Is this *address* within its rate limit?** Before Turnstile, because an
 *    outbound HTTPS round trip is the most expensive step here and a flooder
 *    must not be able to make us pay for it.
 * 6. **Does Cloudflare verify the token?** Fail closed, always.
 * 7. **Is this *email address* within its rate limit?** Deliberately *after*
 *    the challenge - see below.
 * 8. **Only then**, SMTP.
 *
 * ## Why the two rate-limit buckets are checked in different places
 *
 * The client address is a fact about the connection; the email address is a
 * string the submitter typed. Charging the email bucket before the challenge
 * was solved would mean anyone could type a third party's address, fire
 * `CONTACT_RATE_LIMIT_MAX` requests carrying junk tokens, and lock that person
 * out of the contact form for a whole window - a denial of service against
 * someone else, costing the attacker only their own IP quota.
 *
 * Putting the email bucket after verification means filling somebody else's
 * allowance costs a real Turnstile solve per hit, while the IP bucket keeps
 * limiting the attacker throughout.
 *
 * ## What is logged
 *
 * Reason codes and outcomes. Never the message, never the visitor's address,
 * never a raw IP, never the Turnstile token, never the SMTP credentials. A log
 * line from this endpoint should be useless to anyone who steals the log, which
 * is why every failure is identified by a fixed string chosen from a closed set
 * rather than by echoing what the visitor sent.
 *
 * ## What the browser is told
 *
 * Field-level errors for validation, because the visitor has to fix those. For
 * everything else, one generic message. A response that distinguishes "the
 * Turnstile secret is wrong" from "the token was replayed" from "SMTP refused
 * the connection" is a diagnostic tool for whoever is probing the endpoint.
 */

import { NextResponse } from 'next/server';
import { isContactFormRequested, readContactConfig } from '@/lib/contact/config';
import { sendContactMessage } from '@/lib/contact/mailer';
import { checkEmailRateLimit, checkIpRateLimit } from '@/lib/contact/rate-limit';
import { verifyTurnstileToken } from '@/lib/contact/turnstile';
import { isBotSubmission, validateSubmission } from '@/lib/contact/validation';

/** nodemailer and `node:crypto` need Node, not the edge runtime. */
export const runtime = 'nodejs';

/** Nothing here may be cached or statically evaluated at build time. */
export const dynamic = 'force-dynamic';

/**
 * Ceiling on the request body.
 *
 * The longest legitimate submission is the sum of the field limits plus a
 * Turnstile token - comfortably under 8 KB. Reading the body before checking
 * its length is what makes an endpoint a memory sink, so the declared
 * `Content-Length` is checked first and the decoded text is checked again after,
 * because a chunked request declares no length at all.
 */
const MAX_BODY_BYTES = 16 * 1024;

/** The single message shown for every non-validation failure. */
const GENERIC_FAILURE =
  'Your message could not be sent. Please try again, or email us directly.';

/**
 * The 429 body, identical for both buckets.
 *
 * Distinguishing "your address is rate limited" from "that email address is
 * rate limited" would confirm to a stranger that somebody else has been using
 * the form - and turn the endpoint into an oracle for which addresses have.
 */
function rateLimitedBody() {
  return {
    ok: false,
    message:
      'Too many messages have been sent from here recently. Please try again later, or email us directly.',
  };
}

function json(body: unknown, status: number, headers?: HeadersInit): NextResponse {
  return NextResponse.json(body, {
    status,
    headers: { 'Cache-Control': 'no-store', ...headers },
  });
}

/**
 * The response for a form that is switched off or misconfigured.
 *
 * A `404` rather than a `503`: the endpoint does not exist as far as the
 * internet is concerned, and saying "temporarily unavailable" advertises that
 * it will exist later. Nothing about *which* variable is missing is returned -
 * that detail goes to the server log, once, at the top of the handler.
 */
function notFound(): NextResponse {
  return json({ ok: false, message: 'Not found.' }, 404);
}

/**
 * Log a one-line outcome with no visitor-derived content in it.
 *
 * Every argument is a fixed string produced by this codebase.
 */
function logOutcome(outcome: string, detail?: string): void {
  const suffix = detail ? ` detail=${detail}` : '';
  console.info(`[contact] outcome=${outcome}${suffix}`);
}

export async function POST(request: Request): Promise<NextResponse> {
  if (!isContactFormRequested()) {
    return notFound();
  }

  const readiness = readContactConfig();
  if (!readiness.ready) {
    // Named here and only here, on the server, so an operator who switched the
    // form on can see why it is not serving. The browser still gets a 404.
    console.error(
      `[contact] outcome=misconfigured missing=${readiness.missing.join(',')}`,
    );
    return notFound();
  }
  const config = readiness.config;

  const declaredLength = Number.parseInt(request.headers.get('content-length') ?? '', 10);
  if (Number.isInteger(declaredLength) && declaredLength > MAX_BODY_BYTES) {
    logOutcome('rejected', 'body-too-large');
    return json({ ok: false, message: GENERIC_FAILURE }, 413);
  }

  const contentType = request.headers.get('content-type') ?? '';
  if (!contentType.toLowerCase().includes('application/json')) {
    logOutcome('rejected', 'unsupported-content-type');
    return json({ ok: false, message: GENERIC_FAILURE }, 415);
  }

  let raw: string;
  try {
    raw = await request.text();
  } catch {
    logOutcome('rejected', 'body-unreadable');
    return json({ ok: false, message: GENERIC_FAILURE }, 400);
  }

  if (raw.length > MAX_BODY_BYTES) {
    logOutcome('rejected', 'body-too-large');
    return json({ ok: false, message: GENERIC_FAILURE }, 413);
  }

  let payload: Record<string, unknown>;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      throw new Error('not an object');
    }
    payload = parsed as Record<string, unknown>;
  } catch {
    logOutcome('rejected', 'body-not-json');
    return json({ ok: false, message: GENERIC_FAILURE }, 400);
  }

  // Cloudflare sets this and strips any client-supplied copy. `X-Forwarded-For`
  // is deliberately not consulted - see `lib/contact/rate-limit.ts`.
  const clientIp = request.headers.get('cf-connecting-ip');

  // The honeypot is checked before validation so a bot that fills every field
  // gets the identical response a valid submission does, with the identical
  // timing profile of doing no further work. Nothing is sent.
  if (isBotSubmission(payload)) {
    logOutcome('discarded', 'honeypot');
    return json({ ok: true, message: 'Thank you - your message has been sent.' }, 200);
  }

  const validation = validateSubmission(payload);

  // The address bucket runs whether or not validation passed, so probing the
  // validator costs the same quota as sending.
  const ipLimit = checkIpRateLimit(clientIp, config.rateLimit);
  if (ipLimit.limited) {
    logOutcome('rejected', 'rate-limited-ip');
    return json(rateLimitedBody(), 429, {
      'Retry-After': String(ipLimit.retryAfterSeconds),
    });
  }

  if (!validation.valid) {
    logOutcome('rejected', 'validation');
    return json(
      { ok: false, message: 'Please correct the highlighted fields.', errors: validation.errors },
      400,
    );
  }

  const turnstile = await verifyTurnstileToken(
    payload.turnstileToken,
    config.turnstile.secret,
    clientIp,
    config.turnstile,
  );
  if (!turnstile.verified) {
    // The reason is a Cloudflare error code or one of this module's own fixed
    // strings - no visitor input reaches the log.
    logOutcome('rejected', `turnstile:${turnstile.reason}`);
    return json(
      {
        ok: false,
        message: 'We could not confirm you are human. Please reload the page and try again.',
      },
      403,
    );
  }

  // Only now. Before this line the address below is an unverified string a
  // stranger typed, and charging it would let them exhaust somebody else's
  // allowance for free.
  const emailLimit = checkEmailRateLimit(validation.value.email, config.rateLimit);
  if (emailLimit.limited) {
    logOutcome('rejected', 'rate-limited-email');
    return json(rateLimitedBody(), 429, {
      'Retry-After': String(emailLimit.retryAfterSeconds),
    });
  }

  const delivery = await sendContactMessage(config, validation.value);
  if (!delivery.delivered) {
    logOutcome('failed', delivery.reason);
    return json({ ok: false, message: GENERIC_FAILURE }, 502);
  }

  logOutcome('delivered');
  return json({ ok: true, message: 'Thank you - your message has been sent.' }, 200);
}

/**
 * Everything that is not a POST is a 404.
 *
 * `405 Method Not Allowed` would confirm the route exists, which is information
 * this endpoint has no reason to give away.
 */
export async function GET(): Promise<NextResponse> {
  return notFound();
}

export const HEAD = GET;
export const PUT = GET;
export const PATCH = GET;
export const DELETE = GET;
export const OPTIONS = GET;
