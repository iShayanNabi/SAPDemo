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
