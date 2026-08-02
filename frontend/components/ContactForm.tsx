'use client';

/**
 * The contact form.
 *
 * A client component because it holds field state, renders the Turnstile widget
 * and posts JSON. It receives the Turnstile *site* key as a prop from the
 * server component that renders it rather than reading configuration itself:
 * nothing under `lib/contact/` except `validation.ts` may be imported here, and
 * `tests/contact-config.test.ts` asserts that, because a single import of
 * `lib/contact/config.ts` would compile the SMTP password, the Turnstile secret
 * and the rate-limit HMAC key into the browser bundle.
 *
 * Everything this file checks is a courtesy to the visitor. The decision that
 * matters is made again in `app/api/contact/route.ts` on input it assumes is
 * hostile, and the two share `lib/contact/validation.ts` so they cannot drift.
 */

import { useCallback, useEffect, useId, useRef, useState } from 'react';
import Script from 'next/script';
import { FIELD_LIMITS, HONEYPOT_FIELD, validateSubmission } from '@/lib/contact/validation';

const TURNSTILE_SCRIPT = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';

type TurnstileApi = {
  render: (
    container: HTMLElement,
    options: {
      sitekey: string;
      action: string;
      callback: (token: string) => void;
      'expired-callback': () => void;
      'error-callback': () => void;
      theme: 'auto';
    },
  ) => string;
  reset: (widgetId?: string) => void;
  remove: (widgetId: string) => void;
};

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

type Status = 'idle' | 'submitting' | 'sent' | 'error';

const EMPTY = { name: '', email: '', organization: '', topic: '', message: '' };

/**
 * The `action` this widget declares, verified server-side against
 * `TURNSTILE_EXPECTED_ACTION`. It scopes a solved token to this form, so one
 * solved elsewhere under the same public site key does not verify here.
 */
const TURNSTILE_ACTION = 'contact';

