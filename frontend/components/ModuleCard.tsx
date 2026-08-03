import Link from 'next/link';
import type { ModuleContent } from '@/content/modules';
import { OriginBadge } from '@/components/ui';

export function ModuleCard({ module }: { module: ModuleContent }) {
  return (
    <article className="group flex h-full flex-col rounded-xl border border-slate-200 bg-white p-6 transition-colors hover:border-sky-400 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-sky-500">
      <p className="text-sm font-semibold text-sky-700 dark:text-sky-400">
        Module {module.number}
      </p>
      <h3 className="mt-1 text-lg font-semibold text-slate-900 dark:text-white">
        {/* The whole card is clickable via this stretched link, but the link
            text itself is the module name - so the accessible name is the
            module, not "read more". */}
        <Link
          href={`/tools/${module.slug}`}
          className="after:absolute after:inset-0 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-sky-600"
        >
          <span className="relative">{module.name}</span>
        </Link>
      </h3>
      <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">{module.tagline}</p>
      <p className="mt-4 flex-1 text-sm leading-relaxed text-slate-600 dark:text-slate-400">
        {module.problem}
      </p>
      <div className="mt-5 flex flex-wrap gap-2">
        {module.origins.slice(0, 3).map((origin) => (
          <OriginBadge key={origin} origin={origin} />
        ))}
      </div>
    </article>
  );
}

export function ModuleGrid({ modules }: { modules: readonly ModuleContent[] }) {
  return (
    <ul className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
      {modules.map((module) => (
        <li key={module.id} className="relative">
          <ModuleCard module={module} />
        </li>
      ))}
    </ul>
  );
}

/**
 * The same ten tools, in the space the home page has for them.
 *
 * The card above renders `module.problem`, a paragraph, which is right on the
 * tools overview where somebody is choosing between them and wrong on a home
 * page that also has to carry a hero, six problem areas, a method explanation
 * and two calls to action. This one answers three questions in three lines,
 * from `module.overview` - the same content module, not a second list.
 *
 * A description list rather than three paragraphs: "what goes in", "what comes
 * out" and "what it is for" are labelled values, and a screen reader announcing
 * them as term-and-definition pairs conveys that structure. The `<div>` wrapper
 * around each pair is valid inside a `<dl>` and is what lets the label sit
 * beside its value instead of above it.
 */
export function CompactModuleCard({ module }: { module: ModuleContent }) {
  return (
    <article className="flex h-full flex-col rounded-xl border border-slate-200 bg-white p-5 transition-colors hover:border-sky-400 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-sky-500">
      <p className="text-xs font-semibold uppercase tracking-wide text-sky-700 dark:text-sky-400">
        {module.number}
      </p>
      <h3 className="mt-1 text-base font-semibold leading-snug text-slate-900 dark:text-white">
        {/* Stretched over the whole card, but the link text is the tool name,
            so the accessible name is the tool rather than "read more". */}
        <Link
          href={`/tools/${module.slug}`}
          className="after:absolute after:inset-0 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-sky-600"
        >
          <span className="relative">{module.name}</span>
        </Link>
      </h3>
      <dl className="mt-3 space-y-2 text-sm">
        {[
          ['In', module.overview.input],
          ['Out', module.overview.output],
          ['Why', module.overview.purpose],
        ].map(([label, value]) => (
          <div key={label} className="flex gap-2">
            <dt className="w-8 shrink-0 text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
              {label}
            </dt>
            {/* `min-w-0` so the value can wrap inside the column rather than
                forcing the row wider than the card. A flex child defaults to
                `min-width: auto`, which refuses to shrink below its longest
                word - fine for these phrases today, and the one line that stops
                a longer one overflowing the card at four columns. */}
            <dd className="min-w-0 text-slate-600 dark:text-slate-400">{value}</dd>
          </div>
        ))}
      </dl>
    </article>
  );
}

/**
 * The column ramp for the compact grid, as one literal string.
 *
 * Written out rather than composed, because Tailwind finds classes by scanning
 * source text and a name built by interpolation is a name it never generates -
 * the same reason `lib/navigation.ts` spells out its breakpoint constants. It is
 * exported so a test can assert the ramp rather than infer it from a rendered
 * class attribute nobody reads.
 *
 * **It stops at four, and there is a number behind that.** `Container` is
 * `max-w-6xl` with `sm:px-6`, so the content box is 1104px at *every* desktop
 * width - 1280, 1440, 1920 and 2560 all offer exactly the same room, because
 * the container caps long before the window does. With `gap-4` that makes the
 * card width a fixed property of the column count rather than of the viewport:
 *
 * | columns | card width |
 * | ------- | ---------- |
 * | 3       | 357px      |
 * | 4       | 264px      |
 * | 5       | 208px      |
 *
 * At five, 208px minus the card's own `p-5` leaves 168px for "Supplier
 * Recommendation Engine" and three label-and-value rows, which is a title
 * broken over four lines. Moving the five-column tier up to the 2xl breakpoint
 * would not fix it - 2xl is a *viewport* breakpoint and the container does not
 * grow with it, so the cards there would be the same 208px. Five columns is
 * therefore not a wider-screen option, it is the same cramped layout behind a
 * bigger media query, and the ramp ends at four.
 *
 * That tier is described in words rather than written as a class name on
 * purpose. Tailwind finds classes by scanning source text and does not know a
 * comment from markup, so naming it here generated a real five-column rule in
 * the stylesheet - dead CSS that this very comment argues must not exist.
 *
 * Four also divides the ten tools into 4 + 4 + 2 rather than 5 + 5. That is a
 * ragged last row, and it is the better trade: two readable cards on a short
 * row beat ten unreadable ones on two tidy ones.
 */
export const COMPACT_GRID_COLUMNS = 'sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4';

export function CompactModuleGrid({ modules }: { modules: readonly ModuleContent[] }) {
  return (
    <ul className={`grid gap-4 ${COMPACT_GRID_COLUMNS}`}>
      {modules.map((module) => (
        <li key={module.id} className="relative">
          <CompactModuleCard module={module} />
        </li>
      ))}
    </ul>
  );
}
