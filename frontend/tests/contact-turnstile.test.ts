import { describe, expect, it, vi } from 'vitest';
import { verifyTurnstileToken } from '@/lib/contact/turnstile';

const SECRET = 'test-secret';

/** No hostname or action pinning - the local-development configuration. */
const NO_PINS = { expectedHostnames: [], expectedAction: '' };

/** The deployed configuration, pinned to this site and this form. */
const PINNED = {
  expectedHostnames: ['solveaihub.com', 'www.solveaihub.com'],
  expectedAction: 'contact',
};
const TOKEN = 'a-token-from-the-widget';

/** A stub `fetch` that returns one canned siteverify response. */
function respondWith(body: unknown, init: { ok?: boolean; status?: number } = {}) {
  return vi.fn(async () =>
    ({
      ok: init.ok ?? true,
      status: init.status ?? 200,
      json: async () => body,
    }) as unknown as Response,
  );
}

describe('verifyTurnstileToken', () => {
  it('verifies a token Cloudflare accepts', async () => {
    const fetchImpl = respondWith({ success: true });
    const result = await verifyTurnstileToken(TOKEN, SECRET, '203.0.113.7', NO_PINS, fetchImpl);
    expect(result.verified).toBe(true);
  });

  it('posts the secret and token, and never puts them in the URL', async () => {
    const fetchImpl = respondWith({ success: true });
    await verifyTurnstileToken(TOKEN, SECRET, '203.0.113.7', NO_PINS, fetchImpl);

    const [url, init] = fetchImpl.mock.calls[0]! as unknown as [string, RequestInit];
    expect(url).toBe('https://challenges.cloudflare.com/turnstile/v0/siteverify');
    // A secret in a query string is a secret in every proxy log on the path.
    expect(url).not.toContain(SECRET);
    expect(init.method).toBe('POST');

    const body = init.body as URLSearchParams;
    expect(body.get('secret')).toBe(SECRET);
    expect(body.get('response')).toBe(TOKEN);
    expect(body.get('remoteip')).toBe('203.0.113.7');
  });

  it('omits remoteip when there is no client address to send', async () => {
    const fetchImpl = respondWith({ success: true });
    await verifyTurnstileToken(TOKEN, SECRET, null, NO_PINS, fetchImpl);
    const [, init] = fetchImpl.mock.calls[0]! as unknown as [string, RequestInit];
    expect((init.body as URLSearchParams).has('remoteip')).toBe(false);
  });

  describe('fails closed', () => {
    it('refuses when no secret is configured, without calling Cloudflare', async () => {
      const fetchImpl = respondWith({ success: true });
      const result = await verifyTurnstileToken(TOKEN, '', null, NO_PINS, fetchImpl);
      expect(result.verified).toBe(false);
      expect(result.reason).toBe('secret-not-configured');
      // The point: an unconfigured deployment cannot accidentally verify.
      expect(fetchImpl).not.toHaveBeenCalled();
    });

    it.each([
      ['a missing token', undefined],
      ['a null token', null],
      ['an empty token', ''],
      ['a whitespace token', '   '],
      ['a non-string token', 12345],
      ['an object', { token: 'x' }],
    ])('refuses %s without calling Cloudflare', async (_label, token) => {
      const fetchImpl = respondWith({ success: true });
      const result = await verifyTurnstileToken(token, SECRET, null, NO_PINS, fetchImpl);
      expect(result.verified).toBe(false);
      expect(fetchImpl).not.toHaveBeenCalled();
    });

    it('refuses an implausibly long token without calling Cloudflare', async () => {
      const fetchImpl = respondWith({ success: true });
      const result = await verifyTurnstileToken('x'.repeat(4096), SECRET, null, NO_PINS, fetchImpl);
      expect(result.verified).toBe(false);
      expect(result.reason).toBe('token-too-long');
      expect(fetchImpl).not.toHaveBeenCalled();
    });

    it('refuses when Cloudflare rejects the token', async () => {
      const fetchImpl = respondWith({ success: false, 'error-codes': ['invalid-input-response'] });
      const result = await verifyTurnstileToken(TOKEN, SECRET, null, NO_PINS, fetchImpl);
      expect(result.verified).toBe(false);
      expect(result.reason).toBe('invalid-input-response');
    });

    /**
     * The failure a fail-open implementation gets wrong. An attacker who can
     * cause a timeout - by exhausting connections, or simply by being on a
     * network where Cloudflare is unreachable - has otherwise disabled the
     * captcha entirely.
     */
    it('refuses when the network throws', async () => {
      const fetchImpl = vi.fn(async () => {
        throw new Error('ECONNREFUSED');
      });
      const result = await verifyTurnstileToken(TOKEN, SECRET, null, NO_PINS, fetchImpl);
      expect(result.verified).toBe(false);
      expect(result.reason).toBe('verification-unreachable');
    });

    it('refuses when the request times out', async () => {
      const fetchImpl = vi.fn(async () => {
        const error = new Error('The operation was aborted due to timeout');
        error.name = 'TimeoutError';
        throw error;
      });
      const result = await verifyTurnstileToken(TOKEN, SECRET, null, NO_PINS, fetchImpl);
      expect(result.verified).toBe(false);
      expect(result.reason).toBe('verification-unreachable');
    });

    it('refuses on a non-2xx response', async () => {
      const fetchImpl = respondWith({ success: true }, { ok: false, status: 500 });
      const result = await verifyTurnstileToken(TOKEN, SECRET, null, NO_PINS, fetchImpl);
      expect(result.verified).toBe(false);
      expect(result.reason).toBe('verification-http-500');
    });

    it('refuses when the body is not JSON', async () => {
      const fetchImpl = vi.fn(async () =>
        ({
          ok: true,
          status: 200,
          json: async () => {
            throw new SyntaxError('Unexpected token < in JSON');
          },
        }) as unknown as Response,
      );
      const result = await verifyTurnstileToken(TOKEN, SECRET, null, NO_PINS, fetchImpl);
      expect(result.verified).toBe(false);
      expect(result.reason).toBe('verification-malformed');
    });

    /**
     * `success` must be exactly `true`. Every value below is truthy, and a
     * loose `if (payload.success)` would pass all of them - including the
     * string `"false"`, which is what a proxy that stringifies JSON produces.
     */
    it.each([
      ['the string "true"', 'true'],
      ['the string "false"', 'false'],
      ['the number 1', 1],
      ['an object', {}],
      ['an array', []],
      ['null', null],
      ['undefined', undefined],
    ])('refuses when success is %s rather than boolean true', async (_label, success) => {
      const fetchImpl = respondWith({ success });
      const result = await verifyTurnstileToken(TOKEN, SECRET, null, NO_PINS, fetchImpl);
      expect(result.verified).toBe(false);
    });

    it('refuses an entirely empty response body', async () => {
      const fetchImpl = respondWith(null);
      const result = await verifyTurnstileToken(TOKEN, SECRET, null, NO_PINS, fetchImpl);
      expect(result.verified).toBe(false);
    });
  });

  /**
   * A `success: true` alone does not prove the token belongs to this form on
   * this site. The site key is public, so anyone can embed the same widget on
   * a page they control, have a genuine challenge solved there, and replay the
   * token here - Cloudflare will confirm it, correctly, as genuine. The
   * hostname and action are what make the confirmation specific.
   */
  describe('hostname and action pinning', () => {
    it.each(['solveaihub.com', 'www.solveaihub.com', 'WWW.SolveAIHub.com'])(
      'accepts a token solved on %s',
      async (hostname) => {
        const result = await verifyTurnstileToken(
          TOKEN,
          SECRET,
          null,
          PINNED,
          respondWith({ success: true, hostname, action: 'contact' }),
        );
        expect(result.verified).toBe(true);
      },
    );

    it.each([
      ['an attacker-controlled host', 'evil.example'],
      ['a suffix lookalike', 'solveaihub.com.evil.example'],
      ['a prefix lookalike', 'evil-solveaihub.com'],
      ['an unlisted subdomain', 'staging.solveaihub.com'],
      ['a missing hostname', undefined],
      ['a non-string hostname', 12345],
    ])('refuses %s', async (_label, hostname) => {
      const result = await verifyTurnstileToken(
        TOKEN,
        SECRET,
        null,
        PINNED,
        respondWith({ success: true, hostname, action: 'contact' }),
      );
      expect(result.verified).toBe(false);
      expect(result.reason).toBe('hostname-mismatch');
    });

    it.each([
      ['a different action', 'newsletter'],
      ['an empty action', ''],
      ['a missing action', undefined],
    ])('refuses %s', async (_label, action) => {
      const result = await verifyTurnstileToken(
        TOKEN,
        SECRET,
        null,
        PINNED,
        respondWith({ success: true, hostname: 'solveaihub.com', action }),
      );
      expect(result.verified).toBe(false);
      expect(result.reason).toBe('action-mismatch');
    });

    it('accepts the action case-insensitively', async () => {
      const result = await verifyTurnstileToken(
        TOKEN,
        SECRET,
        null,
        PINNED,
        respondWith({ success: true, hostname: 'solveaihub.com', action: 'CONTACT' }),
      );
      expect(result.verified).toBe(true);
    });

    /**
     * Unpinned is the local-development configuration, and it must still
     * require a genuine `success: true`. Skipping the *pins* is not skipping
     * verification.
     */
    it('skips the pins when unconfigured, but still requires success', async () => {
      const ok = await verifyTurnstileToken(
        TOKEN,
        SECRET,
        null,
        NO_PINS,
        respondWith({ success: true, hostname: 'example.com', action: '' }),
      );
      expect(ok.verified).toBe(true);

      const rejected = await verifyTurnstileToken(
        TOKEN,
        SECRET,
        null,
        NO_PINS,
        respondWith({ success: false, hostname: 'example.com' }),
      );
      expect(rejected.verified).toBe(false);
    });
  });

  /**
   * There is no `NODE_ENV` branch in this module, and this asserts it
   * behaviourally rather than by reading the source: the same unconfigured
   * call must refuse in development exactly as it does in production.
   */
  it('has no development bypass', async () => {
    try {
      for (const env of ['development', 'test', 'production'] as const) {
        vi.stubEnv('NODE_ENV', env);
        const result = await verifyTurnstileToken(TOKEN, '', null, NO_PINS, respondWith({ success: true }));
        expect(result.verified, env).toBe(false);
      }
    } finally {
      vi.unstubAllEnvs();
    }
  });
});
