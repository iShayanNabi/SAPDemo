/**
 * The consulting call to action, the topic it preselects, and the email card.
 *
 * Three things are asserted here that a rendered page can hide from a reader:
 *
 * * a call to action whose label promises a conversation and whose `href` opens
 *   a compose window - the label and the destination are a *pair*, and only
 *   checking one of them passes on the version that is wrong;
 * * a query parameter that reaches the form: the four published keys must
 *   select their topic and everything else must select nothing, because the
 *   value comes from the address bar;
 * * a card that looks clickable. A box with a link at the bottom and a box that
 *   *is* a link render almost identically, and the wrong fix for the first -
 *   wrapping it in a second anchor - is invalid HTML that browsers unnest
 *   silently.
 *
 * Deliberately no snapshots. The copy on these pages is expected to change; the
 * relationships below are not.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fireEvent, render, screen, within } from '@testing-library/react';
import axe from 'axe-core';
import { describe, expect, it, vi } from 'vitest';
import ContactPage from '@/app/contact/page';
import HomePage from '@/app/page';
import ServicesPage from '@/app/services/page';
import { ContactCta } from '@/components/ContactCta';
import { ContactForm } from '@/components/ContactForm';
import { EMAIL_CARD_LABEL } from '@/components/EmailCard';
import {
  CONSULTING_SERVICE,
  CONSULTING_TOPIC,
  CONTACT_TOPICS,
  OTHER_TOPIC,
  SERVICE_QUERY_PARAM,
  TOPIC_OPTIONS,
  UNSELECTED_TOPIC,
  topicForService,
} from '@/lib/contact-topics';
import {
  CONSULTING_CTA_HREF,
  CONSULTING_CTA_LABEL,
  CONTACT_CTA_HREF,
  CONTACT_CTA_LABEL,
} from '@/lib/navigation';
import { buildDemoUrl } from '@/lib/demo';
import { siteConfig } from '@/lib/site';

/**
 * A mutable `useSearchParams`, replacing the fixed empty one in `tests/setup.ts`.
 *
 * `vi.hoisted` is required rather than a plain `const`: the mock factory runs
 * during the hoisted imports above, before a normal declaration has been
 * evaluated, and would read it in its temporal dead zone.
 */
const navigation = vi.hoisted(() => ({ params: new URLSearchParams() }));

vi.mock('next/navigation', () => ({
  usePathname: () => '/contact',
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  useSearchParams: () => navigation.params,
}));

const CONTACT_EMAIL = 'solveaihub@gmail.com';
const SITE_KEY = '1x00000000000000000000AA';

function renderForm(search: string) {
  navigation.params = new URLSearchParams(search);
  const view = render(<ContactForm siteKey={SITE_KEY} />);
  return { ...view, topic: screen.getByLabelText('Topic') as HTMLSelectElement };
}

/* ------------------------------------------------------------------------ */
/* 1. The consulting call to action                                          */
/* ------------------------------------------------------------------------ */

