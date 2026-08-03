/**
 * The header, the brand lockup and the footer that repeats it.
 *
 * The failures this file exists for all look fine in a screenshot and are all
 * invisible to a test that reads the source:
 *
 * * **The brand's space was not a character.** `Solve AI` and `Hub` were two
 *   spans in a flex row with `gap-1` between them, so the wordmark *painted*
 *   correctly and its **text** was `Solve AIHub` - in a copy and paste, in a
 *   text-only client, in a search of the built HTML for the brand name. In the
 *   footer, where the product name sits under the brand, the same problem ran
 *   the two together: `Solve AIHubProcurement Intelligence Demo`. So every
 *   assertion below reads `textContent`, never the markup.
 * * **The row had no regions.** Brand, links and actions were three siblings
 *   under `justify-between` with one `gap-4`, and the brand was allowed to
 *   shrink - which is the first thing flex takes space from, being the
 *   shortest item.
 * * **Two navigations that agree today.** Asserted as one list rendered twice,
 *   not as two lists containing the same things.
 */

import { fireEvent, render, screen, within } from '@testing-library/react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { Footer } from '@/components/Footer';
import { Logo } from '@/components/Logo';
import { Nav } from '@/components/Nav';
import {
  CONTACT_CTA_HREF,
  CONTACT_CTA_LABEL,
  DESKTOP_ONLY,
  DESKTOP_ONLY_FLEX,
  MOBILE_ONLY,
  getNavItems,
} from '@/lib/navigation';
import { siteConfig } from '@/lib/site';

const navItems = getNavItems(siteConfig.servicesPageEnabled);

const BRAND = 'Solve AI Hub';
const PRODUCT = 'Procurement Intelligence Demo';

/** The rendered text of an element, with runs of whitespace collapsed. */
function text(node: Element | null | undefined): string {
  return (node?.textContent ?? '').replace(/\s+/g, ' ').trim();
}

/** The same, without collapsing - for asserting a space exists at all. */
function rawText(node: Element | null | undefined): string {
  return node?.textContent ?? '';
}

function openMobileMenu() {
  fireEvent.click(screen.getByRole('button', { name: /open menu/i }));
}

/* ------------------------------------------------------------------------ */
/* The brand lockup                                                          */
/* ------------------------------------------------------------------------ */

describe('the brand reads as one phrase', () => {
  it('renders "Solve AI Hub" with a real space in the text', () => {
    const { container } = render(<Logo />);
    const link = container.querySelector('a');

    expect(text(link)).toBe(BRAND);
    // The failure this catches: a flex gap between two spans paints a space and
    // writes none, so the text is `Solve AIHub` while the screenshot is right.
    expect(rawText(link)).toContain(BRAND);
    expect(rawText(link)).not.toContain('Solve AIHub');
    expect(rawText(link)).not.toContain('SolveAI Hub');
    expect(rawText(link)).not.toMatch(/Solve {2,}AI|AI {2,}Hub/);
  });

  it('keeps the phrase on one line', () => {
    const { container } = render(<Logo />);
    const wordmark = [...container.querySelectorAll('span')].find(
      (span) => text(span) === BRAND,
    );
    expect(wordmark, 'one element holding the whole brand phrase').toBeTruthy();
    expect(wordmark?.className).toContain('whitespace-nowrap');
  });

  it('is one semantic home link for the whole lockup', () => {
    const { container } = render(<Logo withProductName />);
    const links = container.querySelectorAll('a');

    expect(links).toHaveLength(1);
    expect(links[0]?.getAttribute('href')).toBe('/');
    expect(links[0]?.getAttribute('aria-label')).toBe(`${siteConfig.fullName} home`);
    // No second interactive element inside the lockup.
    expect(container.querySelectorAll('a a, a button')).toHaveLength(0);
  });

  it('separates the parent brand from the product name in the lockup', () => {
    const { container } = render(<Logo withProductName />);
    const link = container.querySelector('a');

    expect(rawText(link)).not.toContain(`${BRAND}${PRODUCT}`);
    expect(rawText(link)).not.toContain('Solve AIHub');
    expect(text(link)).toBe(`${BRAND} ${PRODUCT}`);
    expect(text(link)).toContain(PRODUCT);
  });

  it('prints the product name only where it was asked for', () => {
    const { container } = render(<Logo />);
    // The header lockup is the brand alone; the full name is the accessible
    // name, so a screen-reader user still hears what the site is.
    expect(text(container.querySelector('a'))).toBe(BRAND);
    expect(container.querySelector('a')?.getAttribute('aria-label')).toContain(PRODUCT);
  });
});

