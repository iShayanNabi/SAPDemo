import { siteConfig } from '@/lib/site';

/**
 * The Launch Interactive Demo call to action.
 *
 * The destination comes from `NEXT_PUBLIC_DEMO_URL` and is never hardcoded, so
 * the same build serves a local run and a published one. `rel="noopener"` is
 * not optional on a `_blank` link: without it the opened page can reach back
 * through `window.opener`.
 */
export function DemoCta({
  children = 'Launch interactive demo',
  variant = 'primary',
  className = '',
}: {
  children?: React.ReactNode;
  variant?: 'primary' | 'secondary';
  className?: string;
}) {
  const base =
    'inline-flex items-center justify-center gap-2 rounded-lg px-5 py-3 text-base font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2';
  const styles =
    variant === 'primary'
      ? 'bg-sky-600 text-white hover:bg-sky-700 focus-visible:outline-sky-600'
      : 'bg-white text-slate-900 ring-1 ring-slate-300 hover:bg-slate-50 focus-visible:outline-slate-600 dark:bg-slate-800 dark:text-white dark:ring-slate-600 dark:hover:bg-slate-700';

  return (
    <a
      href={siteConfig.demoUrl}
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
