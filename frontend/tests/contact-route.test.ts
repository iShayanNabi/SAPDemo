/**
 * The endpoint, driven end to end with everything below it stubbed at the
 * network and SMTP boundaries only.
 *
 * `lib/contact/validation.ts`, `rate-limit.ts` and `config.ts` all run for
 * real, because the bugs worth catching here live in how they are *wired*
 * rather than inside any one of them - a check performed in the wrong order,
 * or one that a later branch quietly skips.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { __resetRateLimiter } from '@/lib/contact/rate-limit';

const sendMail = vi.fn();

vi.mock('nodemailer', () => ({
  default: { createTransport: () => ({ sendMail }) },
}));

const CONFIGURED = {
  CONTACT_FORM_ENABLED: 'true',
  CONTACT_RECIPIENT_EMAIL: 'inbox@example.com',
  SMTP_HOST: 'smtp.example.com',
  SMTP_PORT: '587',
  SMTP_USER: 'sender@example.com',
  SMTP_APP_PASSWORD: 'not-a-real-password',
  TURNSTILE_SECRET_KEY: 'test-turnstile-secret',
  CONTACT_RATE_LIMIT_MAX: '3',
  CONTACT_RATE_LIMIT_SECRET: 'test-rate-limit-secret',
  NEXT_PUBLIC_TURNSTILE_SITE_KEY: '1x00000000000000000000AA',
};

const BODY = {
  name: 'Ingrid Nordwind',
  email: 'ingrid@example.com',
  organization: 'Nordwind GmbH',
  topic: 'A question about the spend module',
  sourcePage: '/contact',
  message: 'I would like to understand how the category rollup handles a missing material group.',
  turnstileToken: 'a-token-from-the-widget',
};

function configure(overrides: Record<string, string | undefined> = {}) {
  for (const [key, value] of Object.entries({ ...CONFIGURED, ...overrides })) {
    if (value === undefined) vi.stubEnv(key, '');
    else vi.stubEnv(key, value);
  }
}

function post(body: unknown, headers: Record<string, string> = {}) {
  return new Request('https://example.com/api/contact', {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'cf-connecting-ip': '203.0.113.7', ...headers },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
}

/** Imported fresh per test so module-level state cannot leak between cases. */
async function route() {
  return import('@/app/api/contact/route');
}

/**
 * The options object the mailer was called with.
 *
 * A helper rather than `sendMail.mock.calls[0][0]` inline: under
 * `noUncheckedIndexedAccess` that index is `possibly undefined`, and asserting
 * the call happened first makes a missing call fail with "expected 0 to be 1"
 * rather than a `TypeError` three lines later.
 */
function sentMail(): Record<string, unknown> {
  expect(sendMail).toHaveBeenCalled();
  return sendMail.mock.calls[0]![0] as Record<string, unknown>;
}

/** Turnstile accepts everything unless a test says otherwise. */
function stubTurnstile(response: unknown = { success: true }, ok = true) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok, status: ok ? 200 : 500, json: async () => response }) as Response),
  );
}