export function ContactForm({ siteKey }: { siteKey: string }) {
  const [values, setValues] = useState(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<Status>('idle');
  const [notice, setNotice] = useState('');
  const [scriptReady, setScriptReady] = useState(false);

  const tokenRef = useRef<string>('');
  const widgetRef = useRef<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const fieldId = useId();

  const idFor = (field: string) => `${fieldId}-${field}`;
  const errorIdFor = (field: string) => `${fieldId}-${field}-error`;

  /**
   * Render the widget once the script has loaded.
   *
   * Guarded on `widgetRef` because React 19 strict mode runs effects twice in
   * development, and rendering twice would leave two challenges stacked on the
   * page with only the second one wired to a callback.
   */
  useEffect(() => {
    if (!scriptReady || !containerRef.current || widgetRef.current !== null) {
      return;
    }
    const api = window.turnstile;
    if (!api) {
      return;
    }

    widgetRef.current = api.render(containerRef.current, {
      sitekey: siteKey,
      action: TURNSTILE_ACTION,
      callback: (token) => {
        tokenRef.current = token;
      },
      // A Turnstile token is valid for a few minutes. Clearing it on expiry
      // means a form left open in a tab fails the *client* check with a clear
      // message instead of being rejected by the server for a stale token.
      'expired-callback': () => {
        tokenRef.current = '';
      },
      'error-callback': () => {
        tokenRef.current = '';
      },
      theme: 'auto',
    });

    return () => {
      if (widgetRef.current !== null) {
        window.turnstile?.remove(widgetRef.current);
        widgetRef.current = null;
      }
    };
  }, [scriptReady, siteKey]);

  /** A token is spent once it is submitted, successfully or not. */
  const resetChallenge = useCallback(() => {
    tokenRef.current = '';
    if (widgetRef.current !== null) {
      window.turnstile?.reset(widgetRef.current);
    }
  }, []);

  const update = (field: keyof typeof EMPTY) => (
    event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) => {
    setValues((current) => ({ ...current, [field]: event.target.value }));
    setErrors((current) => {
      if (!current[field]) return current;
      const next = { ...current };
      delete next[field];
      return next;
    });
  };

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (status === 'submitting') {
      return;
    }

    setNotice('');
    const validation = validateSubmission({ ...values });
    if (!validation.valid) {
      setErrors(validation.errors);
      setStatus('error');
      setNotice('Please correct the highlighted fields.');
      return;
    }

    if (!tokenRef.current) {
      setStatus('error');
      setNotice(
        'Please complete the "I am human" check below. If it has not appeared, reload the page.',
      );
      return;
    }

    setErrors({});
    setStatus('submitting');

    try {
      const response = await fetch('/api/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...validation.value,
          // Where the visitor was when they submitted. Reported to the
          // recipient, never trusted: the server reduces it to a same-site
          // path or drops it.
          sourcePage: typeof window === 'undefined' ? '' : window.location.pathname,
          // Always present and always empty for a person - see the field below.
          [HONEYPOT_FIELD]: '',
          turnstileToken: tokenRef.current,
        }),
      });

      const body: unknown = await response.json().catch(() => null);
      const payload = (body ?? {}) as { ok?: boolean; message?: string; errors?: Record<string, string> };

      if (response.ok && payload.ok) {
        setStatus('sent');
        setNotice(payload.message ?? 'Thank you - your message has been sent.');
        setValues(EMPTY);
      } else {
        setStatus('error');
        setErrors(payload.errors ?? {});
        setNotice(
          payload.message ?? 'Your message could not be sent. Please try again, or email us directly.',
        );
      }
    } catch {
      // A network failure, an offline browser or a navigation mid-request. The
      // visitor gets the same generic sentence either way.
      setStatus('error');
      setNotice('Your message could not be sent. Please try again, or email us directly.');
    } finally {
      resetChallenge();
    }
  }

  const fieldClass =
    'mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-900 shadow-sm ' +
    'focus:border-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-500 ' +
    'dark:border-slate-700 dark:bg-slate-900 dark:text-white';

  return (
    <form onSubmit={handleSubmit} noValidate className="max-w-2xl">
      <Script
        src={TURNSTILE_SCRIPT}
        strategy="afterInteractive"
        onReady={() => setScriptReady(true)}
      />

      <div className="grid gap-5 sm:grid-cols-2">
        <Field
          id={idFor('name')}
          errorId={errorIdFor('name')}
          label="Your name"
          error={errors.name}
        >
          <input
            id={idFor('name')}
            name="name"
            type="text"
            autoComplete="name"
            required
            maxLength={FIELD_LIMITS.name.max}
            value={values.name}
            onChange={update('name')}
            aria-invalid={Boolean(errors.name)}
            aria-describedby={errors.name ? errorIdFor('name') : undefined}
            className={fieldClass}
          />
        </Field>

        <Field
          id={idFor('email')}
          errorId={errorIdFor('email')}
          label="Your email address"
          error={errors.email}
        >
          <input
            id={idFor('email')}
            name="email"
            type="email"
            autoComplete="email"
            required
            maxLength={FIELD_LIMITS.email.max}
            value={values.email}
            onChange={update('email')}
            aria-invalid={Boolean(errors.email)}
            aria-describedby={errors.email ? errorIdFor('email') : undefined}
            className={fieldClass}
          />
        </Field>
      </div>

      <div className="mt-5 grid gap-5 sm:grid-cols-2">
        <Field
          id={idFor('organization')}
          errorId={errorIdFor('organization')}
          label="Organisation"
          error={errors.organization}
          hint="Optional."
        >
          <input
            id={idFor('organization')}
            name="organization"
            type="text"
            autoComplete="organization"
            maxLength={FIELD_LIMITS.organization.max}
            value={values.organization}
            onChange={update('organization')}
            aria-invalid={Boolean(errors.organization)}
            aria-describedby={errors.organization ? errorIdFor('organization') : undefined}
            className={fieldClass}
          />
        </Field>

        <Field id={idFor('topic')} errorId={errorIdFor('topic')} label="Topic" error={errors.topic}>
          <input
            id={idFor('topic')}
            name="topic"
            type="text"
            required
            maxLength={FIELD_LIMITS.topic.max}
            value={values.topic}
            onChange={update('topic')}
            aria-invalid={Boolean(errors.topic)}
            aria-describedby={errors.topic ? errorIdFor('topic') : undefined}
            className={fieldClass}
          />
        </Field>
      </div>

      <div className="mt-5">
        <Field
          id={idFor('message')}
          errorId={errorIdFor('message')}
          label="Message"
          error={errors.message}
          hint={`Between ${FIELD_LIMITS.message.min} and ${FIELD_LIMITS.message.max} characters.`}
        >
          <textarea
            id={idFor('message')}
            name="message"
            rows={8}
            required
            maxLength={FIELD_LIMITS.message.max}
            value={values.message}
            onChange={update('message')}
            aria-invalid={Boolean(errors.message)}
            aria-describedby={errors.message ? errorIdFor('message') : undefined}
            className={fieldClass}
          />
        </Field>
      </div>

      {/*
        The honeypot.

        Positioned off-screen rather than `display: none`: some form-filling
        bots skip hidden fields specifically to avoid this trap, but most will
        fill anything present in the DOM with a plausible name. `aria-hidden`
        and `tabIndex={-1}` keep it away from screen readers and the tab order,
        and `autoComplete="off"` stops a browser helpfully filling it in - which
        would make a real visitor look like a bot.
      */}
      <div aria-hidden="true" className="absolute left-[-9999px] h-px w-px overflow-hidden">
        <label htmlFor={idFor(HONEYPOT_FIELD)}>Company website</label>
        <input
          id={idFor(HONEYPOT_FIELD)}
          name={HONEYPOT_FIELD}
          type="text"
          tabIndex={-1}
          autoComplete="off"
          defaultValue=""
        />
      </div>

      <div ref={containerRef} className="mt-6" />

      <div className="mt-6 flex flex-wrap items-center gap-4">
        <button
          type="submit"
          disabled={status === 'submitting'}
          className="inline-flex items-center justify-center rounded-lg bg-sky-600 px-5 py-3 text-base font-semibold text-white transition-colors hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {status === 'submitting' ? 'Sending…' : 'Send message'}
        </button>
      </div>

      {/*
        One live region for every outcome. `role="status"` announces politely
        rather than interrupting, and it is always in the DOM - a region added
        to the page at the moment it gains text is frequently not announced.
      */}
      <p
        role="status"
        aria-live="polite"
        className={
          notice
            ? status === 'sent'
              ? 'mt-4 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200'
              : 'mt-4 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200'
            : 'sr-only'
        }
      >
        {notice}
      </p>
    </form>
  );
}

function Field({
  id,
  errorId,
  label,
  error,
  hint,
  children,
}: {
  id: string;
  errorId: string;
  label: string;
  error?: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-semibold text-slate-900 dark:text-white">
        {label}
      </label>
      {children}
      {hint && !error ? (
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{hint}</p>
      ) : null}
      {error ? (
        <p id={errorId} className="mt-1 text-xs font-medium text-red-700 dark:text-red-400">
          {error}
        </p>
      ) : null}
    </div>
  );
}
