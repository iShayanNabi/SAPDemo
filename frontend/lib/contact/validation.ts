/**
 * Field validation for a contact submission.
 *
 * Pure and dependency-free, so the same rules run in the browser for immediate
 * feedback and on the server for the decision that counts. The client copy is a
 * convenience; `app/api/contact/route.ts` re-runs every rule here on input it
 * assumes is hostile, because a browser check is a suggestion to anyone holding
 * `curl`.
 *
 * The limits live here as named constants rather than in a JSON config. The
 * project keeps *thresholds* in configuration because tuning them changes an
 * analytical result; these are transport limits, and a deployment that wants a
 * 12,000-character message wants a different form.
 */

export const FIELD_LIMITS = {
  name: { min: 1, max: 100 },
  email: { min: 3, max: 254 },
  organization: { min: 0, max: 120 },
  topic: { min: 1, max: 150 },
  message: { min: 20, max: 5000 },
  sourcePage: { min: 0, max: 200 },
} as const;

/** The field the browser fills in and a person never sees - see `isBotSubmission`. */
export const HONEYPOT_FIELD = 'company_website';

export type ContactSubmission = {
  name: string;
  email: string;
  /** Optional. `''` when the visitor did not supply one. */
  organization: string;
  topic: string;
  message: string;
  /**
   * The page the form was submitted from, or `''`.
   *
   * Supplied by the browser, so it is untrusted like every other field: it is
   * normalised to a same-site path here and is never used to build a link, a
   * redirect or a request. It exists so the recipient can tell an enquiry that
   * started on the Services page from one that started on a module page.
   */
  sourcePage: string;
};

export type ValidationResult =
  | { valid: true; value: ContactSubmission }
  | { valid: false; errors: Record<string, string> };

/**
 * A deliberately conservative address check.
 *
 * Not RFC 5322 - that grammar admits quoted strings and comments, and a form
 * that accepts `"a b"(c)@example.com` has widened its own attack surface to
 * satisfy nobody. One `@`, no whitespace, a dot in the domain, no leading or
 * trailing dot. Anything this rejects can still be sent by email, which is the
 * fallback the page keeps for exactly this reason.
 */
const EMAIL_PATTERN = /^[^\s@,;:<>()[\]\\"]+@[^\s@.]+(\.[^\s@.]+)+$/;

/**
 * Characters that let a value break out of the header block of an email.
 *
 * A newline in the name or subject is a header-injection attempt: it ends the
 * `Subject:` header and starts one the sender chose, which is how a form
 * becomes an open relay with a `Bcc:` of somebody else's choosing. Nodemailer
 * encodes headers and would refuse most of these, but the rule belongs here
 * where it is visible and tested rather than delegated to a library's internals.
 *
 * Written as escapes rather than literal bytes on purpose: a literal control
 * character in source is invisible in a diff and survives a careless edit.
 */
// eslint-disable-next-line no-control-regex
const HEADER_INJECTION = /[\x00-\x1f\x7f-\x9f]/;

/**
 * Strip control characters that carry no meaning in a plain-text message.
 *
 * Tab, newline and carriage return survive, because a message body is allowed
 * paragraphs. The rest of the C0 and C1 ranges do not: their only effect in an
 * inbox is to disguise what the text actually says.
 */
function clean(value: unknown): string {
  if (typeof value !== 'string') {
    return '';
  }
  // eslint-disable-next-line no-control-regex
  return value.replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]/g, '').trim();
}

function lengthError(label: string, value: string, min: number, max: number): string | null {
  if (value.length < min) {
    return value.length === 0
      ? `${label} is required.`
      : `${label} must be at least ${min} characters.`;
  }
  if (value.length > max) {
    return `${label} must be ${max} characters or fewer.`;
  }
  return null;
}

/**
 * Validate and normalise one submission.
 *
 * Returns every failing field at once. Reporting them one at a time turns a
 * form with four fields into four round trips, each of which costs the visitor
 * a fresh Turnstile challenge.
 */
