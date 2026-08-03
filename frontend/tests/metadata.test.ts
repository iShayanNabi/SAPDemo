import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import robots from '@/app/robots';
import sitemap from '@/app/sitemap';
import { modules } from '@/content/modules';
import { PAGE_PATHS, pageList, pages, publishedPages } from '@/content/pages';
import { problemAreas } from '@/content/problems';
import { examplePanels } from '@/content/examples';
import { methodOrigins, origins } from '@/content/origins';
import {
  NOT_FOUND_METADATA,
  SOCIAL_IMAGE,
  buildMetadata,
  canonicalOrigin,
  canonicalPath,
  canonicalUrl,
  normalizePublicOrigin,
  pageMetadata,
  socialImageUrl,
  toolMetadata,
} from '@/lib/metadata';
import { PUBLIC_ORIGIN, TRADEMARK_NOTICE, siteConfig } from '@/lib/site';

/**
 * A path inside the website package.
 *
 * Resolved from the Vitest root - `vitest.config.mts` lives in this directory,
 * so the working directory is it - rather than from `import.meta.url`, which
 * the JSX transform rewrites and which resolved to `tests/undefined` here.
 * `existsSync` on a wrong path returns `false` rather than failing, so a broken
 * base would quietly turn "this asset exists" into "this assertion is a lie".
 */
function repoFile(relative: string): string {
  return resolve(process.cwd(), relative);
}

/**
 * Every public page's resolved metadata: the eleven marketing pages and the ten
 * tool pages, in one list, because most of what is worth asserting here is a
 * property of the *set* rather than of any single page - uniqueness, a shared
 * title pattern, one origin.
 */
const allMetadata = [
  ...PAGE_PATHS.map((path) => [path, pageMetadata(path)] as const),
  ...modules.map((module) => [`/tools/${module.slug}`, toolMetadata(module)] as const),
];

/** The `<title>` a page ends up with, after `app/layout.tsx` applies its template. */
function resolvedTitle(title: unknown): string {
  if (typeof title === 'string') {
    return `${title} — ${siteConfig.name}`;
  }
  if (title && typeof title === 'object' && 'absolute' in title) {
    return String((title as { absolute: string }).absolute);
  }
  throw new Error(`Unexpected title shape: ${JSON.stringify(title)}`);
}

/* ------------------------------------------------------------------------ */
/* The canonical origin                                                      */
/* ------------------------------------------------------------------------ */

