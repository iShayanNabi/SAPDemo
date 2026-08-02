import { describe, expect, it } from 'vitest';
import {
  FIELD_LIMITS,
  HONEYPOT_FIELD,
  isBotSubmission,
  validateSubmission,
} from '@/lib/contact/validation';

const valid = {
  name: 'Ingrid Nordwind',
  email: 'ingrid@example.com',
  organization: 'Nordwind GmbH',
  topic: 'A question about the spend module',
  sourcePage: '/contact',
  message: 'I would like to understand how the category rollup handles a missing material group.',
};

describe('validateSubmission', () => {
  it('accepts a well-formed submission and returns the normalised value', () => {
    const result = validateSubmission({ ...valid });
    expect(result.valid).toBe(true);
    if (result.valid) {
      expect(result.value).toEqual(valid);
    }
  });

  it('trims surrounding whitespace and lowercases the address', () => {
    const result = validateSubmission({ ...valid, name: '  Ingrid  ', email: 'Ingrid@Example.COM' });
    expect(result.valid).toBe(true);
    if (result.valid) {
      expect(result.value.name).toBe('Ingrid');
      // The rate limiter keys a bucket on this, so two spellings of one address
      // must not buy two allowances.
      expect(result.value.email).toBe('ingrid@example.com');
    }
  });

  it('reports every failing field at once rather than the first', () => {
    const result = validateSubmission({ name: '', email: 'nope', topic: '', message: 'short' });
    expect(result.valid).toBe(false);
    if (!result.valid) {
      expect(Object.keys(result.errors).sort()).toEqual(['email', 'message', 'name', 'topic']);
    }
  });

  it('treats a missing field, a non-string and an empty string identically', () => {
    for (const input of [{}, { name: 42 }, { name: '' }, { name: null }]) {
      const result = validateSubmission(input as Record<string, unknown>);
      expect(result.valid).toBe(false);
      if (!result.valid) {
        expect(result.errors.name).toMatch(/required/i);
      }
    }
  });

  describe('email addresses', () => {
    it.each([
      'plainaddress',
      'no@domain',
      'two@@example.com',
      'spaces in@example.com',
      'trailing@example.com.',
      '@example.com',
      'someone@.com',
      'a<b>@example.com',
      'someone@example,com',
    ])('rejects %s', (email) => {
      const result = validateSubmission({ ...valid, email });
      expect(result.valid).toBe(false);
      if (!result.valid) {
        expect(result.errors.email).toBeDefined();
      }
    });

    it.each([
      'someone@example.com',
      'first.last@sub.example.co.uk',
      'user+tag@example.com',
      "o'brien@example.ie",
    ])('accepts %s', (email) => {
      expect(validateSubmission({ ...valid, email }).valid).toBe(true);
    });
  });

  describe('header injection', () => {
    /**
     * The reason this rule exists: a newline in a header field ends the header
     * and starts one the sender chose, which turns a contact form into a relay
     * that will send to any `Bcc:` an attacker writes.
     */
    it.each([
      ['newline', 'Ingrid\nBcc: victim@example.com'],
      ['carriage return', 'Ingrid\rBcc: victim@example.com'],
      ['CRLF', 'Ingrid\r\nBcc: victim@example.com'],
      ['tab', 'Ingrid\tBcc: victim@example.com'],
    ])('rejects a %s in the name', (_label, name) => {
      const result = validateSubmission({ ...valid, name });
      expect(result.valid).toBe(false);
      if (!result.valid) {
        expect(result.errors.name).toMatch(/invalid characters/i);
      }
    });

    /**
     * Two mechanisms defend the header block, and they are not
     * interchangeable. `clean()` strips the control characters that carry no
     * meaning - a null byte, an escape - so they never reach the check above;
     * only tab, carriage return and newline survive stripping and are then
     * *rejected*, because those are the three that actually terminate or fold
     * a header.
     *
     * Asserting the stripped case as a rejection would be asserting the wrong
     * mechanism: it would pass just as happily if the strip list were emptied
     * and every control character fell through to the reject path instead.
     */
    it('strips a null byte rather than rejecting the submission', () => {
      const result = validateSubmission({ ...valid, name: 'Ingrid\u0000 Nordwind' });
      expect(result.valid).toBe(true);
      if (result.valid) {
        expect(result.value.name).toBe('Ingrid Nordwind');
      }
    });

    it('rejects the same in the topic', () => {
      const result = validateSubmission({ ...valid, topic: 'Hello\r\nBcc: victim@example.com' });
      expect(result.valid).toBe(false);
      if (!result.valid) {
        expect(result.errors.topic).toMatch(/invalid characters/i);
      }
    });

    /**
     * The body is not a header, and a message with paragraphs in it is the
     * normal case. Rejecting newlines here would break the form for everyone
     * to solve a problem the body does not have.
     */
    it('allows newlines in the message body', () => {
      const message = 'First paragraph about the module.\n\nSecond paragraph with more detail.';
      const result = validateSubmission({ ...valid, message });
      expect(result.valid).toBe(true);
      if (result.valid) {
        expect(result.value.message).toBe(message);
      }
    });

    it('strips other control characters from the body but keeps the text', () => {
      const result = validateSubmission({ ...valid, message: `${valid.message}\u0007\u001b` });
      expect(result.valid).toBe(true);
      if (result.valid) {
        expect(result.value.message).toBe(valid.message);
      }
    });
  });

  describe('length limits', () => {
    it('rejects a message below the minimum', () => {
      const result = validateSubmission({ ...valid, message: 'too short' });
      expect(result.valid).toBe(false);
      if (!result.valid) {
        expect(result.errors.message).toMatch(/at least 20 characters/i);
      }
    });

    it('rejects fields above their maximum', () => {
      const result = validateSubmission({
        ...valid,
        name: 'a'.repeat(FIELD_LIMITS.name.max + 1),
        topic: 'b'.repeat(FIELD_LIMITS.topic.max + 1),
        message: 'c'.repeat(FIELD_LIMITS.message.max + 1),
      });
      expect(result.valid).toBe(false);
      if (!result.valid) {
        expect(result.errors.name).toMatch(/100 characters or fewer/);
        expect(result.errors.topic).toMatch(/150 characters or fewer/);
        expect(result.errors.message).toMatch(/5000 characters or fewer/);
      }
    });

    it('accepts a value of exactly the maximum length', () => {
      const result = validateSubmission({
        ...valid,
        name: 'a'.repeat(FIELD_LIMITS.name.max),
        message: 'c'.repeat(FIELD_LIMITS.message.max),
      });
      expect(result.valid).toBe(true);
    });

    /**
     * Whitespace is trimmed *before* the length is measured, so a field of
     * five thousand spaces is empty rather than at the limit.
     */
    it('measures length after trimming', () => {
      const result = validateSubmission({ ...valid, name: '   ' });
      expect(result.valid).toBe(false);
      if (!result.valid) {
        expect(result.errors.name).toMatch(/required/i);
      }
    });
  });
});

describe('isBotSubmission', () => {
  it('is false when the honeypot is absent or empty', () => {
    expect(isBotSubmission({ ...valid })).toBe(false);
    expect(isBotSubmission({ ...valid, [HONEYPOT_FIELD]: '' })).toBe(false);
    expect(isBotSubmission({ ...valid, [HONEYPOT_FIELD]: '   ' })).toBe(false);
  });

  it('is true when the honeypot has been filled in', () => {
    expect(isBotSubmission({ ...valid, [HONEYPOT_FIELD]: 'https://spam.example' })).toBe(true);
  });
});