describe('the consulting call to action', () => {
  it('carries the agreed label and goes to the contact page with the topic', () => {
    render(<ServicesPage />);
    const cta = screen.getByRole('link', { name: CONSULTING_CTA_LABEL });

    expect(CONSULTING_CTA_LABEL).toBe('Start a consulting conversation');
    expect(cta.getAttribute('href')).toBe('/contact?service=consulting');
    expect(CONSULTING_CTA_HREF).toBe('/contact?service=consulting');
  });

  it('is an internal link rather than a compose window', () => {
    render(<ServicesPage />);
    const cta = screen.getByRole('link', { name: CONSULTING_CTA_LABEL });

    expect(cta.tagName).toBe('A');
    expect(cta.getAttribute('href')?.startsWith('mailto:')).toBe(false);
    // Not a new tab: this is navigation within the site the visitor is on.
    expect(cta.getAttribute('target')).toBeNull();
    // And not a button pretending to be a link, which would need a handler.
    expect(cta.getAttribute('onclick')).toBeNull();
  });

  it('is reachable and visible to a keyboard', () => {
    render(<ServicesPage />);
    const cta = screen.getByRole('link', { name: CONSULTING_CTA_LABEL });

    // An anchor with an href is in the tab order; one without is not.
    expect(cta.getAttribute('href')).toBeTruthy();
    expect(cta.getAttribute('tabindex')).toBeNull();
    cta.focus();
    expect(document.activeElement).toBe(cta);
    // jsdom resolves no stylesheet, so the focus ring is asserted as the class
    // that draws it. Without this a keyboard user cannot see where they are.
    expect(cta.className).toContain('focus-visible:outline-2');
  });

  it('appears once, and does not displace the site-wide call to action', () => {
    render(<ServicesPage />);
    expect(screen.getAllByRole('link', { name: CONSULTING_CTA_LABEL })).toHaveLength(1);
    // The header keeps "Start a Conversation". Two consulting buttons on one
    // page is noise; losing the general one is a regression.
    expect(screen.getAllByRole('link', { name: CONTACT_CTA_LABEL })).toHaveLength(1);
  });

  it.each([
    ['services', ServicesPage],
    ['contact', ContactPage],
  ] as const)('the old "Email about consulting" wording is gone from the %s page', (_name, Page) => {
    const { container } = render(<Page />);
    expect((container.textContent ?? '').replace(/\s+/g, ' ')).not.toMatch(
      /Email about consulting/i,
    );
  });

  it('keeps the direct address on the services page as well', () => {
    // The call to action replaced a mailto, so the fallback has to still be
    // there - a page whose only contact route is one more click is a page that
    // lost something.
    const { container } = render(<ServicesPage />);
    const mailtos = [...container.querySelectorAll('a')]
      .map((anchor) => anchor.getAttribute('href') ?? '')
      .filter((href) => href.startsWith('mailto:'));
    expect(mailtos.length).toBeGreaterThan(0);
    expect(mailtos.every((href) => href.startsWith(`mailto:${CONTACT_EMAIL}`))).toBe(true);
  });
});

/* ------------------------------------------------------------------------ */
/* 2. The service-query mapping                                              */
/* ------------------------------------------------------------------------ */

describe('the service-query mapping', () => {
  it('maps every published key to its topic', () => {
    expect(CONTACT_TOPICS.map((topic) => topic.service)).toEqual([
      'procurement-ai',
      'document-intelligence',
      'ai-prototyping',
      'consulting',
    ]);
    for (const topic of CONTACT_TOPICS) {
      expect(topicForService(topic.service), topic.service).toBe(topic.label);
    }
  });

  it('maps consulting to the named topic', () => {
    expect(topicForService(CONSULTING_SERVICE)).toBe('Collaboration or consulting');
    expect(CONSULTING_TOPIC).toBe('Collaboration or consulting');
  });

  it('tolerates casing and surrounding whitespace from a hand-typed URL', () => {
    expect(topicForService('  CONSULTING ')).toBe(CONSULTING_TOPIC);
  });

  /**
   * The value arrives from the address bar, so "unknown" has to be the same
   * outcome as "absent" for every shape of it - including the ones that would
   * be dangerous if the parameter were ever rendered instead of matched.
   */
  it.each([
    '',
    '   ',
    'unknown-service',
    'consulting-x',
    'CONSULTING; DROP TABLE',
    '<script>alert(1)</script>',
    '../../etc/passwd',
    'procurement_ai',
  ])('ignores %o and leaves the topic unselected', (value) => {
    expect(topicForService(value)).toBe(UNSELECTED_TOPIC);
  });

  it.each([null, undefined])('treats %o as no parameter at all', (value) => {
    expect(topicForService(value)).toBe(UNSELECTED_TOPIC);
  });

  it('offers an escape hatch that no link can select', () => {
    expect(TOPIC_OPTIONS).toContain(OTHER_TOPIC);
    expect(CONTACT_TOPICS.map((topic) => topic.label)).not.toContain(OTHER_TOPIC);
  });
});

/* ------------------------------------------------------------------------ */
/* 3. Preselection in the form itself                                        */
/* ------------------------------------------------------------------------ */

