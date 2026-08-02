import { afterEach, describe, expect, it, vi } from 'vitest';
import { moduleBySlug, moduleSlugs, modules } from '@/content/modules';
import { origins, originByKey } from '@/content/origins';
import { DEMO_NOTICE, TRADEMARK_NOTICE, mailto, siteConfig } from '@/lib/site';

/**
 * These assert the *content contract*, not a count. A test that only checked
 * `modules.length === 10` would pass with the same module listed ten times, and
 * would keep passing after a module was renamed to something the API does not
 * serve. The exact identifier list is the thing worth pinning.
 */
const EXPECTED_MODULE_IDS = [
  'po_risk',
  'spend_analytics',
  'supplier_recommendation',
  'invoice_validator',
  'supplier_risk_copilot',
  'contract_assistant',
  'inventory_predictor',
  'test_case_generator',
  'blueprint_generator',
  'interview_coach',
] as const;

describe('module content', () => {
  it('lists exactly the ten module ids the API serves, in order', () => {
    expect(modules.map((module) => module.id)).toEqual([...EXPECTED_MODULE_IDS]);
  });

  it('numbers the modules 1..10 with no gaps or repeats', () => {
    expect(modules.map((module) => module.number)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  });

  it('gives every module a unique slug that is URL safe', () => {
    expect(new Set(moduleSlugs).size).toBe(modules.length);
    for (const slug of moduleSlugs) {
      expect(slug).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/);
    }
  });

  it('resolves a module by slug and returns undefined for an unknown one', () => {
    expect(moduleBySlug('purchase-order-risk-checker')?.id).toBe('po_risk');
    expect(moduleBySlug('does-not-exist')).toBeUndefined();
  });

  it('gives every module the copy each detail page renders', () => {
    for (const module of modules) {
      expect(module.name.length, module.id).toBeGreaterThan(3);
      expect(module.tagline.length, module.id).toBeGreaterThan(10);
      expect(module.problem.length, module.id).toBeGreaterThan(40);
      expect(module.demoInput.length, module.id).toBeGreaterThan(40);
      expect(module.computed.length, module.id).toBeGreaterThanOrEqual(3);
      expect(module.aiWrites.length, module.id).toBeGreaterThanOrEqual(2);
      expect(module.outputs.length, module.id).toBeGreaterThanOrEqual(2);
      expect(module.steps.length, module.id).toBeGreaterThanOrEqual(3);
      expect(module.origins.length, module.id).toBeGreaterThanOrEqual(2);
    }
  });

  it('always labels demonstration data as an origin', () => {
    for (const module of modules) {
      expect(module.origins, module.id).toContain('demo_data');
    }
  });

  it('references only origins that are described on the site', () => {
    const known = new Set(origins.map((entry) => entry.origin));
    for (const module of modules) {
      for (const origin of module.origins) {
        expect(known, `${module.id} → ${origin}`).toContain(origin);
      }
    }
  });
});

describe('claims the site must never make', () => {
  const allCopy = [
    ...modules.flatMap((module) => [
      module.tagline,
      module.problem,
      module.demoInput,
      ...module.computed,
      ...module.aiWrites,
      ...module.outputs,
      ...module.steps,
    ]),
    ...origins.flatMap((entry) => [entry.summary, entry.detail]),
    siteConfig.description,
    siteConfig.shortDescription,
    DEMO_NOTICE,
  ].join('\n');

  it.each([
    ['SAP partnership', /\bSAP\s+(partner|certified|endorsed|approved)\b/i],
    ['claimed affiliation', /\b(in partnership with|certified by|endorsed by)\b/i],
    ['guaranteed savings', /\bguaranteed savings?\b/i],
    ['production deployment claim', /\b(deployed|running) in production\b/i],
    ['customer counts', /\b\d+\+?\s+(customers|clients|companies use)\b/i],
  ])('makes no %s claim', (_label, pattern) => {
    expect(allCopy).not.toMatch(pattern);
  });

  /**
   * "Live SAP" needs sentence-level checking rather than a phrase ban, and the
   * first version of this test proved why: it matched the project's own
   * *denial* - "Nothing is connected to a live SAP system" - and reported the
   * disclaimer as a forbidden claim. The rule that matters is not "never say
   * live SAP", it is "never say it affirmatively".
   */
  it('mentions a live SAP system only to deny a connection to one', () => {
    const sentences = allCopy.split(/(?<=[.!?])\s+/);
    const mentions = sentences.filter((sentence) => /live SAP|SAP system/i.test(sentence));
    expect(mentions.length).toBeGreaterThan(0);
    for (const sentence of mentions) {
      expect(sentence, sentence).toMatch(/\b(no|not|none|never|nothing|without)\b/i);
    }
  });

  it('states the trademark position without claiming a relationship', () => {
    expect(TRADEMARK_NOTICE).toMatch(/not endorsed by/i);
    expect(TRADEMARK_NOTICE).toMatch(/trademarks of SAP SE/i);
  });

  it('states that the data is fictional and unconnected to SAP', () => {
    expect(DEMO_NOTICE).toMatch(/fictional/i);
    expect(DEMO_NOTICE).toMatch(/nothing is connected to a live SAP system/i);
    expect(DEMO_NOTICE).toMatch(/no output has been validated/i);
  });
});

