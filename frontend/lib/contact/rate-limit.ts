/**
 * In-memory sliding-window rate limiting for the contact endpoint.
 *
 * ## What this is, and what it is not
 *
 * The state lives in a module-level `Map` in the Next.js server process. That
 * has three consequences the operator has to know rather than discover:
 *
 * * it is **per process** - two replicas keep two independent counts, so the
 *   effective limit is the configured one multiplied by the replica count;
 * * it **resets on restart**, so a deploy clears every bucket;
 * * it is therefore suitable for **the current single-instance deployment**
 *   only. Horizontal scaling needs shared state (Redis or equivalent), and this
 *   module is where that swap belongs.
 *
 * It is deliberately not a persistence layer. `docs/DEMO_SECURITY_CHECKLIST.md`
 * commits the public site to storing nothing a visitor sends, and a rate-limit
 * table keyed by anything derived from a person is storage. Holding counters in
 * memory that vanish on restart is the weakest mechanism that still works.
 *
 * ## Why the keys are HMACs and not hashes
 *
 * A bare `SHA-256(ip)` is not anonymisation. The IPv4 space is 2^32 - small
 * enough to enumerate exhaustively on a laptop - so an unkeyed digest of an
 * address is reversible by brute force, and the same is true of an email
 * address against any breach corpus. Keying the digest with a secret the
 * attacker does not have (`CONTACT_RATE_LIMIT_SECRET`) is what makes the stored
 * value useless to anyone who obtains a heap dump.
 *
 * Neither the raw address nor the raw email is stored, logged, or included in
 * the delivered message. Only the truncated HMAC ever exists in the `Map`, and
 * nothing in this module writes to a log at all.
 */

import { createHmac } from 'node:crypto';

/**
 * Ceiling on distinct buckets held at once.
 *
 * Without it, a spray of one request each from many addresses grows the `Map`
 * without bound - the rate limiter becomes the memory-exhaustion vector it was
 * added to prevent.
 */
export const MAX_TRACKED_BUCKETS = 10_000;

/** Shared bucket for requests arriving without a trustworthy client address. */
export const FALLBACK_BUCKET_KEY = 'no-client-ip';

type Bucket = { hits: number[] };

const buckets = new Map<string, Bucket>();

/** Test seam. Never called by the endpoint. */
export function __resetRateLimiter(): void {
  buckets.clear();
  lastSweepAt = Number.NEGATIVE_INFINITY;
}

/** Test seam: how many buckets are currently held. */
export function __trackedBucketCount(): number {
  return buckets.size;
}

/**
 * Test seam: a snapshot of every bucket key and how many hits it holds.
 *
 * This exists so the privacy claim can be *asserted* rather than assumed. The
 * page tells a visitor their address is not retained; the test that backs that
 * up has to be able to look at what is actually in memory and confirm the raw
 * value is not among it. A test that cannot see the state can only restate the
 * implementation back to itself.
 *
 * Returns keys, which are already keyed digests, and counts. It never returns
 * anything derived from a message body, because none is ever stored.
 */
export function __inspectBuckets(): Array<{ key: string; hits: number }> {
  return [...buckets.entries()].map(([key, bucket]) => ({ key, hits: bucket.hits.length }));
}

/**
 * Derive a storage key from a sensitive value.
 *
 * Truncated to 32 hex characters: 128 bits is far beyond collision range for a
 * map that holds at most ten thousand entries, and a shorter key means less of
 * the digest sitting in memory.
 */
function bucketKey(secret: string, kind: 'ip' | 'email', value: string): string {
  return createHmac('sha256', secret)
    // The kind is mixed in so an address and an email that somehow produced the
    // same digest could still not share a bucket.
    .update(`${kind}:${value}`)
    .digest('hex')
    .slice(0, 32);
}

/**
 * Normalise a client address before it is keyed.
 *
 * Case and surrounding whitespace vary between proxies; an IPv6 address written
 * two ways must land in one bucket or the limit is trivially doubled.
 */
function normaliseIp(value: string): string {
  return value.trim().toLowerCase();
}

/**
 * How often the expired-bucket sweep runs, in logical milliseconds.
 *
 * The sweep is *garbage collection, not enforcement*. `hitsInWindow` filters
 * expired timestamps every time a bucket is read, so a bucket that has not been
 * swept yet still yields the correct count - the sweep only reclaims memory.
 * That distinction is what makes it safe to run occasionally rather than on
 * every request, and it is the difference between an O(1) and an O(n) endpoint:
 * sweeping ten thousand buckets on each of ten thousand requests is a hundred
 * million operations, and a flooder would be the one choosing to spend them.
 */
const SWEEP_INTERVAL_MS = 60_000;

let lastSweepAt = Number.NEGATIVE_INFINITY;

/** Drop hits that have aged out, and any bucket left holding none. */
function sweep(now: number, windowMs: number): void {
  for (const [key, bucket] of buckets) {
    const live = bucket.hits.filter((at) => now - at < windowMs);
    if (live.length === 0) {
      buckets.delete(key);
    } else {
      bucket.hits = live;
    }
  }
  lastSweepAt = now;
}

/**
 * Reclaim memory when it is worth reclaiming.
 *
 * Runs on a timer rather than per request, and immediately whenever the map is
 * over its ceiling regardless of the timer - that second condition is what
 * stops a burst of distinct addresses outrunning the interval.
 */
