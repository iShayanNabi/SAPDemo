import Link from 'next/link';
import { siteConfig } from '@/lib/site';

/**
 * A text-based logo placeholder.
 *
 * Deliberately typographic rather than a mark: a placeholder image would either
 * be a shape nobody chose or a borrowed one, and this project must not carry
 * anybody else's brand assets. Replacing this with a real logo is a change to
 * this one component.
 *
 * The wordmark is the parent brand; the product name is too long to sit in a
 * sticky header next to eight links. The accessible name carries both, so a
 * screen-reader user hears what the site is rather than only who publishes it,
 * and `withProductName` prints it where there is room - the footer.
 */
export function Logo({
  className = '',
  withProductName = false,
}: {
  className?: string;
  withProductName?: boolean;
}) {
  return (
    <Link
      href="/"
      className={`group inline-flex flex-col rounded-sm font-semibold tracking-tight focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-sky-600 ${className}`}
      aria-label={`${siteConfig.fullName} home`}
    >
      <span className="inline-flex items-baseline gap-1">
        <span className="text-slate-900 dark:text-white">Solve AI</span>
        <span className="text-sky-600 dark:text-sky-400">Hub</span>
      </span>
      {withProductName ? (
        <span
          aria-hidden="true"
          className="text-xs font-medium tracking-normal text-slate-600 dark:text-slate-400"
        >
          {siteConfig.name}
        </span>
      ) : null}
    </Link>
  );
}