describe('site configuration', () => {
  it('reads the demo destination from the environment rather than a hardcoded domain', () => {
    // The default is a localhost placeholder. A real domain compiled in here is
    // how a build ends up linking at the wrong deployment.
    expect(siteConfig.demoUrl).toBeTruthy();
    expect(siteConfig.demoUrl).not.toMatch(/\.(com|net|io|dev|app)\b(?!.*localhost)/);
  });

  it('publishes the product under the parent brand, and never as the internal name', () => {
    expect(siteConfig.name).toBe('Procurement Intelligence Demo');
    expect(siteConfig.parentBrand).toBe('Solve AI Hub');
    expect(siteConfig.fullName).toBe('Procurement Intelligence Demo by Solve AI Hub');
    // SAPDemo is the repository, the package and the image tags. It is not a
    // public label, and nothing a visitor reads may carry it.
    for (const value of [
      siteConfig.name,
      siteConfig.parentBrand,
      siteConfig.fullName,
      siteConfig.title,
      siteConfig.description,
      siteConfig.shortDescription,
      TRADEMARK_NOTICE,
    ]) {
      expect(value).not.toMatch(/SAPDemo/);
    }
  });

  it('has no public repository configured, so every source link is hidden', () => {
    // The repository is private. `null` rather than `''` is the point: an empty
    // string is a renderable href.
    expect(siteConfig.repositoryUrl).toBeNull();
  });

  it('uses the one official public contact address', () => {
    expect(siteConfig.contactEmail).toBe('solveaihub@gmail.com');
  });

  it('builds a mailto link with an encoded subject', () => {
    expect(mailto('A subject with spaces')).toBe(
      'mailto:solveaihub@gmail.com?subject=A%20subject%20with%20spaces',
    );
  });

  it('exposes no secret-shaped configuration to the browser', () => {
    for (const value of Object.values(siteConfig)) {
      expect(String(value)).not.toMatch(/sk-[A-Za-z0-9-]{16,}/);
      expect(String(value)).not.toMatch(/(password|secret|token)=/i);
    }
  });

  it('links the services page by default, so an unset variable cannot hide it', () => {
    expect(siteConfig.servicesPageEnabled).toBe(true);
  });
});

/**
 * A blank build argument is not an absent one.
 *
 * `docker-compose.selfhosted.yml` writes `${PUBLIC_SITE_URL:-}` and the
 * Dockerfile writes `ARG NEXT_PUBLIC_SITE_URL=""`, so a variable left unset in
 * `.env.selfhosted` reaches the build as a defined empty string. `??` does not
 * fall back on that, which broke all three values at once: the build threw
 * `ERR_INVALID_URL`, every Launch Demo button rendered `href=""`, and the
 * contact link lost its recipient.
 *
 * These assert against the *empty string* specifically. A test that only set
 * the variables to `undefined` passed throughout the bug's entire lifetime,
 * because `undefined` is the one input the old operator handled correctly.
 */