/* ------------------------------------------------------------------------ */
/* The header                                                                */
/* ------------------------------------------------------------------------ */

describe('the header', () => {
  it('renders the brand correctly spaced', () => {
    const { container } = render(<Nav items={navItems} />);
    const header = container.querySelector('header');

    expect(rawText(header)).toContain(BRAND);
    expect(rawText(header)).not.toContain('Solve AIHub');
    expect(rawText(header)).not.toContain('SolveAI Hub');
  });

  it('gives the brand and the navigation separate regions, and does not shrink the brand', () => {
    const { container } = render(<Nav items={navItems} />);
    const brand = container.querySelector('a[href="/"]');
    const nav = container.querySelector('nav[aria-label="Primary"]');

    expect(brand?.className).toContain('shrink-0');
    // Separate regions: the navigation is not a child of the brand link, and
    // the row that holds them both is a flex container with a gap rather than
    // a pile of margins.
    expect(brand?.contains(nav!)).toBe(false);
    const row = brand?.parentElement;
    expect(row?.className).toContain('flex');
    expect(row?.className).toMatch(/\bgap-\d/);
  });

  it('spaces the desktop links and separates the action from them', () => {
    const { container } = render(<Nav items={navItems} />);
    const list = container.querySelector('nav[aria-label="Primary"] ul');
    const region = container.querySelector('nav[aria-label="Primary"]')?.parentElement;
    const actions = container.querySelector('nav[aria-label="Primary"]')?.nextElementSibling;

    // Links are spaced by a gap on the list *and* by padding on each link -
    // the padding is what the hover background is drawn on, the gap is what
    // keeps two of those backgrounds from touching. `gap-1`/`px-3` was the
    // tight version; this asserts the roomier one it was widened to.
    expect(list?.className).toMatch(/\bgap-2\b/);
    for (const link of list?.querySelectorAll('a') ?? []) {
      expect(link.className).toMatch(/\bpx-3\.5\b/);
      expect(link.className).toMatch(/\bpy-\d/);
      expect(link.className).toContain('whitespace-nowrap');
    }

    // The action is its own region, spaced and ruled off from the links.
    expect(region?.className).toMatch(/\bgap-\d/);
    expect(actions?.className).toContain('shrink-0');
    expect(actions?.className).toContain('border-l');
  });

  /**
   * One button in the header, and it is the demonstration.
   *
   * Both halves are asserted, because either alone passes on a version that is
   * wrong: dropping the button entirely satisfies "no duplicate call to
   * action", and keeping both satisfies "the demo is in the header".
   */
  it('keeps Launch interactive demo as the only button in the desktop header', () => {
    const { container } = render(<Nav items={navItems} />);
    const actions = container.querySelector(
      'nav[aria-label="Primary"]',
    )?.nextElementSibling as HTMLElement;

    const buttons = [...actions.querySelectorAll('a')];
    expect(buttons).toHaveLength(1);
    // Named by what it does and where it goes, not by its exact wording - the
    // header uses the short label because the full one costs 84px it does not
    // have. The action is the demonstration either way.
    expect(buttons[0]?.textContent).toMatch(/launch/i);
    expect(buttons[0]?.getAttribute('href')).toBe(siteConfig.demoUrl);
    expect(buttons[0]?.getAttribute('target')).toBe('_blank');
    expect(buttons[0]?.getAttribute('rel')).toContain('noopener');
  });

  /**
   * One route to the contact page from the header, at both sizes.
   *
   * Asserted as a pair, because removing the call to action is only right if
   * the ordinary link is still there: a header with neither would pass "no
   * duplicate" while having quietly lost the page. So each half checks that
   * exactly one entry goes to `/contact`, and that it is the navigation link.
   */
  it('offers one route to the contact page, and it is the navigation link', () => {
    const { container } = render(<Nav items={navItems} />);

    const toContact = () =>
      [...container.querySelectorAll('a')].filter(
        (anchor) => anchor.getAttribute('href') === '/contact',
      );

    // Closed: the desktop header is eight links and the demonstration button.
    expect(within(container).queryByRole('link', { name: CONTACT_CTA_LABEL })).toBeNull();
    expect(toContact().map((anchor) => text(anchor))).toEqual(['Contact']);
    expect(toContact()[0]?.getAttribute('href')).toBe(CONTACT_CTA_HREF);

    // Open: the panel is the same list plus the same one action. Two entries
    // going to the same page - one a link, one a button - read as two places.
    openMobileMenu();
    expect(within(container).queryByRole('link', { name: CONTACT_CTA_LABEL })).toBeNull();
    expect(toContact().map((anchor) => text(anchor))).toEqual(['Contact', 'Contact']);

    const panel = container.querySelector('#mobile-navigation') as HTMLElement;
    const actions = [...panel.querySelectorAll('a')].filter(
      (anchor) => anchor.className.includes('w-full'),
    );
    expect(actions).toHaveLength(1);
    expect(actions[0]?.textContent).toMatch(/launch interactive demo/i);
    expect(actions[0]?.getAttribute('href')).toBe(siteConfig.demoUrl);
  });

  it('keeps the row aligned with the page container', () => {
    // The header used to be widened to `max-w-7xl` to fit two buttons, which
    // left the brand sitting 64px outside the body content on a wide screen.
    // One button fits the shared container, so it uses it.
    const { container } = render(<Nav items={navItems} />);
    const row = container.querySelector('a[href="/"]')?.parentElement;
    expect(row?.className).toContain('max-w-6xl');
    expect(row?.className).not.toContain('max-w-7xl');
  });

  it('nests no interactive element inside another', () => {
    const { container } = render(<Nav items={navItems} />);
    openMobileMenu();
    for (const selector of ['a a', 'a button', 'button a', 'button button', 'a [role="button"]']) {
      expect(container.querySelectorAll(selector), selector).toHaveLength(0);
    }
  });

  it('sets no fixed pixel width that could overflow a narrow window', () => {
    const { container } = render(<Nav items={navItems} />);
    openMobileMenu();
    const html = container.innerHTML;
    expect(html).not.toMatch(/style="[^"]*width:\s*\d{3,}px/);
    expect(html).not.toMatch(/\bw-\[\d{3,}px\]/);
    expect(html).not.toMatch(/\bmin-w-\[\d{3,}px\]/);
    // A row that may not wrap and may not shrink is the shape that overflows.
    expect(container.querySelector('header > div')?.className).not.toMatch(/\boverflow-visible\b/);
  });
});

