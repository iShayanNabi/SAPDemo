import { createHash, createHmac } from 'node:crypto';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  MAX_TRACKED_BUCKETS,
  type RateLimitSettings,
  __inspectBuckets,
  __resetRateLimiter,
  __trackedBucketCount,
  checkEmailRateLimit,
  checkIpRateLimit,
} from '@/lib/contact/rate-limit';

const WINDOW = 60 * 60 * 1000;
const SECRET = 'test-hmac-secret';
const START = 1_700_000_000_000;

function settings(overrides: Partial<RateLimitSettings> = {}): RateLimitSettings {
  return { maxPerWindow: 3, windowMs: WINDOW, secret: SECRET, now: START, ...overrides };
}

/** Charge the address bucket. */
function ip(clientIp: string | null = '203.0.113.7', overrides: Partial<RateLimitSettings> = {}) {
  return checkIpRateLimit(clientIp, settings(overrides));
}

/** Charge the email bucket. */
function email(address = 'ingrid@example.com', overrides: Partial<RateLimitSettings> = {}) {
  return checkEmailRateLimit(address, settings(overrides));
}

beforeEach(() => {
  __resetRateLimiter();
});

describe('checkIpRateLimit', () => {
  it('allows requests up to the limit and rejects the one after', () => {
    for (let i = 0; i < 3; i += 1) {
      expect(ip().limited, `request ${i + 1}`).toBe(false);
    }
    expect(ip().limited).toBe(true);
  });

  it('reports how long to wait, based on the oldest hit expiring', () => {
    for (let i = 0; i < 3; i += 1) {
      ip('203.0.113.7', { now: START + i * 1000 });
    }
    const result = ip('203.0.113.7', { now: START + 10_000 });
    expect(result.limited).toBe(true);
    if (result.limited) {
      expect(result.retryAfterSeconds).toBe((WINDOW - 10_000) / 1000);
    }
  });

  it('lets the sender through again once the window has passed', () => {
    for (let i = 0; i < 3; i += 1) ip();
    expect(ip().limited).toBe(true);
    expect(ip('203.0.113.7', { now: START + WINDOW + 1 }).limited).toBe(false);
  });

  it('honours a shorter configured window', () => {
    const short = { windowMs: 60_000 };
    for (let i = 0; i < 3; i += 1) ip('203.0.113.7', short);
    expect(ip('203.0.113.7', short).limited).toBe(true);
    expect(ip('203.0.113.7', { ...short, now: START + 60_001 }).limited).toBe(false);
  });

  it('treats differently-cased and padded spellings as one bucket', () => {
    ip('2001:DB8::1');
    ip('2001:db8::1');
    ip('  2001:db8::1  ');
    expect(ip('2001:db8::1').limited).toBe(true);
  });

  /**
   * Cloudflare always sets `CF-Connecting-IP`, so its absence means the request
   * did not arrive through Cloudflare - and the headers that would otherwise
   * identify a client are attacker-controlled there. Sharing one bucket is the
   * conservative answer: header-less traffic competes with itself.
   */
  it('shares one fallback bucket when the address is absent', () => {
    for (let i = 0; i < 3; i += 1) {
      expect(ip(null).limited).toBe(false);
    }
    expect(ip(null).limited).toBe(true);
  });

  it('treats a blank address the same as an absent one', () => {
    for (let i = 0; i < 3; i += 1) ip('   ');
    expect(ip(null).limited).toBe(true);
  });

  it('does not let the fallback bucket block a real address', () => {
    for (let i = 0; i < 3; i += 1) ip(null);
    expect(ip('203.0.113.9').limited).toBe(false);
  });
});

describe('checkEmailRateLimit', () => {
  it('allows requests up to the limit and rejects the one after', () => {
    for (let i = 0; i < 3; i += 1) {
      expect(email().limited, `request ${i + 1}`).toBe(false);
    }
    expect(email().limited).toBe(true);
  });

  it('is independent of the address bucket', () => {
    for (let i = 0; i < 3; i += 1) ip();
    // The address is spent; a different address with this email is not.
    expect(email().limited).toBe(false);
  });

  /**
   * The reason the email bucket exists: one sender rotating through addresses
   * is cheap with a VPN or a botnet, and the IP bucket alone would not see it.
   */
  it('blocks the same address arriving from many different IPs', () => {
    for (let i = 0; i < 3; i += 1) {
      expect(ip(`198.51.100.${i}`).limited).toBe(false);
      expect(email('ingrid@example.com').limited).toBe(false);
    }
    expect(ip('198.51.100.200').limited).toBe(false);
    expect(email('ingrid@example.com').limited).toBe(true);
  });

  it('lets a genuinely different sender through', () => {
    for (let i = 0; i < 3; i += 1) email('ingrid@example.com');
    expect(email('someone-else@example.com').limited).toBe(false);
  });
});

describe('what is held in memory', () => {
  /**
   * The privacy claim the page makes is that no raw address survives the
   * request. This asserts it against the module's own state rather than
   * trusting the implementation.
   */
  it('stores no raw address or email, only keyed digests', () => {
    ip('203.0.113.7');
    email('ingrid@example.com');
    const serialised = JSON.stringify(__inspectBuckets());

    expect(serialised).not.toContain('203.0.113.7');
    expect(serialised).not.toContain('ingrid@example.com');

    const keyed = createHmac('sha256', SECRET).update('ip:203.0.113.7').digest('hex').slice(0, 32);
    expect(serialised).toContain(keyed);

    // The unkeyed digest must not appear: it is what an attacker holding a heap
    // dump could brute-force back to an address in seconds.
    const unkeyed = createHash('sha256').update('203.0.113.7').digest('hex').slice(0, 32);
    expect(serialised).not.toContain(unkeyed);
  });

  it('produces different keys under a different secret', () => {
    ip('203.0.113.7');
    const first = __inspectBuckets().map((b) => b.key);
    __resetRateLimiter();
    ip('203.0.113.7', { secret: 'a-different-secret' });
    expect(__inspectBuckets().map((b) => b.key)).not.toEqual(first);
  });

  it('drops buckets once their hits have expired', () => {
    ip('203.0.113.7');
    email('ingrid@example.com');
    expect(__trackedBucketCount()).toBe(2);
    ip('198.51.100.1', { now: START + WINDOW + 1 });
    email('other@example.com', { now: START + WINDOW + 1 });
    expect(__trackedBucketCount()).toBe(2);
  });

  /**
   * A bucket that is already blocking needs no further evidence. Without the
   * cap, an attacker in a tight loop grows one array without bound - the rate
   * limiter becoming the memory-exhaustion vector it exists to prevent.
   */
  it('caps the hits retained per bucket', () => {
    for (let i = 0; i < 500; i += 1) {
      ip('203.0.113.7', { now: START + i });
    }
    const buckets = __inspectBuckets();
    expect(buckets.length).toBeGreaterThan(0);
    for (const bucket of buckets) {
      expect(bucket.hits).toBeLessThanOrEqual(3);
    }
  });

  it('does not grow past the tracked-bucket ceiling', () => {
    for (let i = 0; i < MAX_TRACKED_BUCKETS + 200; i += 1) {
      ip(`10.0.${Math.floor(i / 256)}.${i % 256}`);
      email(`p${i}@example.com`);
    }
    expect(__trackedBucketCount()).toBeLessThanOrEqual(MAX_TRACKED_BUCKETS);
  });
});
