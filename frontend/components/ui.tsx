import Link from 'next/link';
import type { ReactNode } from 'react';
import { type OutputOrigin } from '@/content/modules';
import { originByKey } from '@/content/origins';

/** A centred page container. One definition, so every page lines up. */
export function Container({
  children,
  className = '',
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`mx-auto max-w-6xl px-4 sm:px-6 ${className}`}>{children}</div>;
}

/**
 * A page section with its heading.
 *
 * The heading level is a prop rather than fixed at `h2`, because a page with
 * three `h1`s or a jump from `h2` to `h4` is a page a screen-reader user cannot
 * navigate by heading - which is how most of them navigate.
 */
export function Section({
  id,
  title,
  lede,
  children,
  as: Heading = 'h2',
  className = '',
}: {
  id?: string;
  title?: string;
  lede?: string;
  children?: ReactNode;
  as?: 'h2' | 'h3';
  className?: string;
}) {
  return (
    <section id={id} className={`py-12 sm:py-16 ${className}`}>
      {title ? (
        <Heading className="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl dark:text-white">
          {title}
        </Heading>
      ) : null}
      {lede ? (
        <p className="mt-3 max-w-3xl text-lg leading-relaxed text-slate-600 dark:text-slate-300">
          {lede}
        </p>
      ) : null}
      {children ? <div className="mt-8">{children}</div> : null}
    </section>
  );
}

export function PageHeader({
  eyebrow,
  title,
  lede,
  children,
}: {
  eyebrow?: string;
  title: string;
  lede?: string;
  children?: ReactNode;
}) {
  return (
    <header className="border-b border-slate-200 bg-slate-50 py-14 sm:py-20 dark:border-slate-800 dark:bg-slate-900">
      <Container>
        {eyebrow ? (
          <p className="text-sm font-semibold uppercase tracking-wider text-sky-700 dark:text-sky-400">
            {eyebrow}
          </p>
        ) : null}
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl lg:text-5xl dark:text-white">
          {title}
        </h1>
        {lede ? (
          <p className="mt-4 max-w-3xl text-lg leading-relaxed text-slate-600 dark:text-slate-300">
            {lede}
          </p>
        ) : null}
        {children ? <div className="mt-8 flex flex-wrap gap-3">{children}</div> : null}
      </Container>
    </header>
  );
}

export function Card({
  children,
  className = '',
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-slate-900 ${className}`}
    >
      {children}
    </div>
  );
}

/** A labelled badge for one of the five output origins. */
export function OriginBadge({ origin }: { origin: OutputOrigin }) {
  const described = originByKey(origin);
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${described.className}`}
      title={described.summary}
    >
      {described.label}
    </span>
  );
}

/**
 * A list where each item is a claim about what the platform does.
 *
 * `variant` picks the marker: "computed" and "ai" are visually distinct because
 * the difference between them is the most important thing on the page.
 */
export function ClaimList({
  items,
  variant = 'computed',
}: {
  items: readonly string[];
  variant?: 'computed' | 'ai' | 'plain';
}) {
  const marker =
    variant === 'computed'
      ? 'before:bg-sky-600 dark:before:bg-sky-400'
      : variant === 'ai'
        ? 'before:bg-amber-500 dark:before:bg-amber-400'
        : 'before:bg-slate-400';

  return (
    <ul className="space-y-3">
      {items.map((item) => (
        <li
          key={item}
          className={`relative pl-6 text-slate-700 before:absolute before:left-0 before:top-2.5 before:size-2 before:rounded-full ${marker} dark:text-slate-300`}
        >
          {item}
        </li>
      ))}
    </ul>
  );
}

/** An ordered list of guided steps. */
export function Steps({ items }: { items: readonly string[] }) {
  return (
    <ol className="space-y-4">
      {items.map((item, index) => (
        <li key={item} className="flex gap-4">
          <span
            aria-hidden="true"
            className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-sky-600 text-sm font-semibold text-white"
          >
            {index + 1}
          </span>
          <span className="text-slate-700 dark:text-slate-300">{item}</span>
        </li>
      ))}
    </ol>
  );
}

/** A prominent, non-decorative notice. */
export function Callout({
  title,
  children,
  tone = 'info',
}: {
  title: string;
  children: ReactNode;
  tone?: 'info' | 'warning';
}) {
  const styles =
    tone === 'warning'
      ? 'border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/40'
      : 'border-sky-200 bg-sky-50 dark:border-sky-900 dark:bg-sky-950/40';

  return (
    <div className={`rounded-xl border p-6 ${styles}`}>
      <h3 className="text-base font-semibold text-slate-900 dark:text-white">{title}</h3>
      <div className="mt-2 space-y-2 text-sm leading-relaxed text-slate-700 dark:text-slate-300">
        {children}
      </div>
    </div>
  );
}

export function TextLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link
      href={href}
      className="font-medium text-sky-700 underline underline-offset-4 hover:text-sky-900 dark:text-sky-400 dark:hover:text-sky-300"
    >
      {children}
    </Link>
  );
}
