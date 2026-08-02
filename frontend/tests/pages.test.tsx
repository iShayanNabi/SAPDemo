import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Footer } from '@/components/Footer';
import { Nav } from '@/components/Nav';
import { DemoCta } from '@/components/DemoCta';
import { ModuleGrid } from '@/components/ModuleCard';
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
import { modules } from '@/content/modules';
import { getNavItems } from '@/lib/navigation';
import { siteConfig } from '@/lib/site';

/**
 * The navigation the deployed site renders. `Nav` takes its items as a prop,
 * so a test that invented its own list would assert nothing about what the
 * layout actually passes down.
 */
const navItems = getNavItems(siteConfig.servicesPageEnabled);

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

describe('every content page renders', () => {
  it.each(pages)('%s renders exactly one h1', (_name, Page) => {
    render(<Page />);
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
  });
});

describe('the ten module detail pages', () => {
  it.each(modules.map((module) => [module.slug, module] as const))(
    '/tools/%s renders its own content',
    async (slug, module) => {
      const ui = await ModulePage({ params: Promise.resolve({ slug }) });
      render(ui);

      expect(screen.getByRole('heading', { level: 1 }).textContent).toContain(module.name);
      expect(screen.getByText(module.problem)).toBeTruthy();
      expect(screen.getByText(module.demoInput)).toBeTruthy();

      // The two claims that must never be merged into one paragraph.
      expect(screen.getByRole('heading', { name: /what the code calculates/i })).toBeTruthy();
      expect(screen.getByRole('heading', { name: /what ai writes/i })).toBeTruthy();

      for (const claim of module.computed) {
        expect(screen.getByText(claim)).toBeTruthy();
      }
      for (const step of module.steps) {
        expect(screen.getByText(step)).toBeTruthy();
      }
    },
  );

  it('generates a static param for every module and nothing else', async () => {
    const { generateStaticParams } = await import('@/app/tools/[slug]/page');
    expect(generateStaticParams().map((entry) => entry.slug)).toEqual(
      modules.map((module) => module.slug),
    );
  });

  it('every module detail page offers a demo link', async () => {
    for (const module of modules) {
      const { unmount } = render(await ModulePage({ params: Promise.resolve({ slug: module.slug }) }));
      const demoLinks = screen
        .getAllByRole('link')
        .filter((link) => link.getAttribute('href') === siteConfig.demoUrl);
      expect(demoLinks.length, module.slug).toBeGreaterThan(0);
      unmount();
    }
  });
});

describe('navigation', () => {
  it('renders every primary link once, in a nav landmark', () => {
    render(<Nav items={navItems} />);
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    for (const link of navItems) {
      expect(within(nav).getByRole('link', { name: link.label })).toBeTruthy();
    }
  });

  it('keeps the six public destinations visible', () => {
    render(<Nav items={navItems} />);
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    for (const [label, href] of [
      ['Home', '/'],
      ['Tools', '/tools'],
      ['Services', '/services'],
      ['How it works', '/how-it-works'],
      ['Architecture', '/architecture'],
      ['Contact', '/contact'],
    ] as const) {
      const link = within(nav).getByRole('link', { name: label });
      expect(link.getAttribute('href'), label).toBe(href);
    }
  });

  it('marks the current page with aria-current', () => {
    // The setup file stubs usePathname to '/', so Home - and only Home - is
    // the current page.
    render(<Nav items={navItems} />);
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    const current = within(nav).getAllByRole('link', { current: 'page' });
    expect(current.map((link) => link.getAttribute('href'))).toEqual(['/']);
  });

  it('exposes the mobile menu button state to assistive technology', () => {
    render(<Nav items={navItems} />);
    const toggle = screen.getByRole('button', { name: /open menu/i });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(toggle.getAttribute('aria-controls')).toBe('mobile-navigation');
  });

  it('links the tools overview to all ten module pages', () => {
    render(<ModuleGrid modules={modules} />);
    for (const module of modules) {
      const link = screen.getByRole('link', { name: module.name });
      expect(link.getAttribute('href')).toBe(`/tools/${module.slug}`);
    }
  });
});

