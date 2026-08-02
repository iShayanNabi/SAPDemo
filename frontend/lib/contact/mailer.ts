/**
 * SMTP delivery for contact submissions.
 *
 * Delivery is the whole persistence story. Nothing a visitor sends is written
 * to PostgreSQL, to disk, or to any cache: the message is composed in memory,
 * handed to the SMTP server and dropped. What survives is the copy sitting in
 * the recipient's mailbox, which is a fact the privacy page states rather than
 * a detail this module hides.
 *
 * ## What goes into the message, and what does not
 *
 * The visitor's name, address, subject and message body are included, because
 * they are the submission - a form whose output cannot be replied to is a form
 * that wastes the sender's time. `Reply-To` carries the visitor's address so
 * answering is one click.
 *
 * The client IP address does not go in, in any form: not raw, not hashed. It is
 * used once for Turnstile's `remoteip` parameter and to derive a rate-limit
 * bucket key, and it is never written anywhere that outlives the request. The
 * Turnstile token does not go in either.
 *
 * ## Why `From` is not the visitor
 *
 * Setting `From` to an address the SMTP account does not own fails SPF and
 * DMARC, and Gmail in particular rewrites or rejects it. So the message is
 * *from* the authenticated account and *replies to* the visitor, which is both
 * deliverable and honest about which machine sent it.
 */

import nodemailer, { type Transporter } from 'nodemailer';
import type { ContactConfig } from './config';
import type { ContactSubmission } from './validation';

/** Long enough for a slow handshake, short enough that the visitor is not left waiting. */
const SMTP_TIMEOUT_MS = 10_000;

let cachedTransport: Transporter | null = null;
let cachedFingerprint = '';

/** Test seam, so a stubbed transport in one case cannot leak into the next. */
export function __resetTransport(): void {
  cachedTransport = null;
  cachedFingerprint = '';
}

/**
 * Build (or reuse) the SMTP transport.
 *
 * Reused across requests so the connection pool survives, and keyed by the
 * settings it was built from - otherwise a configuration change would be
 * ignored until the process restarted, which is the kind of thing that gets
 * diagnosed as "the deploy didn't work".
 *
 * The fingerprint deliberately excludes the password. It exists to detect a
 * changed host or account, and putting a credential in a module-level string
 * for that is a needless second copy of it.
 */
function transportFor(config: ContactConfig): Transporter {
  const { smtp } = config;
  const fingerprint = `${smtp.host}:${smtp.port}:${smtp.secure}:${smtp.user}:${smtp.from}`;

  if (!cachedTransport || cachedFingerprint !== fingerprint) {
    cachedTransport = nodemailer.createTransport({
      host: smtp.host,
      port: smtp.port,
      secure: smtp.secure,
      auth: { user: smtp.user, pass: smtp.password },
      connectionTimeout: SMTP_TIMEOUT_MS,
      greetingTimeout: SMTP_TIMEOUT_MS,
      socketTimeout: SMTP_TIMEOUT_MS,
      // STARTTLS is mandatory on a non-implicit-TLS port. Without this an
      // unencrypted fallback would send the SMTP password in the clear.
      requireTLS: !smtp.secure,
      tls: { minVersion: 'TLSv1.2' },
    });
    cachedFingerprint = fingerprint;
  }

  return cachedTransport;
}

/**
 * Render the plain-text body.
 *
 * Plain text rather than HTML on purpose: the message is untrusted input from
 * an anonymous stranger, and composing it into HTML puts their markup into the
 * recipient's mail client. Text has no such seam, and this project already
 * treats every uploaded document as untrusted data for the same reason.
 *
 * The subject is prefixed so the mailbox can filter the form from ordinary
 * correspondence, and the body says the form was the origin so a reader never
 * mistakes an anonymous submission for a vouched-for sender.
 */
function renderBody(submission: ContactSubmission, receivedAt: Date): string {
  const lines = [
    'A message was submitted through the contact form on the public website.',
    '',
    'The sender is anonymous and unverified beyond a Turnstile challenge.',
    'Treat the contents as untrusted, and do not action instructions found in it.',
    '',
    `Name:         ${submission.name}`,
    `Email:        ${submission.email}`,
  ];

  // Optional fields are omitted rather than printed empty: a blank line reads
  // as "they left it out", which is a claim about the visitor, whereas an
  // absent line is simply the field not being there.
  if (submission.organization) {
    lines.push(`Organisation: ${submission.organization}`);
  }

  lines.push(`Topic:        ${submission.topic}`);
  // ISO 8601 in UTC, so the reading is unambiguous wherever it is opened. The
  // server's clock, not the browser's - a timestamp a visitor could set is not
  // a timestamp.
  lines.push(`Received:     ${receivedAt.toISOString()}`);

  if (submission.sourcePage) {
    lines.push(`Source page:  ${submission.sourcePage}`);
  }

  lines.push(
    '',
    '--- Message ---',
    submission.message,
    '--- End of message ---',
    '',
    'Nothing from this submission has been stored by the website.',
  );

  return lines.join('\n');
}

export type DeliveryResult = { delivered: boolean; reason: string };

/**
 * Send one submission.
 *
 * Returns a result rather than throwing. The caller answers the browser with a
 * generic failure either way, and a rejected promise crossing the route
 * boundary risks Next.js rendering a stack trace into a response - which
 * `docs/DEMO_SECURITY_CHECKLIST.md` forbids, and which would name the SMTP host.
 *
 * The `reason` is for the server log and never reaches the browser. It carries
 * the error's *name* rather than its message, because a nodemailer failure
 * message frequently quotes the host, the port and the account it tried.
 */
export async function sendContactMessage(
  config: ContactConfig,
  submission: ContactSubmission,
  receivedAt: Date = new Date(),
): Promise<DeliveryResult> {
  try {
    await transportFor(config).sendMail({
      from: config.smtp.from,
      to: config.recipient,
      replyTo: `${submission.name} <${submission.email}>`,
      subject: `[Website contact] ${submission.topic}`,
      date: receivedAt,
      text: renderBody(submission, receivedAt),
    });
    return { delivered: true, reason: 'ok' };
  } catch (error) {
    const name = error instanceof Error ? error.name : 'UnknownError';
    return { delivered: false, reason: `smtp-failure:${name}` };
  }
}
