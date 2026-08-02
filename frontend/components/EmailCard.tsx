import type { ReactNode } from 'react';
import { mailto, siteConfig } from '@/lib/site';

/**
 * A card that is a direct-email action, and nothing else.
 *
 * The whole card is **one anchor**. It used to be a `Card` div holding a
 * separate link at the bottom, which is the shape that invites the wrong fix:
 * making the surrounding box clickable by wrapping it in a second anchor
 * produces nested interactive elements - invalid HTML that browsers unnest
 * unpredictably and that a screen reader announces as two links for one action.
 * One anchor wrapping flow content is valid, has a single accessible name and
 * needs no click handler, so there is none.
 *
 * The address is written in the card as well as being in the `href`. A visitor
 * with no mail client configured gets nothing from a `mailto:` they cannot
 * open, and copying an address they can read is the fallback that always works.
 *
 * `aria-label` names the action rather than leaving the accessible name to be
 * assembled from a heading, a paragraph and an arrow. When several of these
 * appear on one page the labels have to differ, so callers pass a suffix - two
 * links called the same thing are indistinguishable in a screen reader's link
 * list.
 */

/** The accessible name of a plain email card: what it does, and to whom. */
export const EMAIL_CARD_LABEL = `Email ${siteConfig.parentBrand} at ${siteConfig.contactEmail}`;

/** `EMAIL_CARD_LABEL` with a suffix, for pages carrying more than one card. */
export function emailCardLabel(about: string): string {
  return `${EMAIL_CARD_LABEL} about ${about}`;
}

export function EmailCard({
  title,
  body,
  subject,
  ariaLabel = EMAIL_CARD_LABEL,
  className = '',
}: {
  title: string;
  body?: ReactNode;
  /** The `?subject=` the compose window opens with. */
  subject: string;
  ariaLabel?: string;
  className?: string;
}) {
  return (
    <a
      href={mailto(subject)}
      aria-label={ariaLabel}
      className={
        'group flex h-full cursor-pointer flex-col rounded-xl border border-slate-200 bg-white p-6 ' +
        'transition-colors hover:border-sky-500 hover:bg-sky-50 ' +
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 ' +
        'dark:border-slate-800 dark:bg-slate-900 dark:hover:border-sky-500 dark:hover:bg-slate-800 ' +
        className
      }
    >
      {/*
        A heading inside the anchor rather than beside it. `a` takes flow
        content, so this is valid, and it keeps the card reachable by heading
        navigation - which is how most screen-reader users move down a page.
      */}
      <h3 className="text-lg font-semibold text-slate-900 dark:text-white">{title}</h3>
      {body ? (
        <p className="mt-3 flex-1 text-sm leading-relaxed text-slate-600 dark:text-slate-400">
          {body}
        </p>
      ) : null}
      <span className="mt-5 inline-flex items-center gap-1 text-sm font-semibold text-sky-700 underline underline-offset-4 group-hover:text-sky-900 dark:text-sky-400 dark:group-hover:text-sky-300">
        {siteConfig.contactEmail}
        <span aria-hidden="true">→</span>
      </span>
    </a>
  );
}