export function validateSubmission(input: Record<string, unknown>): ValidationResult {
  const value: ContactSubmission = {
    name: clean(input.name),
    // Addresses are case-insensitive in practice, and lowercasing makes the
    // rate-limit bucket for one sender stable - see `lib/contact/rate-limit.ts`.
    email: clean(input.email).toLowerCase(),
    organization: clean(input.organization),
    topic: clean(input.topic),
    message: clean(input.message),
    sourcePage: normaliseSourcePage(input.sourcePage),
  };

  const errors: Record<string, string> = {};

  const nameError = lengthError('Name', value.name, FIELD_LIMITS.name.min, FIELD_LIMITS.name.max);
  if (nameError) errors.name = nameError;
  else if (HEADER_INJECTION.test(value.name)) errors.name = 'Name contains invalid characters.';

  const emailError = lengthError(
    'Email address',
    value.email,
    FIELD_LIMITS.email.min,
    FIELD_LIMITS.email.max,
  );
  if (emailError) errors.email = emailError;
  else if (!EMAIL_PATTERN.test(value.email)) errors.email = 'Enter a valid email address.';

  // Optional, so only an over-long or header-breaking value is an error.
  if (value.organization.length > FIELD_LIMITS.organization.max) {
    errors.organization = `Organisation must be ${FIELD_LIMITS.organization.max} characters or fewer.`;
  } else if (HEADER_INJECTION.test(value.organization)) {
    errors.organization = 'Organisation contains invalid characters.';
  }

  const topicError = lengthError(
    'Topic',
    value.topic,
    FIELD_LIMITS.topic.min,
    FIELD_LIMITS.topic.max,
  );
  if (topicError) errors.topic = topicError;
  else if (HEADER_INJECTION.test(value.topic)) errors.topic = 'Topic contains invalid characters.';

  const messageError = lengthError(
    'Message',
    value.message,
    FIELD_LIMITS.message.min,
    FIELD_LIMITS.message.max,
  );
  if (messageError) errors.message = messageError;

  return Object.keys(errors).length > 0 ? { valid: false, errors } : { valid: true, value };
}

/**
 * Reduce the reported source page to a same-site path, or nothing.
 *
 * The browser supplies this, so it is exactly as trustworthy as the message
 * body. It is printed in an email a person reads, which is precisely where an
 * attacker would like to place `https://example.com/reset-your-password`, so
 * anything that is not a plain same-site path is discarded rather than
 * sanitised into something that still looks like a link.
 *
 * Rejecting `//host/path` matters as much as rejecting `https://host/path`: a
 * protocol-relative URL starts with a slash and is a fully qualified address to
 * a browser. Silently dropping a value that fails is right - a missing line in
 * the email costs nothing, and there is nothing here worth reporting an error
 * to the visitor about.
 */
function normaliseSourcePage(raw: unknown): string {
  const value = clean(raw);
  if (!value.startsWith('/') || value.startsWith('//')) {
    return '';
  }
  if (value.length > FIELD_LIMITS.sourcePage.max) {
    return '';
  }
  // A path, a query and a fragment; nothing that could carry a scheme or a
  // second address.
  return /^\/[A-Za-z0-9\-._~!$&'()*+,;=:@/?#%[\]]*$/.test(value) ? value : '';
}

/**
 * Whether the honeypot was filled in.
 *
 * The field is rendered, labelled plausibly, moved off-screen and marked
 * `aria-hidden` with `tabIndex={-1}`, so a person using a mouse, a keyboard or
 * a screen reader never reaches it and a form-filling script cannot resist it.
 *
 * A hit is answered with the *same* success response a real submission gets.
 * Telling a bot it was detected is telling its author which field to skip.
 */
export function isBotSubmission(input: Record<string, unknown>): boolean {
  return clean(input[HONEYPOT_FIELD]).length > 0;
}
