import { render } from '@testing-library/react';
import axe from 'axe-core';
import { describe, expect, it } from 'vitest';
import AboutPage from '@/app/about/page';
import ArchitecturePage from '@/app/architecture/page';
import ContactPage from '@/app/contact/page';
import DemoDisclaimerPage from '@/app/demo-disclaimer/page';
import HomePage from '@/app/page';
import HowItWorksPage from '@/app/how-it-works/page';
import PlatformPage from '@/app/platform/page';
import PrivacyPage from '@/app/privacy/page';
import ServicesPage from '@/app/services/page';
import TermsPage from '@/app/terms/page';
import ToolsPage from '@/app/tools/page';
import ModulePage from '@/app/tools/[slug]/page';
import { Nav } from '@/components/Nav';
import { Footer } from '@/components/Footer';
import { modules } from '@/content/modules';
import { DESKTOP_ONLY, MOBILE_ONLY, getNavItems } from '@/lib/navigation';
import { siteConfig } from '@/lib/site';

const navItems = getNavItems(siteConfig.servicesPageEnabled);

/**
 * axe-core run against the real rendered markup.
 *
 * Colour-contrast is disabled here and only here: jsdom computes no layout and
 * resolves no stylesheet, so the rule cannot see the colours the browser will
 * actually paint. Leaving it on would produce a result that means nothing in
 * either direction. Contrast is checked in a browser instead; the structural
 * rules below are the ones a DOM test can genuinely verify.
 */
async function analyse(container: HTMLElement) {
  return axe.run(container, {
    rules: {
      'color-contrast': { enabled: false },
      region: { enabled: false },
    },
  });
}

function describeViolations(results: axe.AxeResults): string {
  return results.violations
    .map((violation) => `${violation.id}: ${violation.help} (${violation.nodes.length} node(s))`)
    .join('\n');
}

const pages = [
  ['home', HomePage],
  ['platform', PlatformPage],
  ['tools', ToolsPage],
  ['how it works', HowItWorksPage],
  ['architecture', ArchitecturePage],
  ['services', ServicesPage],
  ['about', AboutPage],
  ['contact', ContactPage],
  ['demo disclaimer', DemoDisclaimerPage],
  ['privacy', PrivacyPage],
  ['terms', TermsPage],
] as const;

describe('accessibility', () => {
  it.each(pages)('%s has no axe violations', async (_name, Page) => {
    const { container } = render(<Page />);
    const results = await analyse(container);
    expect(describeViolations(results)).toBe('');
  });

  it.each(modules.map((module) => [module.slug] as const))(
    '/tools/%s has no axe violations',
    async (slug) => {
      const { container } = render(await ModulePage({ params: Promise.resolve({ slug }) }));
      const results = await analyse(container);
      expect(describeViolations(results)).toBe('');
    },
  );

  it('the navigation and footer have no axe violations', async () => {
    const { container } = render(
      <>
        <Nav items={navItems} />
        <Footer />
      </>,
    );
    const results = await analyse(container);
    expect(describeViolations(results)).toBe('');
  });
});

describe('responsive layout primitives', () => {
  /**
   * jsdom cannot measure a viewport, so this checks the mechanism rather than
   * the outcome: the responsive classes are present and no fixed pixel width
   * is set on a container. A layout that is responsive in the markup can still
   * be checked in a browser; one that hardcodes a width cannot be.
   */
  it.each(pages)('%s uses fluid containers and no fixed pixel width', (_name, Page) => {
    const { container } = render(<Page />);
    const html = container.innerHTML;
    expect(html).toMatch(/max-w-\w+/);
    expect(html).not.toMatch(/style="[^"]*width:\s*\d{3,}px/);
  });

  it('the module grid declares breakpoints for small, medium and large screens', () => {
    const { container } = render(<ToolsPage />);
    const grid = container.querySelector('ul.grid');
    expect(grid?.className).toContain('sm:grid-cols-2');
    expect(grid?.className).toContain('lg:grid-cols-3');
  });

  /**
   * Reads the shared constant rather than naming a breakpoint, because the
   * breakpoint moved once already: eight links, a demo button and the contact
   * call to action do not fit a 1024px window, so the horizontal navigation
   * now appears at `xl`. A test hardcoding `lg:hidden` would have to be edited
   * every time that judgement changes, which is how it ends up asserting a
   * breakpoint the component stopped using.
   */
  it('the primary navigation collapses below the desktop breakpoint', () => {
    const { container } = render(<Nav items={navItems} />);
    // The whole banner, not the navigation's parent: the links and the toggle
    // are in different regions of the row now, so the toggle is a sibling of
    // the region rather than of the navigation.
    const header = container.querySelector('header');
    expect(header?.innerHTML).toContain(MOBILE_ONLY);
    expect(container.querySelector('nav[aria-label="Primary"]')?.className).toBe(DESKTOP_ONLY);
  });
});
