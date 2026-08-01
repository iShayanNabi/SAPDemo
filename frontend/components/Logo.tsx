import Link from 'next/link';
import { siteConfig } from '@/lib/site';

/**
 * A text-based logo placeholder.
 *
 * Deliberately typographic rather than a mark: a placeholder image would either
 * be a shape nobody chose or a borrowed one, and this project must not carry
 * anybody else's brand assets. Replacing this with a real logo is a change to
 * this one component.
 */
export function Logo({ className = '' }: { className?: string }) {
  return (
    <Link
      href="/"
      className={`group inline-flex items-baseline gap-0.5 rounded-sm font-semibold tracking-tight focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-sky-600 ${className}`}
      aria-label={`${siteConfig.name} home`}
    >
      <span className="text-slate-900 dark:text-white">SAP</span>
      <span className="text-sky-600 dark:text-sky-400">Demo</span>
    </Link>
  );
}
