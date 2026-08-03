import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import HomePage from '@/app/page';
import ToolsPage from '@/app/tools/page';
import { COMPACT_GRID_COLUMNS } from '@/components/ModuleCard';
import { modules } from '@/content/modules';
import { methodOrigins } from '@/content/origins';
import { problemAreas } from '@/content/problems';
import { CONTACT_CTA_LABEL } from '@/lib/navigation';
import { UPLOAD_NOTICE, siteConfig } from '@/lib/site';

/** The home page's visible text, whitespace collapsed. */
function homeText(): string {
  const { container } = render(<HomePage />);
  return (container.textContent ?? '').replace(/\s+/g, ' ');
}

describe('the home page brand lockup', () => {
  it('leads with the product name as the one h1', () => {
    render(<HomePage />);
    const headings = screen.getAllByRole('heading', { level: 1 });
    expect(headings).toHaveLength(1);
    expect(headings[0]?.textContent).toBe('Procurement Intelligence Demo');
  });

  /**
   * The lockup has to survive being read as text, not just being painted.
   *
   * A `toContain('by Solve AI Hub')` assertion is not enough on its own and
   * this file shipped with only that for one build: JSX drops the whitespace
   * between two sibling elements, the hero rendered
   * `Procurement Intelligence Demoby Solve AI Hub`, and the assertion passed
   * because the `by` it matched was the one glued to `Demo`. Asserting the
   * *whole* public name is what catches it.
   */
  it('reads as the full public name, with every space in it', () => {
    const text = homeText();
    expect(text).toContain(siteConfig.fullName);
    expect(text).toContain(`by ${siteConfig.parentBrand}`);
    // The three ways the lockup collapses. The first two were real failures in
    // the header wordmark; the third was a real failure in this hero.
    expect(text).not.toMatch(/Solve\s*AIHub/);
    expect(text).not.toMatch(/SolveAI\s*Hub/);
    expect(text).not.toMatch(/Demoby/);
  });

  it('does not present the internal repository name as the product', () => {
    expect(homeText()).not.toMatch(/SAPDemo/);
  });

  it('claims no SAP endorsement, partnership or certification', () => {
    const text = homeText();
    for (const pattern of [
      /\bofficial SAP\b/i,
      /\bSAP[- ](certified|endorsed|approved|partner)\b/i,
      /\bin partnership with\b/i,
      /\ban SAP product\b/i,
    ]) {
      expect(text, String(pattern)).not.toMatch(pattern);
    }
  });
});

describe('the home page structure', () => {
  it('says what the project is, what it addresses, and how it works', () => {
    render(<HomePage />);
    for (const heading of [
      /the problems it addresses/i,
      /the ten tools/i,
      /how it works/i,
      /what an answer looks like/i,
      /four kinds of output/i,
    ]) {
      expect(screen.getByRole('heading', { name: heading }), String(heading)).toBeTruthy();
    }
  });

  it('names all six procurement problem areas', () => {
    render(<HomePage />);
    for (const area of problemAreas) {
      expect(screen.getByRole('heading', { name: area.title }), area.title).toBeTruthy();
    }
  });

  it('links to the pages the long explanations moved to', () => {
    render(<HomePage />);
    const hrefs = screen.getAllByRole('link').map((link) => link.getAttribute('href'));
    expect(hrefs).toContain('/how-it-works');
    expect(hrefs).toContain('/architecture');
    expect(hrefs).toContain('/tools');
  });

  /**
   * The home page used to carry the layered-architecture argument and a full
   * description of all five output origins, both of which exist in more detail
   * on their own pages. This asserts the *page-specific* copy is gone rather
   * than banning the words: "architecture" is still a link label here, and
   * should be.
   */
  it('no longer repeats the architecture and data-flow explanations', () => {
    const text = homeText();
    for (const pattern of [
      /may call downward and never upward/i,
      /services layer/i,
      /Cloudflare Tunnel/i,
      /FastAPI/i,
      /PostgreSQL/i,
      /the decision this whole project is organised around/i,
    ]) {
      expect(text, String(pattern)).not.toMatch(pattern);
    }
  });
});

