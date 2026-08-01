import { describe, expect, it } from 'vitest';
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

  it('points the repository link at the current canonical repository', () => {
    expect(siteConfig.repositoryUrl).toContain('iShayanNabi/SAPDemo');
    expect(siteConfig.repositoryUrl).not.toContain('Chacho-Project');
  });

  it('builds a mailto link with an encoded subject', () => {
    expect(mailto('A subject with spaces')).toBe(
      `mailto:${siteConfig.contactEmail}?subject=A%20subject%20with%20spaces`,
    );
  });

  it('exposes no secret-shaped configuration to the browser', () => {
    for (const value of Object.values(siteConfig)) {
      expect(String(value)).not.toMatch(/sk-[A-Za-z0-9-]{16,}/);
      expect(String(value)).not.toMatch(/(password|secret|token)=/i);
    }
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