function maybeSweep(now: number, windowMs: number): void {
  if (buckets.size > MAX_TRACKED_BUCKETS || now - lastSweepAt >= SWEEP_INTERVAL_MS) {
    sweep(now, windowMs);
  }
}

/**
 * Hold the map at or below the ceiling.
 *
 * Called *after* the attempt is recorded, not before. Enforcing it on the way
 * in leaves the map permanently over the limit by however many buckets a single
 * request then adds - two, here - which is a ceiling that does not hold at the
 * only moment anybody would check it.
 *
 * Eviction follows the `Map`'s insertion order, which is oldest-first and free.
 * Sorting by most-recent-hit would evict slightly better candidates, but it
 * costs an O(n log n) sort on a path an attacker controls the trigger for, and
 * paying that per request to refine which of ten thousand near-expired buckets
 * goes first is a bad trade.
 */
function enforceCeiling(): void {
  if (buckets.size <= MAX_TRACKED_BUCKETS) {
    return;
  }
  const excess = buckets.size - MAX_TRACKED_BUCKETS;
  let removed = 0;
  for (const key of buckets.keys()) {
    if (removed >= excess) break;
    buckets.delete(key);
    removed += 1;
  }
}

function hitsInWindow(key: string, now: number, windowMs: number): number[] {
  const bucket = buckets.get(key);
  if (!bucket) {
    return [];
  }
  return bucket.hits.filter((at) => now - at < windowMs);
}

/**
 * Record an attempt, keeping at most `maxPerWindow` timestamps per bucket.
 *
 * The cap matters: a bucket that is already blocking needs no further evidence,
 * and appending on every retry would let one attacker in a tight loop grow a
 * single array without bound. That is the same memory-exhaustion failure
 * `MAX_TRACKED_BUCKETS` prevents across buckets, one level down inside one.
 *
 * Discarding the surplus does not weaken enforcement. The block lifts when the
 * *oldest* retained hit ages out of the window, and the retained hits are the
 * oldest ones, so a caller gains nothing by hammering - it simply stays blocked
 * until real time passes.
 */
function record(key: string, now: number, maxPerWindow: number): void {
  const bucket = buckets.get(key);
  if (!bucket) {
    buckets.set(key, { hits: [now] });
    return;
  }
  if (bucket.hits.length < maxPerWindow) {
    bucket.hits.push(now);
  }
}

export type RateLimitSettings = {
  readonly maxPerWindow: number;
  readonly windowMs: number;
  readonly secret: string;
  /** Injected so tests can advance the clock without waiting a whole window. */
  readonly now?: number;
};

export type RateLimitResult =
  | { limited: false }
  | { limited: true; retryAfterSeconds: number };

/** Check one bucket, record the attempt against it, and report the verdict. */
function consume(key: string, settings: RateLimitSettings): RateLimitResult {
  const { maxPerWindow, windowMs } = settings;
  const now = settings.now ?? Date.now();

  maybeSweep(now, windowMs);

  const hits = hitsInWindow(key, now, windowMs);
  const blocked = hits.length >= maxPerWindow;
  const oldest = blocked ? Math.min(...hits) : 0;

  record(key, now, maxPerWindow);
  enforceCeiling();

  if (!blocked) {
    return { limited: false };
  }
  return {
    limited: true,
    retryAfterSeconds: Math.max(1, Math.ceil((oldest + windowMs - now) / 1000)),
  };
}

/**
 * Count this request against the client address.
 *
 * Checked early, before anything expensive, and charged for *every* attempt -
 * including ones that go on to fail validation or Turnstile - so probing the
 * endpoint costs the same quota as using it properly.
 *
 * When `CF-Connecting-IP` is absent the request is counted against one shared
 * fallback bucket instead. It is deliberately *not* backfilled from
 * `X-Forwarded-For` or `X-Real-IP`: in front of Cloudflare those headers are
 * whatever the client typed, so trusting them lets an attacker mint a fresh
 * bucket per request and bypass the limit entirely. A shared bucket means
 * header-less traffic competes with itself for one allowance, which is the
 * conservative failure.
 */
export function checkIpRateLimit(
  clientIp: string | null,
  settings: RateLimitSettings,
): RateLimitResult {
  const normalised = clientIp === null ? '' : normaliseIp(clientIp);
  const key = normalised ? bucketKey(settings.secret, 'ip', normalised) : FALLBACK_BUCKET_KEY;
  return consume(key, settings);
}

/**
 * Count this request against the submitted email address.
 *
 * **Only ever called after Turnstile has verified the submission.** That
 * ordering is the reason this is a separate function rather than a second key
 * inside one call, and it is a security property rather than a tidiness one.
 *
 * The email bucket exists to stop one sender rotating through addresses, which
 * a VPN or a botnet makes cheap. But the address is *attacker-chosen input* -
 * it is simply whatever was typed into the form. Charging this bucket before
 * the challenge is solved would let anyone type a third party's address, submit
 * `maxPerWindow` requests carrying garbage tokens, and lock that person out of
 * the contact form for a whole window. That is an unauthenticated denial of
 * service against someone else, and it would cost the attacker nothing beyond
 * their own IP quota.
 *
 * Requiring a solved challenge first means filling somebody else's bucket costs
 * a genuine Turnstile solve per hit, which is where the attack stops being
 * free. The IP bucket is still doing its work in the meantime.
 */
export function checkEmailRateLimit(
  email: string,
  settings: RateLimitSettings,
): RateLimitResult {
  return consume(bucketKey(settings.secret, 'email', email), settings);
}