/* ------------------------------------------------------------------------ */
/* One navigation, two viewports                                             */
/* ------------------------------------------------------------------------ */

describe('the desktop and mobile navigations', () => {
  it('render the same shared list, in the same order, with no duplicates', () => {
    const { container } = render(<Nav items={navItems} />);
    openMobileMenu();

    const hrefsIn = (selector: string) =>
      [...container.querySelectorAll(`${selector} ul a`)].map((a) => a.getAttribute('href'));

    const desktop = hrefsIn('nav[aria-label="Primary"]');
    const mobile = hrefsIn('nav[aria-label="Primary (mobile)"]');

    expect(desktop).toEqual(navItems.map((item) => item.href));
    expect(mobile).toEqual(desktop);
    expect(new Set(desktop).size, 'desktop duplicates').toBe(desktop.length);
    expect(new Set(mobile).size, 'mobile duplicates').toBe(mobile.length);
  });

  it('keeps every required label in both', () => {
    const { container } = render(<Nav items={navItems} />);
    openMobileMenu();

    const required = ['Home', 'Platform', 'Tools', 'How it works', 'Architecture', 'About', 'Contact'];
    for (const selector of ['nav[aria-label="Primary"]', 'nav[aria-label="Primary (mobile)"]']) {
      const labels = [...container.querySelectorAll(`${selector} ul a`)].map((a) => text(a));
      for (const label of required) {
        expect(labels, `${label} in ${selector}`).toContain(label);
      }
      // No label ran into its neighbour, and none is blank.
      for (const label of labels) {
        expect(label.length).toBeGreaterThan(0);
      }
    }
  });

  it('agrees with itself about where the hamburger takes over', () => {
    // Three places have to use the same breakpoint - the links, the actions
    // region and the toggle - and a mismatch shows both navigations at once,
    // or neither, at some window width. jsdom cannot see that, so assert the
    // classes come from the shared constants.
    expect(DESKTOP_ONLY).toBe('hidden xl:block');
    expect(DESKTOP_ONLY_FLEX).toBe('hidden xl:flex');
    expect(MOBILE_ONLY).toBe('xl:hidden');
    // The `flex` variant exists because `hidden xl:block` cannot be composed
    // with `flex`; both are `display`. It must still name the same breakpoint.
    expect(DESKTOP_ONLY_FLEX.replace('flex', 'block')).toBe(DESKTOP_ONLY);

    const { container } = render(<Nav items={navItems} />);
    expect(container.querySelector('nav[aria-label="Primary"]')?.className).toBe(DESKTOP_ONLY);
    expect(
      container.querySelector('nav[aria-label="Primary"]')?.parentElement?.className,
    ).toContain(DESKTOP_ONLY_FLEX);
    expect(screen.getByRole('button', { name: /open menu/i }).className).toContain(MOBILE_ONLY);
  });
});

