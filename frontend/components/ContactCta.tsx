import Link from 'next/link';

/**
 * A navigation call to action, and nothing else.
 *
 * This component **never renders an address**. It does not import
 * `@/lib/site`, so `siteConfig.contactEmail` is not reachable from here at all:
 * the way a button like this ends up displaying `solveaihub@gmail.com` is a
 * caller passing the address as its label, or a default that quietly resolves
 * to one, and a component that cannot read the address cannot do either.
 * Direct email is a separate component - `EmailCard` - which is allowed to
 * print the address because printing it is the whole point of that card.
 *
 * `href` and `children` are both **required**. They used to default to the
 * site-wide contact label and destination, which made every instance look
 * correct without saying anything: a page rendering `<ContactCta />` asserted
 * nothing about what it says or where it goes, and the label of every button
 * on the site moved together. Making them explicit means each call site names
 * its own pair, the labels come from `lib/navigation.ts` where they are shared
 * on purpose, and no single wording is hardcoded here for every instance.
 *
 * Always an internal `Link`, never a `mailto:` and never a new tab. A
 * `mailto:` from a marketing button opens a compose window with no context and
 * no idea what to write; the contact page names the three things worth writing
 * about and hands over a real address for each. The `mailto:` links still
 * exist - they are on the far side of this button.
 */
export function ContactCta({
  href,
  children,
  variant = 'primary',
  className = '',
}: {
  /** Where it goes. An internal path - `/contact`, or `/contact?service=...`. */
  href: string;
  /** The visible label, rendered exactly as given. */
  children: React.ReactNode;
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
    <Link href={href} className={`${base} ${styles} ${className}`}>
      {children}
      <span aria-hidden="true">→</span>
    </Link>
  );
}
