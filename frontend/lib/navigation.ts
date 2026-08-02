/**
 * The one navigation configuration.
 *
 * Desktop and mobile render the *same array*, not two lists that happen to
 * agree today. A second copy is the kind of thing that stays correct until
 * somebody adds a page in a hurry, and then a link exists on a laptop and not
 * on a phone - which nobody notices, because nobody tests the site on both.
 *
 * `Nav` takes the resolved list as a prop rather than importing it, because
 * `SERVICES_PAGE_ENABLED` is a server-side variable. A client component reading
 * it would always see the default and could disagree with the server-rendered
 * markup around it.
 */

import { CONSULTING_SERVICE, SERVICE_QUERY_PARAM } from '@/lib/contact-topics';

export interface NavItem {
  href: string;
  label: string;
}

/**
 * Where the horizontal navigation gives way to the hamburger.
 *
 * Written as complete literal class strings rather than composed from an `xl`
 * constant: Tailwind finds classes by scanning source text, so a name built by
 * interpolation is a name it never sees and never generates. Naming them once
 * still matters, because three places have to agree - the desktop list, the
 * mobile list and the toggle button - and a mismatch shows both navigations at
 * once, or neither, at some window width.
 *
 * `xl` rather than `lg`: eight links, a demo button and the contact call to
 * action do not fit a 1024px window without wrapping.
 */
export const DESKTOP_ONLY = 'hidden xl:block';
export const MOBILE_ONLY = 'xl:hidden';

/**
 * The primary call to action. One label, one destination, used by the
 * navigation, the home page, the services page and the footer.
 */
export const CONTACT_CTA_LABEL = 'Start a Conversation';
export const CONTACT_CTA_HREF = '/contact';

/**
 * The consulting call to action, on the Services page.
 *
 * An internal link rather than a `mailto:`, for the reason `ContactCta`
 * documents: a compose window opened from a marketing button gives the visitor
 * a blank message and no idea what to write. This one carries the topic with
 * it, so the contact form opens with "Collaboration or consulting" already
 * chosen and the direct address still on the same page.
 *
 * The href is built from the mapping rather than written out, so renaming the
 * service key cannot leave this link pointing at a value the form ignores.
 */
export const CONSULTING_CTA_LABEL = 'Start a consulting conversation';
export const CONSULTING_CTA_HREF = `/contact?${SERVICE_QUERY_PARAM}=${CONSULTING_SERVICE}`;

/**
 * Every item in the primary navigation, in order.
 *
 * `/services` is the only conditional one; see `getNavItems`.
 */
const ALL_NAV_ITEMS: readonly NavItem[] = [
  { href: '/', label: 'Home' },
  { href: '/platform', label: 'Platform' },
  { href: '/tools', label: 'Tools' },
  { href: '/services', label: 'Services' },
  { href: '/how-it-works', label: 'How it works' },
  { href: '/architecture', label: 'Architecture' },
  { href: '/about', label: 'About' },
  { href: '/contact', label: 'Contact' },
] as const;

/**
 * The navigation for a given configuration.
 *
 * Takes the flag as an argument rather than reading the environment, so the
 * server resolves it once and both navigations receive the identical array -
 * and so a test can assert both states without stubbing anything.
 */
export function getNavItems(servicesPageEnabled: boolean): readonly NavItem[] {
  if (servicesPageEnabled) {
    return ALL_NAV_ITEMS;
  }
  return ALL_NAV_ITEMS.filter((item) => item.href !== '/services');
}