describe('the contact form topic', () => {
  it('preselects "Collaboration or consulting" for ?service=consulting', () => {
    const { topic } = renderForm(`${SERVICE_QUERY_PARAM}=${CONSULTING_SERVICE}`);
    expect(topic.value).toBe(CONSULTING_TOPIC);
    // Preselected in the control the visitor sees, not merely in state.
    expect(within(topic).getByRole('option', { name: CONSULTING_TOPIC }).hasAttribute('value')).toBe(
      true,
    );
    expect(topic.selectedOptions[0]?.textContent).toBe(CONSULTING_TOPIC);
  });

  it.each(CONTACT_TOPICS.map((topic) => [topic.service, topic.label] as const))(
    '?service=%s preselects %o',
    (service, label) => {
      const { topic } = renderForm(`${SERVICE_QUERY_PARAM}=${service}`);
      expect(topic.value).toBe(label);
    },
  );

  it.each(['unknown-service', '<script>alert(1)</script>', ''])(
    'leaves the field unselected for ?service=%o',
    (value) => {
      const { topic } = renderForm(`${SERVICE_QUERY_PARAM}=${encodeURIComponent(value)}`);
      expect(topic.value).toBe(UNSELECTED_TOPIC);
      // Nothing from the query became an option, either.
      expect([...topic.options].map((option) => option.value)).toEqual([
        UNSELECTED_TOPIC,
        ...TOPIC_OPTIONS,
      ]);
    },
  );

  it('is unselected with no parameter', () => {
    const { topic } = renderForm('');
    expect(topic.value).toBe(UNSELECTED_TOPIC);
  });

  it('never overwrites a choice the visitor made', () => {
    const { topic, rerender } = renderForm(`${SERVICE_QUERY_PARAM}=${CONSULTING_SERVICE}`);
    fireEvent.change(topic, { target: { value: OTHER_TOPIC } });
    expect(topic.value).toBe(OTHER_TOPIC);

    navigation.params = new URLSearchParams(`${SERVICE_QUERY_PARAM}=procurement-ai`);
    rerender(<ContactForm siteKey={SITE_KEY} />);

    expect(topic.value).toBe(OTHER_TOPIC);
  });

  it('is a labelled control with no axe violations', async () => {
    /*
     * `tests/accessibility.test.tsx` renders the contact page in its default
     * state, where the form is switched off - so the form itself is checked
     * nowhere else. Colour contrast and landmark rules are disabled for the
     * same reason they are there: jsdom resolves no stylesheet, and this is a
     * fragment rather than a page.
     */
    const { container, topic } = renderForm(`${SERVICE_QUERY_PARAM}=${CONSULTING_SERVICE}`);
    expect(topic.labels?.[0]?.textContent).toBe('Topic');

    const results = await axe.run(container, {
      rules: { 'color-contrast': { enabled: false }, region: { enabled: false } },
    });
    expect(
      results.violations.map((violation) => `${violation.id}: ${violation.help}`).join('\n'),
    ).toBe('');
  });

  it('does follow a new parameter while the visitor has chosen nothing', () => {
    // The other half of the pair. Without this, a component that simply ignores
    // the parameter after mount would pass the test above.
    const { topic, rerender } = renderForm(`${SERVICE_QUERY_PARAM}=${CONSULTING_SERVICE}`);
    expect(topic.value).toBe(CONSULTING_TOPIC);

    navigation.params = new URLSearchParams(`${SERVICE_QUERY_PARAM}=ai-prototyping`);
    rerender(<ContactForm siteKey={SITE_KEY} />);

    expect(topic.value).toBe('AI prototyping and evaluation');
  });
});

/* ------------------------------------------------------------------------ */
/* 4. The email card                                                         */
/* ------------------------------------------------------------------------ */

