import type { ExamplePanel as ExamplePanelContent } from '@/content/examples';
import { OriginBadge } from '@/components/ui';

/**
 * One illustrative result, drawn with the site's own components.
 *
 * The caption on the section that renders these says what they are, and it is
 * not decoration: this repository contains no sanitised screenshot of the
 * application, and a picture of a dashboard invented for a marketing page is a
 * claim about a result that was never produced. A panel built out of the same
 * badges and typography the real pages use shows the *shape* of an answer
 * without pretending to be one.
 *
 * The computed half and the written half carry their own origin badges, which
 * is the same rule the application follows: the finding, the numbers and the
 * evidence are rule or forecast output, and the paragraph about them is not.
 * Merging the two into one panel with one label would illustrate exactly the
 * confusion this project exists to avoid.
 */
export function ExamplePanel({ panel }: { panel: ExamplePanelContent }) {
  return (
    <figure className="flex h-full flex-col rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-slate-900">
      <figcaption className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {panel.moduleName}
      </figcaption>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <h3 className="text-lg font-semibold text-slate-900 dark:text-white">{panel.title}</h3>
        <OriginBadge origin={panel.origin} />
      </div>

      <dl className="mt-4 space-y-2 text-sm">
        {panel.fields.map((field) => (
          <div key={field.label} className="flex flex-wrap gap-x-3 gap-y-1">
            <dt className="w-40 shrink-0 text-slate-500 dark:text-slate-400">{field.label}</dt>
            <dd className="font-medium text-slate-900 dark:text-slate-100">{field.value}</dd>
          </div>
        ))}
      </dl>

      <p className="mt-4 border-t border-slate-200 pt-4 text-sm leading-relaxed text-slate-600 dark:border-slate-800 dark:text-slate-400">
        {panel.evidence}
      </p>

      <div className="mt-4 rounded-lg bg-slate-50 p-4 dark:bg-slate-800/60">
        <OriginBadge origin={panel.narrative.origin} />
        <p className="mt-2 text-sm leading-relaxed text-slate-600 dark:text-slate-400">
          {panel.narrative.text}
        </p>
      </div>
    </figure>
  );
}
