/**
 * The contact form's topic list, and the `?service=` values that preselect one.
 *
 * This is the documented mapping between a link and a form state. A page that
 * knows what the visitor came to talk about - the Services page knows, because
 * they clicked the consulting call to action - can say so in the URL, and the
 * form opens with that topic already chosen.
 *
 * Two rules the implementation has to keep:
 *
 * * **The query value is untrusted.** It arrives from whatever the visitor
 *   typed in the address bar, so it selects a topic only by matching one of the
 *   keys below exactly. Anything else - a typo, an unknown service, a script
 *   fragment - resolves to the unselected state rather than becoming the topic.
 *   Nothing here ever renders the raw parameter.
 * * **A key is a promise.** `?service=consulting` appears in links, and the four
 *   keys below are the ones the site publishes. Renaming one silently turns a
 *   working link into a form with nothing selected, so the keys are stable and
 *   the labels are what may be reworded.
 *
 * Deliberately at `lib/` rather than under `lib/contact/`. Everything in that
 * directory except `validation.ts` reads a secret - the SMTP password, the
 * Turnstile secret, the rate-limit key - and `tests/contact-config.test.ts`
 * asserts that no `'use client'` component imports any of it. This module is
 * imported by the client form, holds no configuration and reads no environment,
 * so it belongs on the safe side of that boundary and its location says so.
 */

/** The query parameter a link uses to name the topic. */
export const SERVICE_QUERY_PARAM = 'service';

/** The state of the topic field when nothing has been chosen. */
export const UNSELECTED_TOPIC = '';

export interface ContactTopic {
  /** The `?service=` value. Published in links; do not rename. */
  readonly service: string;
  /** What the visitor sees, and what arrives in the email. */
  readonly label: string;
}

export const CONTACT_TOPICS = [
  { service: 'procurement-ai', label: 'Procurement and supply-chain analysis' },
  { service: 'document-intelligence', label: 'Document and data extraction' },
  { service: 'ai-prototyping', label: 'AI prototyping and evaluation' },
  { service: 'consulting', label: 'Collaboration or consulting' },
] as const satisfies readonly ContactTopic[];

/** The service key the consulting call to action links with. */
export const CONSULTING_SERVICE = 'consulting';

/** The topic that key selects. Named so a test cannot drift from the mapping. */
export const CONSULTING_TOPIC = 'Collaboration or consulting';

/**
 * The escape hatch for an enquiry none of the four describes.
 *
 * The field was free text before it was a list, and a list with no way out
 * turns "I want to talk about something else" into a form the visitor cannot
 * submit honestly. It has no `?service=` key because no link should preselect
 * it.
 */
export const OTHER_TOPIC = 'Something else';

/** Every option the topic field offers, in order. */
export const TOPIC_OPTIONS: readonly string[] = [
  ...CONTACT_TOPICS.map((topic) => topic.label),
  OTHER_TOPIC,
];

/**
 * The topic a `?service=` value selects, or the unselected state.
 *
 * Trimmed and lowercased before matching, because a hand-typed or
 * link-shortened URL is the ordinary case rather than an attack. Everything
 * that is not one of the four published keys returns `UNSELECTED_TOPIC` - the
 * visitor sees a form waiting for them to choose, which is the same thing they
 * would have seen with no parameter at all.
 */
export function topicForService(raw: string | null | undefined): string {
  if (typeof raw !== 'string') {
    return UNSELECTED_TOPIC;
  }
  const key = raw.trim().toLowerCase();
  const match = CONTACT_TOPICS.find((topic) => topic.service === key);
  return match ? match.label : UNSELECTED_TOPIC;
}
