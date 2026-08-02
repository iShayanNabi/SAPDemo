'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';
import { ContactCta } from '@/components/ContactCta';
import { DemoCta } from '@/components/DemoCta';
import { Logo } from '@/components/Logo';
import { DESKTOP_ONLY, MOBILE_ONLY, type NavItem } from '@/lib/navigation';

/**
 * The primary navigation.
 *
 * Built as a real `<nav>` containing a real list of real links, so it works
 * with a keyboard and a screen reader before any JavaScript decides how it
 * looks. The mobile disclosure is the only stateful part, and the button
 * carries `aria-expanded` and `aria-controls` rather than relying on the icon
 * to communicate its state.
 *
 * `items` is a prop rather than an import because one of the links is
 * conditional on `SERVICES_PAGE_ENABLED`, which is a server-side variable this
 * client component cannot read. The server resolves the list once and both the
 * desktop and mobile lists below map over that same array - there is no second
 * copy to fall out of step.
 */
export function Nav({ items }: { items: readonly NavItem[] }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  const isCurrent = (href: string) =>
    href === '/' ? pathname === '/' : pathname === href || pathname?.startsWith(`${href}/`);

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <Logo className="text-xl" />

        <nav aria-label="Primary" className={DESKTOP_ONLY}>
          <ul className="flex items-center gap-1">
            {items.map((link) => (
              <li key={link.href}>
                <Link
                  href={link.href}
                  aria-current={isCurrent(link.href) ? 'page' : undefined}
                  className="rounded-md px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 hover:text-slate-900 aria-[current=page]:bg-slate-100 aria-[current=page]:text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white dark:aria-[current=page]:bg-slate-800 dark:aria-[current=page]:text-white"
                >
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>

        <div className={`${DESKTOP_ONLY} shrink-0`}>
          <div className="flex items-center gap-2">
            <DemoCta variant="secondary" className="px-3 py-2 text-sm">
              Launch demo
            </DemoCta>
            <ContactCta className="px-4 py-2 text-sm" />
          </div>
        </div>

        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-controls="mobile-navigation"
          className={`rounded-md p-2 text-slate-700 ring-1 ring-slate-300 ${MOBILE_ONLY} dark:text-slate-200 dark:ring-slate-700`}
        >
          <span className="sr-only">{open ? 'Close menu' : 'Open menu'}</span>
          <span aria-hidden="true" className="block text-lg leading-none">
            {open ? '✕' : '☰'}
          </span>
        </button>
      </div>

      {open ? (
        <nav
          id="mobile-navigation"
          aria-label="Primary (mobile)"
          className={`border-t border-slate-200 px-4 pb-4 ${MOBILE_ONLY} dark:border-slate-800`}
        >
          <ul className="flex flex-col py-2">
            {items.map((link) => (
              <li key={link.href}>
                <Link
                  href={link.href}
                  onClick={() => setOpen(false)}
                  aria-current={isCurrent(link.href) ? 'page' : undefined}
                  className="block rounded-md px-3 py-2.5 text-base font-medium text-slate-700 hover:bg-slate-100 aria-[current=page]:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800 dark:aria-[current=page]:bg-slate-800"
                >
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
          <div className="flex flex-col gap-2">
            <ContactCta className="w-full" />
            <DemoCta variant="secondary" className="w-full">
              Launch interactive demo
            </DemoCta>
          </div>
        </nav>
      ) : null}
    </header>
  );
}