describe('the ten tools on the home page', () => {
  it('shows every one of them, exactly once', () => {
    render(<HomePage />);
    for (const module of modules) {
      const links = screen.getAllByRole('link', { name: module.name });
      expect(links, module.name).toHaveLength(1);
      expect(links[0]?.getAttribute('href')).toBe(`/tools/${module.slug}`);
    }
  });

  it('shows exactly ten tool links and no eleventh', () => {
    const { container } = render(<HomePage />);
    const toolLinks = [...container.querySelectorAll('a')]
      .map((anchor) => anchor.getAttribute('href') ?? '')
      .filter((href) => href.startsWith('/tools/'));
    expect(toolLinks).toHaveLength(10);
    expect(new Set(toolLinks).size).toBe(10);
  });

  /**
   * jsdom measures nothing, so this asserts the mechanism: the column ramp the
   * grid is actually rendered with, and the absence of the tier that made the
   * cards unreadable.
   *
   * Five columns is banned at *every* breakpoint rather than only at `xl`, and
   * that is the point of the assertion. `Container` is `max-w-6xl`, so the
   * content box is 1104px at 1280px, at 1920px and at 2560px alike - moving the
   * five-column tier to `2xl` would look like a fix and would produce exactly
   * the same 208px cards, because the container does not grow with the
   * viewport. There is no width at which five columns here is comfortable.
   */
  it('lays the cards out 1 / 2 / 3 / 4 and never returns to five columns', () => {
    const { container } = render(<HomePage />);
    const grid = [...container.querySelectorAll('ul.grid')].find((list) =>
      list.querySelector('a[href^="/tools/"]'),
    );
    expect(grid, 'the compact tool grid').toBeTruthy();

    expect(grid?.className).toBe(`grid gap-4 ${COMPACT_GRID_COLUMNS}`);
    // One column is the unprefixed default, so it is asserted as the absence of
    // a base `grid-cols-*` rather than as a class.
    expect(COMPACT_GRID_COLUMNS).not.toMatch(/(^|\s)grid-cols-/);
    expect(grid?.className).toContain('sm:grid-cols-2');
    expect(grid?.className).toContain('lg:grid-cols-3');
    expect(grid?.className).toContain('xl:grid-cols-4');
    expect(grid?.className).not.toMatch(/grid-cols-5/);
  });

  /**
   * The compact grid was the confirmed problem; the tools overview was not. Its
   * cards carry a paragraph and sit three to a row at 357px, so this asserts the
   * change stayed where it belonged instead of spreading.
   */
  it('leaves the /tools overview grid alone', () => {
    const { container } = render(<ToolsPage />);
    const grid = container.querySelector('ul.grid');
    expect(grid?.className).toContain('sm:grid-cols-2');
    expect(grid?.className).toContain('lg:grid-cols-3');
    expect(grid?.className).not.toMatch(/xl:grid-cols-/);
  });

  it('says what goes in, what comes out and what each is for', () => {
    render(<HomePage />);
    for (const module of modules) {
      expect(screen.getByText(module.overview.input), module.id).toBeTruthy();
      expect(screen.getByText(module.overview.output), module.id).toBeTruthy();
      expect(screen.getByText(module.overview.purpose), module.id).toBeTruthy();
    }
  });

  /**
   * Module-specific demonstration routing is PR 4. Until then the only
   * demonstration destination on this page is the configured one, and a tool
   * card is a link to the tool's *page*.
   */
  it('routes no tool card at the demonstration directly', () => {
    const { container } = render(<HomePage />);
    const demoLinks = [...container.querySelectorAll('a')].filter(
      (anchor) => anchor.getAttribute('href') === siteConfig.demoUrl,
    );
    expect(demoLinks.length).toBeGreaterThan(0);
    for (const link of demoLinks) {
      expect(link.textContent).toMatch(/launch interactive demo/i);
      expect(link.getAttribute('href')).not.toMatch(/\?module=|\/tools\//);
    }
  });
});

describe('the calls to action', () => {
  it('offers Launch interactive demo, pointing at the configured demonstration', () => {
    render(<HomePage />);
    const [demo] = screen.getAllByRole('link', { name: /launch interactive demo/i });
    expect(demo?.getAttribute('href')).toBe(siteConfig.demoUrl);
    expect(demo?.getAttribute('target')).toBe('_blank');
    expect(demo?.getAttribute('rel')).toContain('noopener');
  });

  it('keeps Start a Conversation, once, going to the contact page', () => {
    render(<HomePage />);
    const links = screen.getAllByRole('link', { name: new RegExp(CONTACT_CTA_LABEL) });
    expect(links).toHaveLength(1);
    expect(links[0]?.getAttribute('href')).toBe('/contact');
  });
});

describe('the method distinction', () => {
  it('names the four kinds of output and what each covers', () => {
    render(<HomePage />);
    for (const entry of methodOrigins) {
      expect(screen.getAllByText(entry.label).length, entry.origin).toBeGreaterThan(0);
      expect(screen.getByText(entry.summary), entry.origin).toBeTruthy();
      for (const example of entry.examples) {
        expect(screen.getByText(example), `${entry.origin}: ${example}`).toBeTruthy();
      }
    }
  });

  it('distinguishes deterministic, statistical, AI-written and mock output', () => {
    const text = homeText();
    expect(text).toMatch(/Rule-based/);
    expect(text).toMatch(/Forecast/);
    expect(text).toMatch(/AI-generated/);
    expect(text).toMatch(/Mock AI/);
    expect(text).toMatch(/business rules/i);
    expect(text).toMatch(/statistical projection/i);
    expect(text).toMatch(/no external call/i);
  });

  it('does not claim AI produces every result, or decides anything', () => {
    const text = homeText();
    expect(text).toMatch(/No AI output ever overwrites a computed value/i);
    expect(text).toMatch(/nothing here decides a procurement approval/i);
    for (const pattern of [
      /\bAI-powered platform\b/i,
      /\bevery (result|answer) is (generated|written) by AI\b/i,
      /\bAI (decides|approves|signs off)\b/i,
    ]) {
      expect(text, String(pattern)).not.toMatch(pattern);
    }
  });
});

describe('the illustrative examples', () => {
  it('says they are illustrations rather than screenshots', () => {
    const text = homeText();
    expect(text).toMatch(/Illustrative examples/i);
    expect(text).toMatch(/They are not screenshots/i);
  });

  it('carries a separate label on the computed half and the written half', () => {
    render(<HomePage />);
    const figures = screen.getAllByRole('figure');
    expect(figures.length).toBeGreaterThanOrEqual(2);
    for (const figure of figures) {
      expect(within(figure).getAllByText(/Mock AI/).length).toBeGreaterThan(0);
    }
  });

  it('claims no customer, no outcome and no production deployment', () => {
    const text = homeText();
    for (const pattern of [
      /\bour (customers?|clients?)\b/i,
      /\bcase study\b/i,
      /\btestimonial\b/i,
      /\bsaved (us|them|€|\$)/i,
      /\bin production at\b/i,
      /\btrusted by\b/i,
    ]) {
      expect(text, String(pattern)).not.toMatch(pattern);
    }
  });
});

describe('the one disclaimer on the home page', () => {
  it('states the upload position in the agreed wording', () => {
    expect(homeText()).toContain(UPLOAD_NOTICE);
  });

  it('warns against confidential and personal information, and requires human review', () => {
    const text = homeText();
    expect(text).toMatch(/confidential/i);
    expect(text).toMatch(/personal information/i);
    expect(text).toMatch(/review by a qualified person/i);
    expect(text).toMatch(/demonstration/i);
  });

  it('is one callout, not several', () => {
    const { container } = render(<HomePage />);
    // The warning callouts on this page, by the tone class they are drawn with.
    const warnings = [...container.querySelectorAll('div')].filter((node) =>
      node.className.includes('border-amber-300'),
    );
    expect(warnings).toHaveLength(1);
  });

  /**
   * The assertion is about the *disclaimer sentences*, not about the words in
   * them. A first version counted the phrase "bundled fictional data" and
   * failed on the How-it-works step describing what the input is, which is
   * ordinary copy rather than a repeated warning - and a test that fires on
   * prose gets deleted rather than fixed.
   */
  it('states each disclaimer sentence once, not twice', () => {
    const text = homeText();
    expect(text.split(UPLOAD_NOTICE)).toHaveLength(2);
    expect(text.match(/review by a qualified person/gi) ?? []).toHaveLength(1);
    expect(text.match(/do not enter confidential/gi) ?? []).toHaveLength(1);
  });
});