beforeEach(() => {
  vi.resetModules();
  __resetRateLimiter();
  sendMail.mockReset();
  sendMail.mockResolvedValue({ messageId: 'test' });
  stubTurnstile();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe('POST /api/contact', () => {
  describe('when the form is switched off', () => {
    it('returns 404 and sends nothing', async () => {
      configure({ CONTACT_FORM_ENABLED: 'false' });
      const { POST } = await route();
      const response = await POST(post(BODY));

      expect(response.status).toBe(404);
      expect(sendMail).not.toHaveBeenCalled();
    });

    it('returns 404 when the flag is absent entirely', async () => {
      configure({ CONTACT_FORM_ENABLED: undefined });
      const { POST } = await route();
      expect((await POST(post(BODY))).status).toBe(404);
      expect(sendMail).not.toHaveBeenCalled();
    });
  });

  describe('when the form is on but incompletely configured', () => {
    /**
     * The fail-closed requirement. Each of these is one missing variable away
     * from a working form, and every one of them must produce the *same* 404 a
     * switched-off form does rather than a form without that protection.
     */
    it.each([
      'TURNSTILE_SECRET_KEY',
      'CONTACT_RECIPIENT_EMAIL',
      'SMTP_HOST',
      'SMTP_USER',
      'SMTP_APP_PASSWORD',
      'CONTACT_RATE_LIMIT_SECRET',
    ])('returns 404 and sends nothing when %s is missing', async (variable) => {
      configure({ [variable]: undefined });
      const { POST } = await route();
      const response = await POST(post(BODY));

      expect(response.status).toBe(404);
      expect(sendMail).not.toHaveBeenCalled();
    });

    it('does not name the missing variable in the response', async () => {
      configure({ TURNSTILE_SECRET_KEY: undefined });
      const { POST } = await route();
      const body = await (await POST(post(BODY))).text();

      expect(body).not.toMatch(/TURNSTILE|SMTP|CONTACT_/i);
    });
  });

  describe('a valid submission', () => {
    it('is delivered, and answers 200', async () => {
      configure();
      const { POST } = await route();
      const response = await POST(post(BODY));

      expect(response.status).toBe(200);
      expect(await response.json()).toMatchObject({ ok: true });
      expect(sendMail).toHaveBeenCalledOnce();
    });

    it('sends to the configured recipient, from the SMTP account, replying to the visitor', async () => {
      configure();
      const { POST } = await route();
      await POST(post(BODY));

      const mail = sentMail();
      expect(mail.to).toBe('inbox@example.com');
      // Not the visitor: an unowned From fails SPF and DMARC.
      expect(mail.from).toBe('sender@example.com');
      expect(mail.replyTo).toContain('ingrid@example.com');
      expect(mail.subject).toContain(BODY.topic);
      expect(mail.text).toContain(BODY.message);
    });

    /**
     * The message is composed as text, never HTML. An anonymous stranger's
     * markup rendered in the recipient's mail client is the same class of
     * mistake as executing instructions found in an uploaded document.
     */
    it('composes plain text with no HTML part', async () => {
      configure();
      const { POST } = await route();
      await POST(post({ ...BODY, message: 'A message <script>alert(1)</script> with markup.' }));

      const mail = sentMail();
      expect(mail.html).toBeUndefined();
      expect(typeof mail.text).toBe('string');
    });

    /**
     * The delivered email is the deliverable. Every field the recipient needs
     * to act on the enquiry has to be in it - this is the assertion that stops
     * a privacy tightening from quietly stripping the contents and leaving a
     * notification nobody can answer.
     */
    it('carries every submitted field, plus a server timestamp', async () => {
      configure();
      const { POST } = await route();
      const before = Date.now();
      await POST(post(BODY));
      const after = Date.now();

      const text = String(sentMail().text);
      expect(text).toContain(BODY.name);
      expect(text).toContain(BODY.email);
      expect(text).toContain(BODY.organization);
      expect(text).toContain(BODY.topic);
      expect(text).toContain(BODY.message);
      expect(text).toContain(BODY.sourcePage);

      // An ISO 8601 UTC timestamp, taken from the server clock rather than
      // from anything the browser sent.
      const stamp = /Received:\s+(\S+)/.exec(text)?.[1];
      expect(stamp).toBeDefined();
      const parsed = Date.parse(String(stamp));
      expect(parsed).toBeGreaterThanOrEqual(before - 1000);
      expect(parsed).toBeLessThanOrEqual(after + 1000);
    });

    it('omits optional fields that were not supplied rather than printing them blank', async () => {
      configure();
      const { organization: _o, sourcePage: _s, ...minimal } = BODY;
      const { POST } = await route();
      await POST(post(minimal));

      const text = String(sentMail().text);
      expect(text).not.toMatch(/Organisation:/);
      expect(text).not.toMatch(/Source page:/);
      // The required ones are still there.
      expect(text).toContain(BODY.name);
      expect(text).toContain(BODY.message);
    });

    /**
     * The source page is browser-supplied, printed in an email a person reads,
     * and therefore exactly where an attacker would like to put a link. Only a
     * same-site path survives; anything else is dropped rather than sanitised
     * into something that still looks like an address.
     */
    it.each([
      ['an absolute URL', 'https://evil.example/reset-your-password'],
      ['a protocol-relative URL', '//evil.example/phish'],
      ['a scheme with no slashes', 'javascript:alert(1)'],
      ['a bare word', 'evil.example'],
    ])('drops a source page that is %s', async (_label, sourcePage) => {
      configure();
      const { POST } = await route();
      await POST(post({ ...BODY, sourcePage }));

      const text = String(sentMail().text);
      expect(text).not.toContain('evil.example');
      expect(text).not.toContain('javascript:');
      expect(text).not.toMatch(/Source page:/);
    });

    it('keeps a legitimate same-site path', async () => {
      configure();
      const { POST } = await route();
      await POST(post({ ...BODY, sourcePage: '/tools/spend-analytics-dashboard' }));

      expect(String(sentMail().text)).toContain('/tools/spend-analytics-dashboard');
    });

    it('does not put the client address or the Turnstile token in the email', async () => {
      configure();
      const { POST } = await route();
      await POST(post(BODY));

      const serialised = JSON.stringify(sentMail());
      expect(serialised).not.toContain('203.0.113.7');
      expect(serialised).not.toContain(BODY.turnstileToken);
    });
  });

  describe('the honeypot', () => {
    /**
     * A bot must not learn it was caught. The response is byte-identical to a
     * real success, and nothing is sent - telling it otherwise tells its
     * author which field to leave alone next time.
     */
    it('answers exactly as a success does, and sends nothing', async () => {
      configure();
      const { POST } = await route();

      const real = await POST(post(BODY));
      const realBody = await real.json();
      sendMail.mockClear();

      const trapped = await POST(post({ ...BODY, company_website: 'https://spam.example' }));
      expect(trapped.status).toBe(real.status);
      expect(await trapped.json()).toEqual(realBody);
      expect(sendMail).not.toHaveBeenCalled();
    });
  });

  describe('validation', () => {
    it('rejects an invalid submission with field errors and sends nothing', async () => {
      configure();
      const { POST } = await route();
      const response = await POST(post({ ...BODY, email: 'not-an-address', message: 'short' }));

      expect(response.status).toBe(400);
      const body = await response.json();
      expect(body.errors).toHaveProperty('email');
      expect(body.errors).toHaveProperty('message');
      expect(sendMail).not.toHaveBeenCalled();
    });

    it('rejects a header-injection attempt in the subject', async () => {
      configure();
      const { POST } = await route();
      const response = await POST(post({ ...BODY, topic: 'Hi\r\nBcc: victim@example.com' }));

      expect(response.status).toBe(400);
      expect(sendMail).not.toHaveBeenCalled();
    });

    it.each([
      ['a body that is not JSON', 'this is not json'],
      ['a JSON array', '[]'],
      ['a JSON string', '"hello"'],
      ['a JSON null', 'null'],
    ])('rejects %s', async (_label, raw) => {
      configure();
      const { POST } = await route();
      const response = await POST(post(raw));

      expect(response.status).toBe(400);
      expect(sendMail).not.toHaveBeenCalled();
    });

    it('rejects a body over the size ceiling before parsing it', async () => {
      configure();
      const { POST } = await route();
      const response = await POST(post(BODY, { 'content-length': String(64 * 1024) }));

      expect(response.status).toBe(413);
      expect(sendMail).not.toHaveBeenCalled();
    });

    /**
     * The `Content-Length` check is not enough on its own: a chunked request
     * declares no length at all, so a body large enough to matter arrives with
     * nothing to check it against. The decoded text is measured again after
     * reading for exactly this case.
     */
    it('rejects an oversized body that declares no length', async () => {
      configure();
      const oversized = JSON.stringify({ ...BODY, message: 'x'.repeat(32 * 1024) });
      const request = new Request('https://example.com/api/contact', {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'cf-connecting-ip': '203.0.113.7' },
        // A stream body is sent chunked, so no Content-Length is set.
        body: new ReadableStream({
          start(controller) {
            controller.enqueue(new TextEncoder().encode(oversized));
            controller.close();
          },
        }),
        // Required by undici whenever the body is a stream.
        duplex: 'half',
      } as RequestInit & { duplex: 'half' });

      expect(request.headers.get('content-length')).toBeNull();

      const { POST } = await route();
      const response = await POST(request);

      expect(response.status).toBe(413);
      expect(sendMail).not.toHaveBeenCalled();
    });

    it('rejects a non-JSON content type', async () => {
      configure();
      const { POST } = await route();
      const response = await POST(post(BODY, { 'content-type': 'text/plain' }));

      expect(response.status).toBe(415);
      expect(sendMail).not.toHaveBeenCalled();
    });
  });

  describe('Turnstile', () => {
    it('refuses when Cloudflare rejects the token', async () => {
      configure();
      stubTurnstile({ success: false, 'error-codes': ['invalid-input-response'] });
      const { POST } = await route();
      const response = await POST(post(BODY));

      expect(response.status).toBe(403);
      expect(sendMail).not.toHaveBeenCalled();
    });

    it('refuses when siteverify is unreachable', async () => {
      configure();
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => {
          throw new Error('ECONNREFUSED');
        }),
      );
      const { POST } = await route();
      const response = await POST(post(BODY));

      expect(response.status).toBe(403);
      expect(sendMail).not.toHaveBeenCalled();
    });

    it('refuses when the token is missing from the payload', async () => {
      configure();
      const { turnstileToken: _omitted, ...withoutToken } = BODY;
      const { POST } = await route();
      const response = await POST(post(withoutToken));

      expect(response.status).toBe(403);
      expect(sendMail).not.toHaveBeenCalled();
    });

    it('does not reveal why verification failed', async () => {
      configure();
      stubTurnstile({ success: false, 'error-codes': ['invalid-input-secret'] });
      const { POST } = await route();
      const body = await (await POST(post(BODY))).text();

      // A response that distinguishes a wrong secret from a replayed token is
      // a diagnostic tool for whoever is probing the endpoint.
      expect(body).not.toContain('invalid-input-secret');
      expect(body).not.toMatch(/secret/i);
    });
  });

  describe('rate limiting', () => {
    it('rejects the request after the limit with a Retry-After header', async () => {
      configure();
      const { POST } = await route();

      for (let i = 0; i < 3; i += 1) {
        expect((await POST(post(BODY))).status, `request ${i + 1}`).toBe(200);
      }

      const blocked = await POST(post(BODY));
      expect(blocked.status).toBe(429);
      expect(Number(blocked.headers.get('Retry-After'))).toBeGreaterThan(0);
      expect(sendMail).toHaveBeenCalledTimes(3);
    });

    /**
     * The ordering that matters: an outbound HTTPS round trip to Cloudflare is
     * the most expensive step in this handler, and a flooder must not be able
     * to make the server pay for it on every request.
     */
    it('blocks before spending a Turnstile verification', async () => {
      configure();
      const { POST } = await route();
      for (let i = 0; i < 3; i += 1) {
        await POST(post(BODY));
      }

      const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
      const before = fetchMock.mock.calls.length;
      await POST(post(BODY));
      expect(fetchMock.mock.calls.length).toBe(before);
    });

    it('counts a failed validation against the quota', async () => {
      configure();
      const { POST } = await route();

      for (let i = 0; i < 3; i += 1) {
        expect((await POST(post({ ...BODY, email: 'nope' }))).status).toBe(400);
      }
      // Probing the validator has to cost the same as sending, or it is a free
      // oracle for whatever the validator reveals.
      expect((await POST(post(BODY))).status).toBe(429);
    });

    it('blocks a second address reusing an exhausted email', async () => {
      configure();
      const { POST } = await route();
      for (let i = 0; i < 3; i += 1) {
        await POST(post(BODY, { 'cf-connecting-ip': `198.51.100.${i}` }));
      }

      const response = await POST(post(BODY, { 'cf-connecting-ip': '198.51.100.200' }));
      expect(response.status).toBe(429);
    });
  });

  /**
   * The ordering requirement, asserted directly.
   *
   * The email bucket is keyed on attacker-chosen input. If it were charged
   * before Turnstile, anyone could type a third party's address, send junk
   * tokens until the bucket filled, and lock that person out of the contact
   * form for a whole window - an unauthenticated denial of service against
   * someone else, costing only the attacker's own IP quota.
   */
  describe('rate-limit ordering around Turnstile', () => {
    it('does not consume another address\'s allowance on failed Turnstile attempts', async () => {
      configure();
      stubTurnstile({ success: false, 'error-codes': ['invalid-input-response'] });
      const { POST } = await route();

      // The victim's address, submitted from many attacker IPs, all failing
      // the challenge. Enough attempts to exhaust the bucket several times over
      // if the email bucket were charged before verification.
      for (let i = 0; i < 9; i += 1) {
        const response = await POST(post(BODY, { 'cf-connecting-ip': `198.51.100.${i}` }));
        expect(response.status).toBe(403);
      }

      // The victim now submits, from their own address, and solves the
      // challenge. Their allowance must be untouched.
      stubTurnstile({ success: true });
      const victim = await POST(post(BODY, { 'cf-connecting-ip': '203.0.113.7' }));
      expect(victim.status).toBe(200);
      expect(sendMail).toHaveBeenCalledOnce();
    });

    it('still enforces the email limit across valid submissions from many IPs', async () => {
      configure();
      const { POST } = await route();

      for (let i = 0; i < 3; i += 1) {
        const response = await POST(post(BODY, { 'cf-connecting-ip': `192.0.2.${i}` }));
        expect(response.status, `submission ${i + 1}`).toBe(200);
      }

      // A fourth, from an address that has sent nothing: the IP bucket is
      // clean, so only the email bucket can reject this.
      const fourth = await POST(post(BODY, { 'cf-connecting-ip': '192.0.2.99' }));
      expect(fourth.status).toBe(429);
      expect(Number(fourth.headers.get('Retry-After'))).toBeGreaterThan(0);
      expect(sendMail).toHaveBeenCalledTimes(3);
    });

    it('gives the same 429 body for both buckets', async () => {
      configure();
      const { POST } = await route();

      for (let i = 0; i < 3; i += 1) await POST(post(BODY));
      const byIp = await POST(post(BODY));
      expect(byIp.status).toBe(429);
      const ipBody = await byIp.json();

      __resetRateLimiter();
      for (let i = 0; i < 3; i += 1) {
        await POST(post(BODY, { 'cf-connecting-ip': `192.0.2.${i}` }));
      }
      const byEmail = await POST(post(BODY, { 'cf-connecting-ip': '192.0.2.99' }));
      expect(byEmail.status).toBe(429);

      // Distinguishing them would confirm to a stranger that a given address
      // has been used here.
      expect(await byEmail.json()).toEqual(ipBody);
    });
  });

  describe('Turnstile hostname and action pinning', () => {
    const PINNED = {
      TURNSTILE_EXPECTED_HOSTNAMES: 'solveaihub.com,www.solveaihub.com',
      TURNSTILE_EXPECTED_ACTION: 'contact',
    };

    it.each(['solveaihub.com', 'www.solveaihub.com'])(
      'delivers when the token was solved on %s',
      async (hostname) => {
        configure(PINNED);
        stubTurnstile({ success: true, hostname, action: 'contact' });
        const { POST } = await route();

        expect((await POST(post(BODY))).status).toBe(200);
        expect(sendMail).toHaveBeenCalledOnce();
      },
    );

    /**
     * The site key is public, so anyone can host the same widget and have a
     * real challenge solved on their own page. Cloudflare will confirm that
     * token is genuine, because it is - the hostname is what makes the
     * confirmation specific to this site rather than to the key.
     */
    it.each([
      ['an attacker-controlled host', 'evil.example'],
      ['a lookalike subdomain', 'solveaihub.com.evil.example'],
      ['a bare subdomain that is not listed', 'staging.solveaihub.com'],
      ['an empty hostname', ''],
    ])('refuses a token solved on %s, and sends nothing', async (_label, hostname) => {
      configure(PINNED);
      stubTurnstile({ success: true, hostname, action: 'contact' });
      const { POST } = await route();

      expect((await POST(post(BODY))).status).toBe(403);
      expect(sendMail).not.toHaveBeenCalled();
    });

    it.each([
      ['a different action', 'newsletter'],
      ['no action at all', ''],
    ])('refuses a token carrying %s, and sends nothing', async (_label, action) => {
      configure(PINNED);
      stubTurnstile({ success: true, hostname: 'solveaihub.com', action });
      const { POST } = await route();

      expect((await POST(post(BODY))).status).toBe(403);
      expect(sendMail).not.toHaveBeenCalled();
    });

    it('does not reveal which pin failed', async () => {
      configure(PINNED);
      stubTurnstile({ success: true, hostname: 'evil.example', action: 'contact' });
      const { POST } = await route();
      const body = await (await POST(post(BODY))).text();

      expect(body).not.toMatch(/hostname|action|solveaihub/i);
    });
  });

  describe('SMTP failure', () => {
    it('answers 502 with a generic message and leaks no detail', async () => {
      configure();
      sendMail.mockRejectedValue(
        new Error('connect ECONNREFUSED smtp.example.com:587 for sender@example.com'),
      );
      const { POST } = await route();
      const response = await POST(post(BODY));

      expect(response.status).toBe(502);
      const text = await response.text();
      expect(text).not.toContain('smtp.example.com');
      expect(text).not.toContain('ECONNREFUSED');
      expect(text).not.toContain('sender@example.com');
    });
  });

  describe('logging', () => {
    /**
     * The privacy claim, asserted rather than assumed: a log line from this
     * endpoint must be useless to whoever steals the log.
     */
    it('never writes the message, the address, the email or the token', async () => {
      configure();
      const lines: string[] = [];
      const record = (...args: unknown[]) => void lines.push(args.join(' '));
      vi.spyOn(console, 'info').mockImplementation(record);
      vi.spyOn(console, 'error').mockImplementation(record);
      vi.spyOn(console, 'warn').mockImplementation(record);

      const { POST } = await route();
      await POST(post(BODY));
      await POST(post({ ...BODY, email: 'nope' }));
      stubTurnstile({ success: false, 'error-codes': ['invalid-input-response'] });
      await POST(post(BODY));

      const all = lines.join('\n');
      expect(all).not.toContain(BODY.message);
      expect(all).not.toContain(BODY.email);
      expect(all).not.toContain(BODY.name);
      expect(all).not.toContain(BODY.turnstileToken);
      expect(all).not.toContain(BODY.organization);
      expect(all).not.toContain(BODY.topic);
      expect(all).not.toContain(BODY.sourcePage);
      expect(all).not.toContain('203.0.113.7');
      expect(all).not.toContain('not-a-real-password');
      // It does say what happened.
      expect(all).toMatch(/outcome=/);
    });
  });
});

describe('other methods', () => {
  it.each(['GET', 'PUT', 'PATCH', 'DELETE'] as const)(
    '%s returns 404 rather than confirming the route exists',
    async (method) => {
      configure();
      const handlers = await route();
      const handler = handlers[method] as () => Promise<Response>;
      expect((await handler()).status).toBe(404);
    },
  );
});