/* ------------------------------------------------------------------------ */
/* The mobile menu                                                           */
/* ------------------------------------------------------------------------ */

describe('the mobile menu', () => {
  it('has an accessible name that changes with its state, and a visible focus ring', () => {
    render(<Nav items={navItems} />);
    const button = screen.getByRole('button', { name: /open menu/i });

    expect(button.getAttribute('aria-expanded')).toBe('false');
    expect(button.getAttribute('aria-controls')).toBe('mobile-navigation');
    expect(button.className).toContain('focus-visible:outline-2');

    fireEvent.click(button);
    expect(screen.getByRole('button', { name: /close menu/i }).getAttribute('aria-expanded')).toBe(
      'true',
    );
  });

  it('opens and closes', () => {
    const { container } = render(<Nav items={navItems} />);
    const menu = () => container.querySelector('#mobile-navigation');

    expect(menu()).toBeNull();
    openMobileMenu();
    expect(menu()).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /close menu/i }));
    expect(menu()).toBeNull();
  });

  it('closes when a link inside it is followed', () => {
    const { container } = render(<Nav items={navItems} />);
    openMobileMenu();
    const link = container.querySelector('#mobile-navigation ul a') as HTMLElement;
    fireEvent.click(link);
    expect(container.querySelector('#mobile-navigation')).toBeNull();
  });

  it('gives every link a full-width target and consistent spacing', () => {
    const { container } = render(<Nav items={navItems} />);
    openMobileMenu();
    const list = container.querySelector('#mobile-navigation ul');

    expect(list?.className).toMatch(/\bgap-\d/);
    for (const link of list?.querySelectorAll('a') ?? []) {
      // `block` is what makes the whole row tappable rather than the glyphs.
      expect(link.className).toContain('block');
      expect(link.className).toMatch(/\bpy-\d/);
      expect(link.className).toContain('focus-visible:outline-2');
    }

    // The one action below them is full width too, and opens the demonstration.
    const action = within(container.querySelector('#mobile-navigation') as HTMLElement).getByRole(
      'link',
      { name: /launch interactive demo/i },
    );
    expect(action.className).toContain('w-full');
    expect(action.getAttribute('href')).toBe(siteConfig.demoUrl);
    expect(action.getAttribute('target')).toBe('_blank');
  });
});

/* ------------------------------------------------------------------------ */
/* The markup a browser is actually served                                   */
/* ------------------------------------------------------------------------ */

/**
 * The same assertions against server-rendered HTML rather than a jsdom tree.
 *
 * `next build` writes this markup to `.next/server/app/*.html`, and it is what
 * a visitor with no JavaScript, a crawler, or anybody reading the page source
 * sees. Reading it as *text* is the point: the brand's two halves are separate
 * elements, so a raw substring search for the phrase fails whether the space is
 * there or not, and only stripping the tags asks the question that matters.
 */
