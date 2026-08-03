import { buildDemoUrl, type DemoModuleId } from '@/lib/demo';

/**
 * The Launch Interactive Demo call to action.
 *
 * The destination comes from `NEXT_PUBLIC_DEMO_URL` through `buildDemoUrl` and
 * is never hardcoded, so the same build serves a local run and a published one.
 * `rel="noopener"` is not optional on a `_blank` link: without it the opened
 * page can reach back through `window.opener`.
 *
 * With no `module`, this is the general demonstration home page - which is what
 * the header, the home page hero and every page-level call to action want.
 * Passing a module identifier opens that module directly, and only the ten
 * individual tool pages do it: a visitor who clicked *Purchase Order Risk
 * Checker* and then *Launch interactive demo* has already said which tool they
 * want, and making them find it again in a sidebar is a step for nothing.
 *
 * The identifier is navigation only. Cloudflare Access still stands in front of
 * the whole demonstration hostname and decides whether the request arrives at
 * all - see `docs/DEMO_MODULE_ROUTING.md`.
 */
export function DemoCta({
  children = 'Launch interactive demo',
  variant = 'primary',
  className = '',
  module,
}: {
  children?: React.ReactNode;
  variant?: 'primary' | 'secondary';
  className?: string;
  /** Open one module rather than the demonstration home page. */
  module?: DemoModuleId;
}) {
  const base =
    'inline-flex items-center justify-center gap-2 rounded-lg px-5 py-3 text-base font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2';
  const styles =
    variant === 'primary'
      ? 'bg-sky-600 text-white hover:bg-sky-700 focus-visible:outline-sky-600'
      : 'bg-white text-slate-900 ring-1 ring-slate-300 hover:bg-slate-50 focus-visible:outline-slate-600 dark:bg-slate-800 dark:text-white dark:ring-slate-600 dark:hover:bg-slate-700';

  return (
    <a
      href={buildDemoUrl(module)}
      target="_blank"
      rel="noopener noreferrer"
      className={`${base} ${styles} ${className}`}
    >
      {children}
      <span aria-hidden="true">→</span>
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  );
}