describe('the demo call to action', () => {
  it('points at the configured demo URL and opens safely in a new tab', () => {
    render(<DemoCta />);
    const link = screen.getByRole('link');
    expect(link.getAttribute('href')).toBe(siteConfig.demoUrl);
    expect(link.getAttribute('target')).toBe('_blank');
    // Without noopener the opened page can reach back through window.opener.
    expect(link.getAttribute('rel')).toContain('noopener');
    expect(link.getAttribute('rel')).toContain('noreferrer');
  });

  it('warns a screen reader that the link opens a new tab', () => {
    render(<DemoCta />);
    expect(screen.getByText(/opens in a new tab/i)).toBeTruthy();
  });

  it('appears on the home page', () => {
    render(<HomePage />);
    const demoLinks = screen
      .getAllByRole('link')
      .filter((link) => link.getAttribute('href') === siteConfig.demoUrl);
    expect(demoLinks.length).toBeGreaterThan(0);
  });
});

describe('the footer', () => {
  it('carries project, contact, privacy and disclaimer links', () => {
    render(<Footer />);
    expect(screen.getByRole('link', { name: /platform overview/i })).toBeTruthy();
    expect(screen.getByRole('link', { name: siteConfig.contactEmail })).toBeTruthy();
    expect(screen.getByRole('link', { name: /consulting services/i })).toBeTruthy();
    expect(screen.getByRole('link', { name: /^privacy$/i })).toBeTruthy();
    expect(screen.getByRole('link', { name: /terms and disclaimer/i })).toBeTruthy();
    expect(screen.getByRole('link', { name: /demonstration disclaimer/i })).toBeTruthy();
  });

  it('states the trademark and demonstration position on every page', () => {
    render(<Footer />);
    expect(screen.getByText(/not endorsed by, certified by/i)).toBeTruthy();
    expect(screen.getByText(/fictional sample data generated for demonstration/i)).toBeTruthy();
  });
});

describe('the demonstration disclaimer', () => {
  it('names each category of data a visitor must not enter', () => {
    render(<DemoDisclaimerPage />);
    for (const phrase of [
      /confidential or commercially sensitive/i,
      /personal information/i,
      /real SAP data/i,
      /real supplier, purchase order, invoice or contract data/i,
      /proprietary company data/i,
    ]) {
      expect(screen.getByText(phrase)).toBeTruthy();
    }
  });

  it('says uploads are refused server-side rather than merely hidden', () => {
    render(<DemoDisclaimerPage />);
    expect(screen.getByText(/refused by the API whether or not the button is on the page/i)).toBeTruthy();
  });
});

describe('no secrets reach the rendered page', () => {
  it.each(pages)('%s renders no credential-shaped string', (_name, Page) => {
    const { container } = render(<Page />);
    const html = container.innerHTML;
    expect(html).not.toMatch(/sk-ant-[A-Za-z0-9-]{10,}/);
    expect(html).not.toMatch(/\bAKIA[0-9A-Z]{16}\b/);
    // A connection string with credentials in it, in any form.
    expect(html).not.toMatch(/postgres(ql)?:\/\/[^\s"'<]*:[^\s"'<]*@/);
    expect(html).not.toMatch(/(?:password|secret|api[_-]?key|token)\s*[=:]\s*["']?\S{8,}/i);
    // A Cloudflare tunnel token is a long base64 blob; nothing on this site
    // should ever carry one.
    expect(html).not.toMatch(/eyJ[A-Za-z0-9_-]{40,}/);
  });

  /**
   * Internal service hostnames are a separate question from secrets.
   *
   * `api:8000` is a Docker service name on a private network - knowing it buys
   * an attacker nothing, and the architecture page's whole purpose is to
   * explain that topology. What must never happen is one appearing where it was
   * not deliberately written: in an error message, or in copy about something
   * else. So this asserts exactly that - the architecture page may name them,
   * and no other page may.
   */
  it.each(pages.filter(([name]) => name !== 'architecture'))(
    '%s names no internal service hostname',
    (_name, Page) => {
      const { container } = render(<Page />);
      expect(container.innerHTML).not.toMatch(/\b(api|database|streamlit|website):\d{2,5}\b/);
    },
  );

  it('the architecture page names them deliberately, as documentation', () => {
    const { container } = render(<ArchitecturePage />);
    expect(container.innerHTML).toMatch(/http:\/\/api:8000/);
  });
});