describe('the email card', () => {
  it('is one anchor to the configured address, with the address readable in it', () => {
    const { container } = render(<ServicesPage />);
    const card = screen.getByRole('link', { name: EMAIL_CARD_LABEL });

    expect(card.tagName).toBe('A');
    expect(card.getAttribute('href')?.startsWith(`mailto:${CONTACT_EMAIL}`)).toBe(true);
    expect(card.textContent).toContain(CONTACT_EMAIL);
    // The card, not a link inside it: the heading is part of the same anchor.
    expect(within(card).getByRole('heading').textContent).toBeTruthy();
    expect(container.querySelectorAll('a a')).toHaveLength(0);
  });

  it('is named for what it does, and to whom', () => {
    render(<ServicesPage />);
    expect(EMAIL_CARD_LABEL).toBe(`Email ${siteConfig.parentBrand} at ${siteConfig.contactEmail}`);
    expect(EMAIL_CARD_LABEL).toBe('Email Solve AI Hub at solveaihub@gmail.com');
    expect(screen.getByRole('link', { name: EMAIL_CARD_LABEL })).toBeTruthy();
  });

  it('reads the configured address rather than a second copy of it', () => {
    // If the address were hardcoded in the card, changing the configuration
    // would leave the label and the href disagreeing with the rest of the site.
    render(<ServicesPage />);
    const card = screen.getByRole('link', { name: EMAIL_CARD_LABEL });
    expect(card.getAttribute('href')).toContain(siteConfig.contactEmail);
    expect(EMAIL_CARD_LABEL).toContain(siteConfig.contactEmail);
  });

  it('looks and behaves interactive without a click handler', () => {
    render(<ServicesPage />);
    const card = screen.getByRole('link', { name: EMAIL_CARD_LABEL });

    expect(card.className).toContain('cursor-pointer');
    expect(card.className).toMatch(/hover:/);
    expect(card.className).toContain('focus-visible:outline-2');
    expect(card.getAttribute('onclick')).toBeNull();
    expect(card.getAttribute('tabindex')).toBeNull();

    card.focus();
    expect(document.activeElement).toBe(card);
  });

  it('does not open a mailto in a new tab', () => {
    render(<ServicesPage />);
    const card = screen.getByRole('link', { name: EMAIL_CARD_LABEL });
    // A new tab for a mailto leaves the visitor staring at a blank page.
    expect(card.getAttribute('target')).toBeNull();
  });

  it('makes each contact-page card a single, distinctly named email action', () => {
    const { container } = render(<ContactPage />);
    const cards = screen
      .getAllByRole('link')
      .filter((link) => link.getAttribute('aria-label')?.startsWith(EMAIL_CARD_LABEL));

    // Three reasons to write, plus the address in the page header.
    expect(cards.length).toBeGreaterThanOrEqual(4);
    for (const card of cards) {
      expect(card.getAttribute('href')?.startsWith(`mailto:${CONTACT_EMAIL}`)).toBe(true);
    }

    // Distinct names: several links called the same thing are one entry
    // repeated in a screen reader's link list.
    const names = cards.map((card) => card.getAttribute('aria-label'));
    expect(new Set(names).size).toBe(names.length);

    expect(container.querySelectorAll('a a')).toHaveLength(0);
  });

  it.each([
    ['services', ServicesPage],
    ['contact', ContactPage],
  ] as const)('renders no nested interactive element on the %s page', (_name, Page) => {
    const { container } = render(<Page />);
    for (const selector of [
      'a a',
      'a button',
      'button a',
      'button button',
      'a [role="button"]',
      'a input',
      'a select',
    ]) {
      expect(container.querySelectorAll(selector), selector).toHaveLength(0);
    }
  });
});

/* ------------------------------------------------------------------------ */
/* 5. The call to action is navigation, not an address                       */
/* ------------------------------------------------------------------------ */

/**
 * The label a caller passes, unchanged, and the address nowhere near it.
 *
 * The failure this section exists for is a call to action that renders
 * `solveaihub@gmail.com` where its label should be. Two things make that
 * possible and both are asserted below: a component that can *read* the
 * address, and a label that comes from a default rather than from the caller -
 * so every button on the site moves together and no page asserts what its own
 * button says.
 */

/** The label of a call to action, with the decorative arrow removed. */
function visibleLabel(link: Element): string {
  return (link.textContent ?? '').replace(/→/g, '').trim();
}

/**
 * The module specifiers a file actually imports.
 *
 * Comments are stripped first, for the reason `tests/contact-config.test.ts`
 * documents at length: `ContactCta.tsx` names `@/lib/site` in the comment
 * explaining why it must never import it, so a substring search over the raw
 * text reports the file as an offender and the assertion fails on prose.
 */