describe('the canonical origin', () => {
  it('is the public production origin', () => {
    expect(PUBLIC_ORIGIN).toBe('https://solveaihub.com');
    expect(canonicalOrigin).toBe('https://solveaihub.com');
  });

  it('canonicalises www to the bare domain', () => {
    // Both hostnames serve the same pages. Two origins serving one page is the
    // definition of duplicate content, so only one of them may be named.
    expect(normalizePublicOrigin('https://www.solveaihub.com')).toBe('https://solveaihub.com');
    expect(normalizePublicOrigin('https://WWW.SolveAIHub.com/')).toBe('https://solveaihub.com');
  });

  it.each([
    ['a loopback address', 'http://127.0.0.1:3000'],
    ['localhost', 'http://localhost:3000'],
    ['https localhost', 'https://localhost:3000'],
    ['a Docker service name', 'http://website:3000'],
    ['an https Docker service name', 'https://website'],
    ['the protected demonstration hostname', 'https://demo.solveaihub.com'],
    ['a staging hostname', 'https://staging.solveaihub.com'],
    ['an .internal hostname', 'https://website.internal'],
    ['a .local hostname', 'https://laptop.local'],
    ['plain http', 'http://solveaihub.com'],
    ['a bare IP', 'https://192.168.1.10'],
    ['nonsense', 'not-a-url'],
    ['a blank value', ''],
  ])('refuses %s', (_label, value) => {
    expect(normalizePublicOrigin(value)).toBeNull();
  });

  /**
   * `docker-compose.debug.yml` really does set this, so the fallback is not a
   * hypothetical. A debug build must not be able to publish a loopback
   * canonical - a page telling a crawler it lives at 127.0.0.1 asks to be
   * de-indexed, and nothing about the page looks wrong.
   */
  it.each([
    ['http://127.0.0.1:3000', 'the debug compose default'],
    ['https://demo.solveaihub.com', 'the protected demonstration'],
    ['', 'a blank Docker variable'],
    ['   ', 'a hand-edited blank'],
  ])('falls back to the public origin when configured with %s', async (value) => {
    vi.resetModules();
    vi.stubEnv('NEXT_PUBLIC_SITE_URL', value);
    const metadata = await import('@/lib/metadata');
    expect(metadata.canonicalOrigin).toBe('https://solveaihub.com');
    expect(metadata.canonicalUrl('/about')).toBe('https://solveaihub.com/about');
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it('honours a different real public origin', async () => {
    vi.resetModules();
    vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'https://www.example.org/');
    const metadata = await import('@/lib/metadata');
    expect(metadata.canonicalOrigin).toBe('https://example.org');
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });
});

describe('canonical paths', () => {
  it.each([
    ['/', '/'],
    ['', '/'],
    ['/about', '/about'],
    ['/about/', '/about'],
    ['about', '/about'],
    ['//tools//spend', '/tools/spend'],
  ])('normalises %o to %o', (input, expected) => {
    expect(canonicalPath(input)).toBe(expected);
  });

  /**
   * The one that matters for this site specifically. The Services page's call
   * to action is `/contact?service=consulting`, which preselects a topic on a
   * page that is otherwise identical to `/contact`. A canonical carrying the
   * parameter would split one page into two in an index.
   */
  it('drops query strings and fragments rather than creating a second page', () => {
    expect(canonicalUrl('/contact?service=consulting')).toBe('https://solveaihub.com/contact');
    expect(canonicalUrl('/contact?service=consulting#form')).toBe(
      'https://solveaihub.com/contact',
    );
    expect(canonicalUrl('/contact')).toBe(canonicalUrl('/contact?anything=at-all'));
  });

  it('gives the home page the origin', () => {
    expect(canonicalUrl('/')).toBe('https://solveaihub.com/');
  });
});

/* ------------------------------------------------------------------------ */
/* Titles, descriptions and canonicals across every page                     */
/* ------------------------------------------------------------------------ */

describe('every public page', () => {
  it('has a title, and no two share one', () => {
    const titles = allMetadata.map(([, meta]) => resolvedTitle(meta.title));
    for (const title of titles) {
      expect(title.length).toBeGreaterThan(10);
    }
    expect(new Set(titles).size).toBe(titles.length);
  });

  it('has a description, and no two share one', () => {
    const descriptions = allMetadata.map(([path, meta]) => {
      expect(meta.description, path).toBeTruthy();
      return meta.description as string;
    });
    for (const description of descriptions) {
      // Long enough to say something, short enough not to be cut off in a
      // result. A description nobody wrote is the failure this catches.
      expect(description.length).toBeGreaterThan(60);
      expect(description.length).toBeLessThanOrEqual(320);
    }
    expect(new Set(descriptions).size).toBe(descriptions.length);
  });

  /**
   * The product name is written out in two places that must agree: the layout's
   * default title, and the home page's absolute title in the page registry.
   * They are separate values because they are read at different points, and
   * nothing else would notice them drifting apart.
   */
  it('names the product identically in the layout default and the home page', () => {
    expect(pages['/'].absoluteTitle).toBe(siteConfig.title);
    expect(siteConfig.title).toBe(siteConfig.fullName);
  });

  it('follows one title pattern: the page, then the product', () => {
    for (const [path, meta] of allMetadata) {
      const title = resolvedTitle(meta.title);
      if (path === '/') {
        // The one page whose title is the product itself. "Home — Procurement
        // Intelligence Demo" is what a template produces there, and it is worse
        // than the name.
        expect(title).toBe('Procurement Intelligence Demo by Solve AI Hub');
      } else {
        expect(title, path).toMatch(/ — Procurement Intelligence Demo$/);
      }
    }
  });

  it('carries its own canonical, on the public origin', () => {
    for (const [path, meta] of allMetadata) {
      expect(meta.alternates?.canonical, path).toBe(canonicalUrl(path));
      expect(String(meta.alternates?.canonical), path).toMatch(/^https:\/\/solveaihub\.com/);
    }
  });

  it('has one canonical each, and no two pages claim the same address', () => {
    const canonicals = allMetadata.map(([, meta]) => String(meta.alternates?.canonical));
    expect(new Set(canonicals).size).toBe(canonicals.length);
  });

  it.each([
    ['localhost', /localhost/],
    ['a loopback address', /127\.0\.0\.1/],
    ['a Docker service hostname', /\/\/(api|website|database|streamlit)(:|\/|$)/],
    ['the protected demonstration hostname', /demo\.solveaihub\.com/],
    ['the www hostname', /www\.solveaihub\.com/],
    ['a query string', /\?/],
  ])('names no %s in any canonical or Open Graph URL', (_label, pattern) => {
    for (const [path, meta] of allMetadata) {
      expect(String(meta.alternates?.canonical), path).not.toMatch(pattern);
      expect(String(meta.openGraph?.url), path).not.toMatch(pattern);
    }
  });

  it('agrees between its canonical and its Open Graph URL', () => {
    for (const [path, meta] of allMetadata) {
      expect(String(meta.openGraph?.url), path).toBe(String(meta.alternates?.canonical));
    }
  });

  it('is indexable', () => {
    for (const [path, meta] of allMetadata) {
      expect(meta.robots, path).toMatchObject({ index: true, follow: true });
    }
  });
});

/* ------------------------------------------------------------------------ */
/* Open Graph and the social card                                            */
/* ------------------------------------------------------------------------ */

describe('Open Graph and Twitter metadata', () => {
  it('gives every page a title, a description, a URL, a site name and an image', () => {
    for (const [path, meta] of allMetadata) {
      const og = meta.openGraph;
      expect(og, path).toBeTruthy();
      expect(og?.title, path).toBeTruthy();
      expect(og?.description, path).toBeTruthy();
      expect(og?.url, path).toBeTruthy();
      expect((og as { siteName?: string })?.siteName, path).toBe('Solve AI Hub');
      expect((og as { type?: string })?.type, path).toBe('website');
      const images = (og as { images?: unknown[] })?.images ?? [];
      expect(images.length, path).toBe(1);
    }
  });

  /**
   * The failure this exists for was invisible in every unit test and visible
   * in one line of built HTML: Next applies the `opengraph-image` file
   * convention *only* to pages that do not declare an `openGraph` object. Every
   * page here declares one, so the first version shipped ten tool pages and ten
   * marketing pages with no preview image at all - shareable, and blank.
   */
  it('declares the image explicitly rather than relying on the file convention', () => {
    for (const [path, meta] of allMetadata) {
      const [image] = (meta.openGraph as { images?: Array<Record<string, unknown>> })?.images ?? [];
      expect(image, path).toBeTruthy();
      expect(image?.url, path).toBe(socialImageUrl());
      expect(image?.width, path).toBe(1200);
      expect(image?.height, path).toBe(630);
      expect(image?.type, path).toBe('image/png');
      expect(String(image?.alt), path).toMatch(/Procurement Intelligence Demo by Solve AI Hub/);
    }
  });

  it('uses the wide card, with its own title, description and image', () => {
    for (const [path, meta] of allMetadata) {
      const twitter = meta.twitter as
        | { card?: string; title?: string; description?: string; images?: unknown[] }
        | undefined;
      // `summary` crops a 1200×630 card to a square thumbnail.
      expect(twitter?.card, path).toBe('summary_large_image');
      expect(twitter?.title, path).toBeTruthy();
      expect(twitter?.description, path).toBeTruthy();
      expect(twitter?.images?.length, path).toBe(1);
    }
  });

  it('gives the social image an absolute production URL', () => {
    expect(socialImageUrl()).toBe('https://solveaihub.com/opengraph-image');
    expect(socialImageUrl()).toMatch(/^https:\/\//);
    expect(socialImageUrl()).not.toMatch(/localhost|127\.0\.0\.1|demo\./);
  });

  it('is generated by a route that exists, at the declared size', () => {
    const source = repoFile('app/opengraph-image.tsx');
    expect(existsSync(source)).toBe(true);
    expect(SOCIAL_IMAGE.width).toBe(1200);
    expect(SOCIAL_IMAGE.height).toBe(630);
    expect(SOCIAL_IMAGE.contentType).toBe('image/png');
    // The alt text is what somebody using a screen reader gets instead of the
    // card, so it has to name the product rather than describe a picture.
    expect(SOCIAL_IMAGE.alt).toMatch(/Procurement Intelligence Demo/);
    expect(SOCIAL_IMAGE.alt).toMatch(/Solve AI Hub/);
  });

  it('draws a card that carries no address, no local URL and no secret', () => {
    const source = readFileSync(repoFile('app/opengraph-image.tsx'), 'utf8');
    expect(source).not.toMatch(/@gmail\.com/);
    expect(source).not.toMatch(/localhost|127\.0\.0\.1/);
    expect(source).not.toMatch(/\b(api|database|streamlit):\d{2,5}\b/);
    expect(source).not.toMatch(/(password|secret|token)\s*[=:]/i);
  });
});

/* ------------------------------------------------------------------------ */
/* Icons                                                                     */
/* ------------------------------------------------------------------------ */

describe('icons', () => {
  it('ships a site icon and an Apple touch icon that both exist', () => {
    expect(existsSync(repoFile('app/icon.svg'))).toBe(true);
    expect(existsSync(repoFile('app/apple-icon.tsx'))).toBe(true);
  });

  it('draws the site icon inline, with no external reference', () => {
    const svg = readFileSync(repoFile('app/icon.svg'), 'utf8');
    expect(svg).toMatch(/<svg/);
    /*
     * A favicon that fetches something is a favicon that can fail to load and
     * can report a visit to a third party. The rule is about *fetching*, not
     * about the string `http`: the first version of this banned `https?://`
     * outright and failed on `xmlns="http://www.w3.org/2000/svg"`, which is a
     * namespace identifier that is never resolved. What matters is a reference
     * that a renderer would follow.
     */
    expect(svg).not.toMatch(/(href|src)\s*=\s*["']https?:/i);
    expect(svg).not.toMatch(/url\(\s*["']?https?:/i);
    expect(svg).not.toMatch(/<image\b/);
    expect(svg).toMatch(/Procurement Intelligence Demo by Solve AI Hub/);
  });

  it('adds no manifest, service worker or install prompt', () => {
    // This site is a set of documents. A manifest invites an install prompt and
    // a service worker, which is behaviour nothing here needs and a cache
    // nobody would remember to invalidate.
    for (const path of ['app/manifest.ts', 'app/manifest.json', 'app/sw.ts', 'public/sw.js']) {
      expect(existsSync(repoFile(path)), path).toBe(false);
    }
  });
});

/* ------------------------------------------------------------------------ */
/* Branding                                                                  */
/* ------------------------------------------------------------------------ */

describe('public branding', () => {
  it('publishes the product under the parent brand', () => {
    expect(siteConfig.name).toBe('Procurement Intelligence Demo');
    expect(siteConfig.parentBrand).toBe('Solve AI Hub');
    expect(siteConfig.fullName).toBe('Procurement Intelligence Demo by Solve AI Hub');
  });

  /**
   * The brand is three words with two real spaces in it. The header wordmark
   * used to be two flex children with a `gap`, which paints a space without
   * containing one - so the brand read `Solve AIHub` to anything that reads the
   * page as text. These assert the two ways it can collapse, over every string
   * this project publishes.
   */
  it.each([
    ['Solve AIHub', /Solve\s*AIHub/],
    ['SolveAI Hub', /SolveAI\s*Hub/],
  ])('never writes the brand as %s', (_label, pattern) => {
    const everything = [
      siteConfig.name,
      siteConfig.parentBrand,
      siteConfig.fullName,
      siteConfig.title,
      siteConfig.description,
      siteConfig.shortDescription,
      TRADEMARK_NOTICE,
      SOCIAL_IMAGE.alt,
      ...pageList.flatMap((page) => [page.title, page.absoluteTitle ?? '', page.description]),
      ...allMetadata.map(([, meta]) => resolvedTitle(meta.title)),
      ...allMetadata.map(([, meta]) => String(meta.description)),
    ].join('\n');
    expect(everything).not.toMatch(pattern);
  });

  it('never uses the internal repository name as a public label', () => {
    // SAPDemo remains the repository, the npm package and the image tags. It is
    // not what the product is called.
    for (const [path, meta] of allMetadata) {
      expect(resolvedTitle(meta.title), path).not.toMatch(/SAPDemo/);
      expect(String(meta.description), path).not.toMatch(/SAPDemo/);
      expect(String(meta.openGraph?.title), path).not.toMatch(/SAPDemo/);
    }
    for (const page of pageList) {
      expect(page.description, page.path).not.toMatch(/SAPDemo/);
    }
  });

  it('never describes the project as an official or endorsed SAP product', () => {
    const everything = [
      ...allMetadata.map(([, meta]) => `${resolvedTitle(meta.title)} ${meta.description}`),
      SOCIAL_IMAGE.alt,
      siteConfig.description,
    ].join('\n');
    for (const pattern of [
      /\bofficial SAP\b/i,
      /\bSAP[- ](certified|endorsed|approved|partner)\b/i,
      /\ban SAP product\b/i,
      /\bin partnership with SAP\b/i,
    ]) {
      expect(everything, String(pattern)).not.toMatch(pattern);
    }
    // And the denial is still on every page, through the footer.
    expect(TRADEMARK_NOTICE).toMatch(/not endorsed by/i);
  });

  it('leaves no generic template metadata behind', () => {
    for (const [path, meta] of allMetadata) {
      const text = `${resolvedTitle(meta.title)} ${meta.description}`;
      for (const pattern of [
        /Create Next App/i,
        /Generated by create next app/i,
        /\bNext\.js app\b/i,
        /lorem ipsum/i,
        /\bTODO\b/,
        /\bplaceholder\b/i,
        /your (site|company|product) name/i,
      ]) {
        expect(text, `${path} ${pattern}`).not.toMatch(pattern);
      }
    }
  });
});

/* ------------------------------------------------------------------------ */
/* The tool pages                                                            */
/* ------------------------------------------------------------------------ */

describe('tool page metadata', () => {
  it('gives each tool its own canonical, matching its public slug', () => {
    for (const module of modules) {
      expect(toolMetadata(module).alternates?.canonical).toBe(
        `https://solveaihub.com/tools/${module.slug}`,
      );
    }
  });

  it('titles each tool with its own name', () => {
    for (const module of modules) {
      expect(resolvedTitle(toolMetadata(module).title)).toBe(
        `${module.name} — Procurement Intelligence Demo`,
      );
    }
  });

  it('builds each description from the tool’s own copy, ending in a whole sentence', () => {
    for (const module of modules) {
      const description = String(toolMetadata(module).description);
      expect(description, module.slug).toContain(module.tagline);
      // The previous version was `${tagline} ${problem}`.slice(0, 300), which
      // cut mid-word and mid-clause. The visible half of a sentence about what
      // goes wrong reads as a claim that it does.
      expect(description, module.slug).toMatch(/[.!?]$/);
      expect(description.length, module.slug).toBeLessThanOrEqual(320);
    }
  });

  it('invents no capability that is not in the tool’s own content', () => {
    for (const module of modules) {
      const description = String(toolMetadata(module).description);
      expect(`${module.tagline} ${module.problem}`, module.slug).toContain(
        description.replace(`${module.tagline} `, ''),
      );
    }
  });
});

describe('the not-found metadata', () => {
  it('has a useful title and description', () => {
    expect(resolvedTitle(NOT_FOUND_METADATA.title)).toBe(
      'Page not found — Procurement Intelligence Demo',
    );
    expect(String(NOT_FOUND_METADATA.description).length).toBeGreaterThan(40);
  });

  it('is not indexed, and claims no canonical address', () => {
    expect(NOT_FOUND_METADATA.robots).toMatchObject({ index: false });
    // Without this it inherits the layout's canonical, and every mistyped
    // address on the site announces itself to a crawler as the home page.
    expect(NOT_FOUND_METADATA.alternates).toBeUndefined();
  });

  it('is the metadata an unknown tool slug gets', async () => {
    const { generateMetadata } = await import('@/app/tools/[slug]/page');
    const meta = await generateMetadata({ params: Promise.resolve({ slug: 'not-a-tool' }) });
    expect(meta.alternates).toBeUndefined();
    expect(meta.robots).toMatchObject({ index: false });
  });
});

describe('an overridden page', () => {
  it('may carry its own social title and description without losing anything else', () => {
    const meta = buildMetadata({
      path: '/about',
      title: 'About',
      description: 'A description.',
      socialTitle: 'Something else',
      socialDescription: 'Something else again',
    });
    expect(meta.openGraph?.title).toBe('Something else');
    expect(meta.twitter).toMatchObject({ title: 'Something else' });
    expect(meta.openGraph?.description).toBe('Something else again');
    expect(meta.description).toBe('A description.');
    expect(meta.alternates?.canonical).toBe('https://solveaihub.com/about');
  });
});

/* ------------------------------------------------------------------------ */
/* Sitemap and robots                                                        */
/* ------------------------------------------------------------------------ */

describe('the sitemap', () => {
  const entries = sitemap();
  const urls = entries.map((entry) => entry.url);

  it('lists every public marketing page', () => {
    for (const page of publishedPages(siteConfig.servicesPageEnabled)) {
      expect(urls, page.path).toContain(canonicalUrl(page.path));
    }
  });

  it('lists all ten tool pages', () => {
    for (const module of modules) {
      expect(urls, module.slug).toContain(`https://solveaihub.com/tools/${module.slug}`);
    }
    expect(urls.filter((url) => url.includes('/tools/'))).toHaveLength(10);
  });

  it('lists nothing twice', () => {
    expect(new Set(urls).size).toBe(urls.length);
  });

  it('uses the canonical production origin for every entry', () => {
    for (const url of urls) {
      expect(url).toMatch(/^https:\/\/solveaihub\.com(\/|$)/);
    }
  });

  it.each([
    ['API routes', /\/api\b/],
    ['the protected demonstration', /demo\.solveaihub\.com/],
    ['query-string variants', /\?/],
    ['localhost', /localhost/],
    ['a loopback address', /127\.0\.0\.1/],
    ['the 404', /404|not-found/],
    ['the sitemap or robots files themselves', /sitemap\.xml|robots\.txt/],
    ['the social image route', /opengraph-image|apple-icon|icon\.svg/],
  ])('excludes %s', (_label, pattern) => {
    for (const url of urls) {
      expect(url, String(pattern)).not.toMatch(pattern);
    }
  });

  it('lists only routes that exist', () => {
    const known = new Set([
      ...PAGE_PATHS.map((path) => canonicalUrl(path)),
      ...modules.map((module) => canonicalUrl(`/tools/${module.slug}`)),
    ]);
    for (const url of urls) {
      expect(known, url).toContain(url);
    }
  });

  it('follows the services switch, exactly as the navigation and the footer do', () => {
    // A page that is not linked anywhere must not be advertised to a crawler.
    expect(publishedPages(false).map((page) => page.path)).not.toContain('/services');
    expect(publishedPages(true).map((page) => page.path)).toContain('/services');
  });
});

describe('robots', () => {
  const rules = robots();

  it('points at the sitemap on the production origin', () => {
    expect(rules.sitemap).toBe('https://solveaihub.com/sitemap.xml');
  });

  it('does not disallow the public site', () => {
    const rule = rules.rules as { allow?: string; disallow?: string[] };
    expect(rule.allow).toBe('/');
    expect(rule.disallow ?? []).not.toContain('/');
  });

  it('does not offer the API as a crawl target', () => {
    const rule = rules.rules as { disallow?: string[] };
    expect(rule.disallow).toContain('/api/');
  });
});

/* ------------------------------------------------------------------------ */
/* The registries the metadata is built from                                 */
/* ------------------------------------------------------------------------ */

describe('the page registry', () => {
  it('holds one definition per path, and each knows its own path', () => {
    expect(pageList).toHaveLength(PAGE_PATHS.length);
    for (const path of PAGE_PATHS) {
      expect(pages[path].path).toBe(path);
    }
  });

  it('lists no route that is only reachable with a query string', () => {
    for (const path of PAGE_PATHS) {
      expect(path).toBe(canonicalPath(path));
    }
  });
});

describe('the problem areas', () => {
  it('covers all ten modules, each in exactly one area', () => {
    const ids = problemAreas.flatMap((area) => area.moduleIds);
    expect(new Set(ids).size).toBe(ids.length);
    expect([...ids].sort()).toEqual(modules.map((module) => module.id).sort());
  });

  it('names only modules that exist', () => {
    const known = new Set(modules.map((module) => module.id));
    for (const area of problemAreas) {
      for (const id of area.moduleIds) {
        expect(known, `${area.title} → ${id}`).toContain(id);
      }
    }
  });

  it('covers the six areas the site says it addresses', () => {
    expect(problemAreas.map((area) => area.title)).toEqual([
      'Risk and compliance',
      'Spend visibility and savings analysis',
      'Supplier selection and risk',
      'Invoice and contract review',
      'Inventory planning',
      'SAP project delivery and training',
    ]);
  });
});

describe('the compact tool overview content', () => {
  it('gives every module a short input, output and purpose', () => {
    for (const module of modules) {
      for (const [field, value] of Object.entries(module.overview)) {
        expect(value.length, `${module.id}.${field}`).toBeGreaterThan(10);
        // A card is scanned, not read. Anything longer than this is a paragraph
        // in a space that has room for a phrase.
        expect(value.length, `${module.id}.${field}`).toBeLessThanOrEqual(75);
      }
    }
  });

  it('keeps internals off the cards', () => {
    // Test counts, endpoint counts, table names and container details tell a
    // procurement reader nothing about whether a tool is about their problem.
    for (const module of modules) {
      const text = Object.values(module.overview).join(' ');
      for (const pattern of [
        // A *count* of tests, not the word: "a structured test suite across
        // eight test types" is what the tool produces and is exactly what a
        // reader wants. A ban on the word would have deleted it, and a test
        // that cries wolf is removed by the next person in a hurry.
        /\d+\s*(unit |api |integration )?tests?\b/i,
        /\d+\s*endpoints?\b/i,
        /\bendpoints?\b/i,
        /\bdocker\b/i,
        /\bdatabase tables?\b/i,
        /\b(FastAPI|Streamlit|PostgreSQL|SQLite|Next\.js)\b/i,
        /\bAPI\b/,
      ]) {
        expect(text, `${module.id} ${pattern}`).not.toMatch(pattern);
      }
    }
  });

  it('implies no live SAP connection, no customer upload and no guarantee', () => {
    const text = modules.map((module) => Object.values(module.overview).join(' ')).join('\n');
    for (const pattern of [
      /\bconnects? to (your |a live )?SAP\b/i,
      /\bupload your\b/i,
      /\bguarantee/i,
      /\bcustomer data\b/i,
      /\byour (invoices|suppliers|contracts|data)\b/i,
    ]) {
      expect(text, String(pattern)).not.toMatch(pattern);
    }
  });
});

describe('the four output methods', () => {
  it('is the five origins without the one that describes the input', () => {
    expect(methodOrigins.map((entry) => entry.origin)).toEqual([
      'rule_based',
      'forecast',
      'ai_generated',
      'mock_ai',
    ]);
    expect(origins).toHaveLength(5);
  });

  it('gives every origin examples of what it covers', () => {
    for (const entry of origins) {
      expect(entry.examples.length, entry.origin).toBeGreaterThanOrEqual(2);
      for (const example of entry.examples) {
        expect(example.length, `${entry.origin}: ${example}`).toBeGreaterThan(15);
      }
    }
  });

  it('says the mock provider makes no external call', () => {
    const mock = origins.find((entry) => entry.origin === 'mock_ai');
    expect(mock?.examples.join(' ')).toMatch(/no external call|without.*call|no provider/i);
  });
});

describe('the illustrative example panels', () => {
  it('labels the computed half and the written half separately', () => {
    for (const panel of examplePanels) {
      // A panel with one label would show a computed finding and a written
      // paragraph as though one thing produced both - the exact confusion the
      // origin labels exist to prevent.
      expect(panel.origin, panel.title).not.toBe(panel.narrative.origin);
      expect(['rule_based', 'forecast'], panel.title).toContain(panel.origin);
      expect(['ai_generated', 'mock_ai'], panel.title).toContain(panel.narrative.origin);
    }
  });

  it('illustrates modules that exist', () => {
    const names = new Set(modules.map((module) => module.name));
    for (const panel of examplePanels) {
      expect(names, panel.moduleName).toContain(panel.moduleName);
    }
  });

  it('claims no customer, no outcome and no saving', () => {
    const text = examplePanels
      .map((panel) =>
        [
          panel.title,
          panel.evidence,
          panel.narrative.text,
          ...panel.fields.map((field) => `${field.label} ${field.value}`),
        ].join(' '),
      )
      .join('\n');
    for (const pattern of [
      /\bsaved\b/i,
      /\bsavings? of\b/i,
      /\bcustomer\b/i,
      /\bclient\b/i,
      /\bprevented\b/i,
      /\bin production\b/i,
      /\breal SAP\b/i,
      /\bscreenshot\b/i,
    ]) {
      expect(text, String(pattern)).not.toMatch(pattern);
    }
  });
});
