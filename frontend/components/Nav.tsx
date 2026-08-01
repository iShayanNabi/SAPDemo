'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';
import { DemoCta } from '@/components/DemoCta';
import { Logo } from '@/components/Logo';

export const navLinks = [
  { href: '/platform', label: 'Platform' },
  { href: '/tools', label: 'Tools' },
  { href: '/how-it-works', label: 'How it works' },
  { href: '/architecture', label: 'Architecture' },
  { href: '/services', label: 'Services' },
  { href: '/about', label: 'About' },
  { href: '/contact', label: 'Contact' },
] as const;

/**
 * The primary navigation.
 *
 * Built as a real `<nav>` containing a real list of real links, so it works
 * with a keyboard and a screen reader before any JavaScript decides how it
 * looks. The mobile disclosure is the only stateful part, and the button
 * carries `aria-expanded` and `aria-controls` rather than relying on the icon
 * to communicate its state.
 */
export function Nav() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  const isCurrent = (href: string) =>
    pathname === href || (href !== '/' && pathname?.startsWith(`${href}/`));

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <Logo className="text-xl" />

        <nav aria-label="Primary" className="hidden lg:block">
          <ul className="flex items-center gap-1">
            {navLinks.map((link) => (
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

        <div className="hidden lg:block">
          <DemoCta className="px-4 py-2 text-sm">Launch demo</DemoCta>
        </div>

        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-controls="mobile-navigation"
          className="rounded-md p-2 text-slate-700 ring-1 ring-slate-300 lg:hidden dark:text-slate-200 dark:ring-slate-700"
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
          className="border-t border-slate-200 px-4 pb-4 lg:hidden dark:border-slate-800"
        >
          <ul className="flex flex-col py-2">
            {navLinks.map((link) => (
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
          <DemoCta className="w-full">Launch interactive demo</DemoCta>
        </nav>
      ) : null}
    </header>
  );
}