describe('the served markup', () => {
  const markup = () =>
    renderToStaticMarkup(
      <>
        <Nav items={navItems} />
        <Footer />
      </>,
    );

  /** The markup as a reader sees it: tags removed, entities left alone. */
  const asText = (html: string) => html.replace(/<[^>]*>/g, '');

  it('spells the brand with its space', () => {
    const html = markup();
    expect(asText(html)).toContain(BRAND);
    expect(asText(html)).not.toContain('Solve AIHub');
    expect(asText(html)).not.toContain('SolveAI Hub');
    // And not merely as an accessible name in an attribute.
    expect(asText(html.replace(/aria-label="[^"]*"/g, ''))).toContain(BRAND);
  });

  it('does not run the brand into the product name', () => {
    expect(asText(markup())).not.toContain(`${BRAND}${PRODUCT}`);
  });

  it('serves the header with the demonstration button and the Contact link', () => {
    const html = renderToStaticMarkup(<Nav items={navItems} />);

    // The one button in the header, in the markup a browser is handed.
    expect(html).toContain(`href="${siteConfig.demoUrl}"`);
    expect(html).toMatch(/target="_blank"/);
    expect(asText(html)).toMatch(/Launch demo/);
    // Contact is still an ordinary link, and the call to action is not here.
    expect(html).toMatch(/href="\/contact"[^>]*>Contact</);
    expect(asText(html)).not.toContain(CONTACT_CTA_LABEL);
    expect(html.match(/href="\/contact"/g) ?? []).toHaveLength(1);
  });

  it('serves the call to action as a link to /contact carrying no address', () => {
    const html = markup();
    expect(html).toContain(`href="/contact"`);
    expect(html).toMatch(new RegExp(`href="/contact"[^>]*>${CONTACT_CTA_LABEL}`));

    /*
     * The address is on the site and must stay - the footer's own mailto is a
     * link whose whole text is the address, on purpose. So this asks the
     * narrower question: no *button* carries it as a label. Matching the
     * address anywhere in the markup would fail on the link that is supposed
     * to have it, which is an assertion that gets deleted rather than fixed.
     */
    expect(html).toContain('mailto:solveaihub@gmail.com');
    const buttons = [...html.matchAll(/<a\b([^>]*)>(.*?)<\/a>/g)].filter(
      ([, attributes]) =>
        Boolean(attributes?.includes('rounded-lg') && attributes?.includes('font-semibold')),
    );
    expect(buttons.length).toBeGreaterThan(0);
    for (const [, , inner] of buttons) {
      expect(asText(inner ?? '')).not.toMatch(/@/);
    }
  });
});

/* ------------------------------------------------------------------------ */
/* The footer                                                                */
/* ------------------------------------------------------------------------ */

describe('the footer brand', () => {
  it('uses the shared lockup rather than a second copy of the wordmark', () => {
    const { container } = render(<Footer />);
    const home = [...container.querySelectorAll('a')].filter(
      (anchor) => anchor.getAttribute('href') === '/',
    );

    expect(home, 'one home link in the footer').toHaveLength(1);
    expect(home[0]?.getAttribute('aria-label')).toBe(`${siteConfig.fullName} home`);
  });

  it('does not concatenate the brand and the product name', () => {
    const { container } = render(<Footer />);
    const footerText = rawText(container.querySelector('footer'));

    expect(footerText).not.toContain(`${BRAND}${PRODUCT}`);
    expect(footerText).not.toContain('Solve AIHub');
    expect(footerText).not.toContain('SolveAI Hub');
    expect(footerText).not.toContain('Solve AIHubProcurement Intelligence Demo');
    // Both are still there, correctly spelled and correctly spaced.
    expect(footerText).toContain(BRAND);
    expect(footerText).toContain(PRODUCT);
  });

  it('keeps its links and its call to action', () => {
    const { container } = render(<Footer />);
    const cta = within(container).getByRole('link', { name: CONTACT_CTA_LABEL });

    expect(cta.getAttribute('href')).toBe('/contact');
    expect(cta.textContent).not.toContain('@');
    // The three link columns survive a spacing change.
    for (const heading of ['Project', 'Using it', 'Legal']) {
      expect(within(container).getByRole('navigation', { name: heading })).toBeTruthy();
    }
    expect(container.querySelectorAll('a a')).toHaveLength(0);
  });
});