function importedModules(file: string): string[] {
  const source = readFileSync(file, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1');

  return [
    ...source.matchAll(/(?:^|\n)\s*(?:import|export)[\s\S]*?from\s*['"]([^'"]+)['"]/g),
    ...source.matchAll(/(?:^|\n)\s*import\s*['"]([^'"]+)['"]/g),
    ...source.matchAll(/\brequire\s*\(\s*['"]([^'"]+)['"]\s*\)/g),
    ...source.matchAll(/\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)/g),
  ]
    .map((match) => match[1])
    .filter((specifier): specifier is string => Boolean(specifier));
}

describe('the call to action is navigation, not an address', () => {
  it('renders exactly the children it is given', () => {
    render(
      <ContactCta href="/somewhere">
        A label nothing else on this site uses
      </ContactCta>,
    );
    const link = screen.getByRole('link', { name: 'A label nothing else on this site uses' });
    expect(visibleLabel(link)).toBe('A label nothing else on this site uses');
    expect(link.getAttribute('href')).toBe('/somewhere');
  });

  it('hardcodes no single label for every instance', () => {
    // Two instances, two labels, one component. A default that filled either of
    // these in would make this pass while saying nothing.
    const { container } = render(
      <>
        <ContactCta href="/one">First label</ContactCta>
        <ContactCta href="/two">Second label</ContactCta>
      </>,
    );
    const links = [...container.querySelectorAll('a')];
    expect(links.map(visibleLabel)).toEqual(['First label', 'Second label']);
    expect(links.map((link) => link.getAttribute('href'))).toEqual(['/one', '/two']);
  });

  it('cannot read the contact address at all', () => {
    // The import graph, not the text: the file documents this boundary in the
    // comment above the component, so a substring search matches the prose.
    const file = join(__dirname, '..', 'components/ContactCta.tsx');
    expect(readFileSync(file, 'utf8')).toContain('@/lib/site');
    expect(importedModules(file)).not.toContain('@/lib/site');
    expect(importedModules(file)).toEqual(['next/link']);
  });

  it('is an internal link, never a compose window and never a new tab', () => {
    render(<ContactCta href={CONTACT_CTA_HREF}>{CONTACT_CTA_LABEL}</ContactCta>);
    const link = screen.getByRole('link', { name: CONTACT_CTA_LABEL });
    expect(link.tagName).toBe('A');
    expect(link.getAttribute('href')).toBe('/contact');
    expect(link.getAttribute('href')?.startsWith('mailto:')).toBe(false);
    expect(link.getAttribute('target')).toBeNull();
    // Keyboard reachable, and visibly so.
    expect(link.getAttribute('tabindex')).toBeNull();
    link.focus();
    expect(document.activeElement).toBe(link);
    expect(link.className).toContain('focus-visible:outline-2');
  });

  it('renders the home page action as "Start a Conversation" to /contact', () => {
    render(<HomePage />);
    const cta = screen.getByRole('link', { name: CONTACT_CTA_LABEL });

    expect(visibleLabel(cta)).toBe('Start a Conversation');
    expect(cta.getAttribute('href')).toBe('/contact');
    expect(cta.getAttribute('target')).toBeNull();
    expect(cta.textContent).not.toContain(CONTACT_EMAIL);
  });

  it('renders the services action as "Start a consulting conversation" to the topic link', () => {
    render(<ServicesPage />);
    const cta = screen.getByRole('link', { name: CONSULTING_CTA_LABEL });

    expect(visibleLabel(cta)).toBe('Start a consulting conversation');
    expect(cta.getAttribute('href')).toBe('/contact?service=consulting');
    expect(cta.textContent).not.toContain(CONTACT_EMAIL);
  });

  it.each([
    ['home', HomePage],
    ['services', ServicesPage],
    ['contact', ContactPage],
  ] as const)('prints no address in any call to action on the %s page', (_name, Page) => {
    const { container } = render(<Page />);
    // Every internal link on the page: none of them may display the address.
    // The mailto: links are allowed to - that is what they are for - and they
    // are excluded by their own href rather than by name.
    const internal = [...container.querySelectorAll('a')].filter(
      (anchor) => !(anchor.getAttribute('href') ?? '').startsWith('mailto:'),
    );
    expect(internal.length).toBeGreaterThan(0);
    for (const anchor of internal) {
      expect(anchor.textContent ?? '', anchor.getAttribute('href') ?? '').not.toContain(
        CONTACT_EMAIL,
      );
    }
  });

  /**
   * The one that catches the bug this section was written for.
   *
   * The assertion above excludes `mailto:` links, so it cannot see the failure
   * that actually shipped: the contact page's page-header action was a
   * *button* - filled, beside Launch interactive demo, the same shape as every
   * other call to action - whose label was `solveaihub@gmail.com`. It read as
   * an address rather than an action, and on a machine with no mail client it
   * appeared to do nothing when pressed.
   *
   * So the rule is about the shape rather than the destination: anything
   * rendered as a button says what pressing it does. A direct-email action is
   * still allowed to *be* a mailto and still names the address in its
   * accessible name - see the email card section - it just does not use the
   * address as its label. Email cards are `rounded-xl` and are not buttons;
   * this matches the shared button styling only.
   */
  it.each([
    ['home', HomePage],
    ['services', ServicesPage],
    ['contact', ContactPage],
  ] as const)('labels every button-shaped action on the %s page with an action', (_name, Page) => {
    const { container } = render(<Page />);
    const buttons = [...container.querySelectorAll('a')].filter(
      (anchor) =>
        anchor.className.includes('rounded-lg') && anchor.className.includes('font-semibold'),
    );

    // Guards the guard: a selector that matches nothing passes silently.
    expect(buttons.length).toBeGreaterThan(0);
    for (const button of buttons) {
      const label = visibleLabel(button);
      expect(label, button.getAttribute('href') ?? '').not.toMatch(/@/);
      expect(label.length, button.getAttribute('href') ?? '').toBeGreaterThan(0);
    }
  });

  it('keeps the contact page header offering direct email, named for what it does', () => {
    render(<ContactPage />);
    const direct = screen.getByRole('link', { name: EMAIL_CARD_LABEL });

    // The action survives the relabelling: same address, same accessible name.
    expect(direct.getAttribute('href')?.startsWith(`mailto:${CONTACT_EMAIL}`)).toBe(true);
    expect(direct.getAttribute('aria-label')).toBe(EMAIL_CARD_LABEL);
    expect(EMAIL_CARD_LABEL).toContain(CONTACT_EMAIL);
    // And the address is still readable on the page, in the cards below.
    expect(screen.getAllByText(CONTACT_EMAIL).length).toBeGreaterThan(0);
  });

  it('keeps Launch interactive demo beside it, pointing at the configured demonstration', () => {
    const { container } = render(<HomePage />);
    const [demo] = screen.getAllByRole('link', { name: /launch interactive demo/i });

    expect(demo?.getAttribute('href')).toBe(buildDemoUrl());
    expect(demo?.getAttribute('href')).toBeTruthy();
    expect(demo?.getAttribute('target')).toBe('_blank');
    expect(demo?.getAttribute('rel')).toContain('noopener');

    // The two actions are siblings and visually distinct: one filled, one not.
    const cta = screen.getByRole('link', { name: CONTACT_CTA_LABEL });
    expect(demo?.parentElement).toBe(cta.parentElement);
    expect(demo?.className).not.toBe(cta.className);
    expect(container.querySelectorAll('a a')).toHaveLength(0);
  });
});

/* ------------------------------------------------------------------------ */
/* 6. The fallback that must survive all of this                             */
/* ------------------------------------------------------------------------ */

describe('the direct-email fallback', () => {
  it('is what the contact page still offers while the form is unavailable', () => {
    // No CONTACT_FORM_ENABLED in the test environment, which is the default
    // deployment: the page explains why there is no form and every route to
    // the inbox is a mailto.
    const { container } = render(<ContactPage />);
    expect(container.textContent).toMatch(/Why there is no contact form/i);

    const mailtos = [...container.querySelectorAll('a')]
      .map((anchor) => anchor.getAttribute('href') ?? '')
      .filter((href) => href.startsWith('mailto:'));
    expect(mailtos.length).toBeGreaterThanOrEqual(4);
    expect(mailtos.every((href) => href.startsWith(`mailto:${CONTACT_EMAIL}`))).toBe(true);
  });
});