describe('site configuration built from a blank environment', () => {
  /**
   * The three ways a value arrives unconfigured.
   *
   * `undefined` is the only one the old `??` handled, which is why a test that
   * stubbed only `undefined` passed throughout that bug's entire lifetime.
   * Docker supplies the other two: `${PUBLIC_X:-}` is a defined empty string,
   * and a hand-edited environment file supplies the space.
   */
  const ABSENT_CASES = [undefined, '', '   '] as const;

  /**
   * Returns the freshly-evaluated module, not just its config. `siteConfig` is
   * built once at module scope, so the statically imported `mailto` at the top
   * of this file closes over the *unstubbed* config - asserting on that one
   * would pass no matter what these stubs say.
   */
  async function moduleWith(value: string | undefined) {
    vi.resetModules();
    for (const name of [
      'NEXT_PUBLIC_SITE_URL',
      'NEXT_PUBLIC_DEMO_URL',
      'NEXT_PUBLIC_CONTACT_EMAIL',
      'NEXT_PUBLIC_REPOSITORY_URL',
    ]) {
      vi.stubEnv(name, value);
    }
    return import('@/lib/site');
  }

  async function configWith(value: string | undefined) {
    return (await moduleWith(value)).siteConfig;
  }

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it.each(ABSENT_CASES)('falls back to a usable site URL when it is %o', async (value) => {
    const config = await configWith(value);
    // `new URL('')` throws, and `app/layout.tsx` calls exactly that on this
    // value - so a blank here fails the whole build, not just one page.
    expect(() => new URL(config.url)).not.toThrow();
  });

  it.each(ABSENT_CASES)('falls back to a usable demo URL when it is %o', async (value) => {
    const config = await configWith(value);
    // An empty href is not a broken link a browser reports; it silently
    // reloads the page the visitor is already on.
    expect(config.demoUrl).not.toBe('');
    expect(() => new URL(config.demoUrl)).not.toThrow();
  });

  it.each(ABSENT_CASES)(
    'falls back to the official contact address when it is %o',
    async (value) => {
      const site = await moduleWith(value);
      expect(site.siteConfig.contactEmail).toBe('solveaihub@gmail.com');
      // A recipientless `mailto:?subject=...` opens an empty compose window, so
      // the failure reaches the visitor rather than the operator.
      expect(site.mailto('Hello')).not.toMatch(/^mailto:\?/);
      expect(site.mailto('Hello')).toBe('mailto:solveaihub@gmail.com?subject=Hello');
    },
  );

  it.each(ABSENT_CASES)('reports no repository at all when it is %o', async (value) => {
    const site = await moduleWith(value);
    // `null`, never `''`. An empty string would render `href=""`, which is a
    // working anchor that reloads the current page - the failure this whole
    // arrangement exists to prevent.
    expect(site.siteConfig.repositoryUrl).toBeNull();
    expect(site.hasRepository).toBe(false);
    expect(site.repositoryLabel()).toBeNull();
  });

  it('honours a configured contact address, and trims it', async () => {
    vi.resetModules();
    vi.stubEnv('NEXT_PUBLIC_CONTACT_EMAIL', '  someone@example.org  ');
    const { siteConfig: config } = await import('@/lib/site');
    expect(config.contactEmail).toBe('someone@example.org');
  });

  it('brings the repository back when a valid URL is configured, and trims it', async () => {
    vi.resetModules();
    vi.stubEnv('NEXT_PUBLIC_REPOSITORY_URL', '  https://github.com/example/repo  ');
    const site = await import('@/lib/site');
    expect(site.siteConfig.repositoryUrl).toBe('https://github.com/example/repo');
    expect(site.hasRepository).toBe(true);
    expect(site.repositoryLabel()).toBe('github.com/example/repo');
  });

  it.each([
    ['no scheme', 'github.com/example/repo'],
    ['a relative path', '/example/repo'],
    ['a non-web scheme', 'javascript:alert(1)'],
    ['a shell fragment', '${PUBLIC_REPOSITORY_URL}'],
  ])('treats %s as no repository rather than rendering it', async (_label, value) => {
    vi.resetModules();
    vi.stubEnv('NEXT_PUBLIC_REPOSITORY_URL', value);
    const site = await import('@/lib/site');
    expect(site.siteConfig.repositoryUrl).toBeNull();
    expect(site.hasRepository).toBe(false);
  });

  it('still honours a real value, and trims it', async () => {
    vi.resetModules();
    vi.stubEnv('NEXT_PUBLIC_DEMO_URL', '  https://demo.example.com  ');
    const { siteConfig: config } = await import('@/lib/site');
    expect(config.demoUrl).toBe('https://demo.example.com');
  });

  it.each([
    ['false', false],
    ['0', false],
    ['no', false],
    ['off', false],
    ['FALSE', false],
    ['true', true],
    ['', true],
    ['   ', true],
  ])('reads SERVICES_PAGE_ENABLED=%o as %o', async (value, expected) => {
    vi.resetModules();
    vi.stubEnv('SERVICES_PAGE_ENABLED', value);
    const { siteConfig: config } = await import('@/lib/site');
    expect(config.servicesPageEnabled).toBe(expected);
  });
});

describe('origins', () => {
  it('describes all five output origins', () => {
    expect(origins.map((entry) => entry.origin)).toEqual([
      'rule_based',
      'forecast',
      'ai_generated',
      'mock_ai',
      'demo_data',
    ]);
  });

  it('throws rather than rendering an unlabelled badge for an unknown origin', () => {
    // @ts-expect-error - deliberately passing a value outside the union.
    expect(() => originByKey('made_up')).toThrow(/Unknown output origin/);
  });
});
