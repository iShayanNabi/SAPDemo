import Link from 'next/link';
import { CONTACT_CTA_HREF, CONTACT_CTA_LABEL } from '@/lib/navigation';

/**
 * The primary "Start a Conversation" call to action.
 *
 * An internal `Link` to the contact page rather than a `mailto:`, deliberately.
 * A `mailto:` from a marketing button opens a compose window with no context
 * and no idea what to write; the contact page names the three things worth
 * writing about and hands over a real address for each. The `mailto:` links
 * still exist - they are on the far side of this button.
 *
 * The label lives in `lib/navigation.ts` so the navigation, the home page, the
 * services page and the footer cannot drift into three different wordings of
 * the same button.
 */
export function ContactCta({
  children = CONTACT_CTA_LABEL,
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
    <Link href={CONTACT_CTA_HREF} className={`${base} ${styles} ${className}`}>
      {children}
      <span aria-hidden="true">→</span>
    </Link>
  );
}
