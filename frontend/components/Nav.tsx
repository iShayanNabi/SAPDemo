'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';
import { DemoCta } from '@/components/DemoCta';
import { Logo } from '@/components/Logo';
import { DESKTOP_ONLY, DESKTOP_ONLY_FLEX, MOBILE_ONLY, type NavItem } from '@/lib/navigation';

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
 *
 * ## The three regions, and the width they have to fit in
 *
 * The row is the brand, the links and the action, as three flex children with
 * one `gap` between them rather than a scattering of margins. The brand is
 * `shrink-0`: it is the shortest item, and flex takes space from the shortest
 * item first - so the wordmark was being squeezed before any of the eight links
 * gave anything up.
 *
 * The row is `max-w-6xl`, the same container the page body uses, so the brand
 * lines up with the content below it. That leaves 1104px of content at *every*
 * desktop width - the container caps long before the window does, so 1280px and
 * 1920px offer exactly the same room, and no breakpoint can change that.
 *
 * Measured in the system font this header actually renders in, at its real
 * sizes and weights, what is in the row needs **1050px**: 460px of link text,
 * 280px of link padding, 56px of gaps between them, a 122px wordmark, a 140px
 * button and 32px of region spacing. That leaves ~54px, and the number is worth
 * knowing because it is the whole reason for two decisions here:
 *
 * * **One button, not two.** The header carried both Launch demo and Start a
 *   Conversation, which together needed 353px and overflowed a `max-w-6xl` row
 *   by about a hundred pixels at every desktop width - that overflow was what
 *   "cramped and uneven" actually was. The demonstration is the header action
 *   at both sizes; Contact stays as an ordinary link beside the other seven,
 *   and Start a Conversation is on the home page, the Services page and the
 *   footer, where it is the only route being offered rather than a second one
 *   next to a link that already goes there.
 * * **The short label.** `Launch demo` is 140px and `Launch interactive demo`
 *   is 224px - the full wording alone would spend the entire spacing budget
 *   below and put the links back to touching. The mobile menu, which has a
 *   whole row per item, spells it out.
 */
export function Nav({ items }: { items: readonly NavItem[] }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  const isCurrent = (href: string) =>
    href === '/' ? pathname === '/' : pathname === href || pathname?.startsWith(`${href}/`);

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3 sm:px-6">
        <Logo className="shrink-0 text-xl" />

        {/*
          One desktop region holding the two that belong together, so the
          spacing between the links and the actions is a single `gap` rather
          than a margin on one of them. `ml-auto` pushes the whole region right
          and leaves the brand where it is.
        */}
        <div className={`ml-auto items-center gap-4 ${DESKTOP_ONLY_FLEX}`}>
          <nav aria-label="Primary" className={DESKTOP_ONLY}>
            {/*
              `gap-2` on the list and `px-3.5` on each link: 36px between one
              label and the next, where it used to be 28. Both halves matter -
              the padding is what the hover and current-page background is
              drawn on, and the gap is what stops two of those backgrounds
              touching. Freed up by the header carrying one button instead of
              two; see the note above the component.
            */}
            <ul className="flex items-center gap-2">
              {items.map((link) => (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    aria-current={isCurrent(link.href) ? 'page' : undefined}
                    className="block rounded-md px-3.5 py-2 text-sm font-medium whitespace-nowrap text-slate-700 hover:bg-slate-100 hover:text-slate-900 aria-[current=page]:bg-slate-100 aria-[current=page]:text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white dark:aria-[current=page]:bg-slate-800 dark:aria-[current=page]:text-white"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>

          {/*
            A rule, not just a gap. The button is a different kind of thing from
            the eight links beside it, and at this density a gap alone reads as
            "the last link is spaced oddly".

            One button, and it is the demonstration. Start a Conversation is not
            here: Contact is already an ordinary link two positions to the left,
            and the call to action belongs where there is room to make it look
            like one - the page bodies, the footer and the mobile menu below.
          */}
          <div className="flex shrink-0 items-center border-l border-slate-200 pl-4 dark:border-slate-800">
            <DemoCta variant="secondary" className="px-3 py-2 text-sm">
              Launch demo
            </DemoCta>
          </div>
        </div>

        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-controls="mobile-navigation"
          className={`ml-auto shrink-0 rounded-md p-2 text-slate-700 ring-1 ring-slate-300 hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 ${MOBILE_ONLY} dark:text-slate-200 dark:ring-slate-700 dark:hover:bg-slate-800`}
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
          className={`border-t border-slate-200 px-4 pb-4 sm:px-6 ${MOBILE_ONLY} dark:border-slate-800`}
        >
          <ul className="flex flex-col gap-1 py-3">
            {items.map((link) => (
              <li key={link.href}>
                <Link
                  href={link.href}
                  onClick={() => setOpen(false)}
                  aria-current={isCurrent(link.href) ? 'page' : undefined}
                  className="block rounded-md px-3 py-3 text-base font-medium text-slate-700 hover:bg-slate-100 aria-[current=page]:bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 dark:text-slate-200 dark:hover:bg-slate-800 dark:aria-[current=page]:bg-slate-800"
                >
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
          {/*
            The same single action as the desktop header, spelled out in full
            because a stacked panel has a whole row for it. Start a Conversation
            is not here either: Contact is one of the links directly above, and
            two entries going to the same page - one a link, one a button - read
            as two destinations.
          */}
          <div className="border-t border-slate-200 pt-4 dark:border-slate-800">
            <DemoCta variant="secondary" className="w-full">
              Launch interactive demo
            </DemoCta>
          </div>
        </nav>
      ) : null}
    </header>
  );
}
