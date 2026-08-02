import { render } from '@testing-library/react';
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
import { Footer } from '@/components/Footer';
import { modules } from '@/content/modules';
import {
  ACCESS_NOTICE,
  DEMO_NOTICE,
  POLICY_LAST_UPDATED,
  UPLOAD_NOTICE,
  siteConfig,
} from '@/lib/site';

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

/** The visible text of one page, whitespace collapsed so a line break in the JSX cannot hide a phrase. */
function textOf(Page: (typeof pages)[number][1]): string {
  const { container, unmount } = render(<Page />);
  const text = (container.textContent ?? '').replace(/\s+/g, ' ');
  unmount();
  return text;
}

/** The visible text of every page, including the ten module detail pages. */
async function everyPageText(): Promise<Array<readonly [string, string]>> {
  const collected: Array<readonly [string, string]> = pages.map(
    ([name, Page]) => [name, textOf(Page)] as const,
  );
  for (const module of modules) {
    const { container, unmount } = render(
      await ModulePage({ params: Promise.resolve({ slug: module.slug }) }),
    );
    collected.push([`tools/${module.slug}`, (container.textContent ?? '').replace(/\s+/g, ' ')]);
    unmount();
  }
  return collected;
}

/**
 * Sentences on a page that mention `pattern`.
 *
 * Several of the phrases this file polices are ones the site is *supposed* to
 * use, in a denial - "not offered as a commercially production-ready product"
 * has to survive a ban on "production ready". A phrase ban would fail on the
 * disclaimer doing its job, and the lesson from the last phase of this project
 * is that a test which cries wolf gets deleted rather than fixed. So the unit
 * of assertion is the sentence, and the rule is about how the phrase is used.
 */
function sentencesMentioning(text: string, pattern: RegExp): string[] {
  return text.split(/(?<=[.!?])\s+/).filter((sentence) => pattern.test(sentence));
}

const NEGATED = /\b(no|not|none|never|nothing|nobody|cannot|does not|is not|are not|without)\b/i;

describe('the privacy policy', () => {
  const text = () => textOf(PrivacyPage);

  it('no longer describes itself as a placeholder or as unfinished', () => {
    expect(text()).not.toMatch(/placeholder/i);
    expect(text()).not.toMatch(/coming (soon|later)/i);
    expect(text()).not.toMatch(/pending a full policy/i);
  });

  it('shows the last-updated date', () => {
    expect(text()).toMatch(new RegExp(`Last updated:\\s*${POLICY_LAST_UPDATED}`));
  });

  it('separates the public website from the protected demonstration', () => {
    const body = text();
    expect(body).toMatch(/public(ly)? (accessible|marketing)/i);
    expect(body).toMatch(/Cloudflare Access/);
    expect(body).toMatch(/separate (application|hostname)/i);
  });

  it('describes the operational and Cloudflare logging it actually has', () => {
    const body = text();
    expect(body).toMatch(/operational logging/i);
    expect(body).toMatch(/Cloudflare/);
    expect(body).toMatch(/troubleshoot/i);
  });

  it('states the cautious retention position rather than a period it cannot verify', () => {
    expect(text()).toMatch(
      /retained for as long as reasonably necessary to operate, secure, troubleshoot and respond/i,
    );
  });

  it('warns against sending sensitive or confidential information', () => {
    const body = text();
    expect(body).toMatch(/confidential/i);
    expect(body).toMatch(/do not (enter|email|send)/i);
  });

  it('says contact information is not sold', () => {
    expect(text()).toMatch(/not sold/i);
  });

  it('acknowledges cookies and session technologies rather than denying them', () => {
    expect(text()).toMatch(/does not claim that no cookies or session technologies are involved/i);
  });

  it('reaches the official contact address', () => {
    expect(text()).toContain(siteConfig.contactEmail);
  });

  /**
   * The list from the brief of claims a privacy page must not make. Each is a
   * claim about an absolute that this deployment cannot evidence - and three of
   * them (deletion, anonymity, third-party retention) are about behaviour owned
   * by Cloudflare or an email provider rather than by this project at all.
   */
  it.each([
    ['zero logging', /\b(zero|no)\s+logging\b/i],
    ['complete anonymity', /\b(completely|fully|entirely)\s+anonymous\b/i],
    ['no data processed', /\bno data is processed\b/i],
    ['guaranteed deletion', /\b(guaranteed|permanent(ly)?) deletion\b/i],
    ['nothing retained', /\b(nothing is ever retained|no information is retained)\b/i],
    // Not a ban on the substring "no cookies": the page's honest sentence is
    // "does not claim that no cookies ... are involved, because they are",
    // which contains it while asserting the opposite. What must never appear is
    // the affirmative claim.
    ['no cookies at all', /\b(sets?|uses?|stores?|places?) no cookies\b|\bno cookies (are|is) (used|set|stored)\b/i],
    ['a third party never retaining anything', /\b(cloudflare|email providers?) never\b/i],
  ])('makes no %s claim', (_label, pattern) => {
    expect(text()).not.toMatch(pattern);
  });

  it('does not promise deletion it cannot carry out at a third party', () => {
    expect(text()).not.toMatch(/ask and it will be deleted/i);
    // The honest version: what the project holds, versus what a provider holds.
    expect(text()).toMatch(/outside this project’s control/i);
  });
});

describe('the terms of use', () => {
  const text = () => textOf(TermsPage);

  it('no longer describes itself as a placeholder', () => {
    expect(text()).not.toMatch(/placeholder/i);
    expect(text()).not.toMatch(/pending formal terms/i);
  });

  it('shows the last-updated date', () => {
    expect(text()).toMatch(new RegExp(`Last updated:\\s*${POLICY_LAST_UPDATED}`));
  });

  it('describes the project as an educational, technical and portfolio demonstration', () => {
    expect(text()).toMatch(/educational, technical and portfolio demonstration/i);
  });

  it('disclaims every category of professional advice named in the brief', () => {
    const body = text();
    for (const field of [
      /legal/i,
      /financial/i,
      /procurement/i,
      /cybersecurity/i,
      /medical/i,
      /regulatory/i,
    ]) {
      expect(body, String(field)).toMatch(field);
    }
    expect(body).toMatch(/not legal, financial, procurement, cybersecurity, medical, regulatory/i);
  });

  it('requires qualified human review of the outputs', () => {
    const body = text();
    expect(body).toMatch(/qualified/i);
    expect(body).toMatch(/review/i);
    expect(body).toMatch(/incomplete, simulated/i);
  });

  it('tells users to submit only fictional, sanitised or non-confidential information', () => {
    const body = text();
    expect(body).toMatch(/fictional, sanitised or otherwise non-confidential/i);
    for (const forbidden of [
      /personal information/i,
      /medical, financial or otherwise regulated/i,
      /production SAP data/i,
      /proprietary or confidential/i,
      /credentials, keys, tokens/i,
    ]) {
      expect(body, String(forbidden)).toMatch(forbidden);
    }
  });

  it('states the acceptable-use rules', () => {
    const body = text();
    for (const rule of [
      /unauthorised access/i,
      /denial-of-service/i,
      /automated attacks/i,
      /credential abuse/i,
      /scraping that harms/i,
      /security testing without prior written permission/i,
    ]) {
      expect(body, String(rule)).toMatch(rule);
    }
  });

  it('says access may be withdrawn and availability is not guaranteed', () => {
    const body = text();
    expect(body).toMatch(/modified, suspended, restricted or withdrawn/i);
    expect(body).toMatch(/uninterrupted operation are not guaranteed/i);
  });

  it('says it is not an official SAP product and keeps the trademark position', () => {
    const body = text();
    expect(body).toMatch(/is not an official SAP product/i);
    expect(body).toMatch(/not endorsed by, certified by, sponsored by/i);
    expect(body).toMatch(/trademarks of SAP SE/i);
    expect(body).toMatch(/respective owners/i);
  });

  it('does not claim a lawyer wrote it, and does not claim all liability disappears', () => {
    const body = text();
    expect(body).toMatch(/not been drafted or reviewed by a lawyer/i);
    expect(body).not.toMatch(/reviewed by (our|a) (lawyer|counsel|solicitor|attorney)\b(?! )/i);
    // "To the extent permitted by applicable law" is the honest form. A page
    // claiming to exclude liability outright is claiming something no document
    // achieves in every jurisdiction.
    expect(body).toMatch(/to the extent permitted by applicable law/i);
    expect(body).not.toMatch(/(all|any and all) liability is excluded/i);
  });
});

describe('authentication is described as it is deployed', () => {
  it('never says there is no authentication', async () => {
    for (const [name, text] of await everyPageText()) {
      expect(text, name).not.toMatch(/there is no (user )?authentication/i);
      expect(text, name).not.toMatch(/\bno user authentication\b/i);
    }
  });

  /**
   * "No authentication" is true of one thing on this site - the public
   * marketing website - and false of the demonstration. Banning the phrase
   * outright would delete an accurate and useful sentence, so the rule is that
   * every sentence using it has to name what it is talking about.
   */
  it('only says something requires no authentication when it means the public website', async () => {
    for (const [name, text] of await everyPageText()) {
      for (const sentence of sentencesMentioning(text, /no (authentication|account)/i)) {
        expect(sentence, `${name}: ${sentence}`).toMatch(
          /website|marketing site|public|this site|internal|application|accounts,/i,
        );
      }
    }
  });

  it('states the Cloudflare Access position in the exact agreed wording', () => {
    expect(ACCESS_NOTICE).toMatch(
      /Cloudflare Access authenticates approved visitors at the network edge/,
    );
    expect(ACCESS_NOTICE).toMatch(
      /does not maintain internal user accounts, roles, organisations, tenant permissions or enterprise identity administration/,
    );
  });

  it.each([
    ['privacy', PrivacyPage],
    ['terms', TermsPage],
    ['architecture', ArchitecturePage],
    ['demo disclaimer', DemoDisclaimerPage],
  ] as const)('renders that position on the %s page', (_name, Page) => {
    expect(textOf(Page)).toContain(ACCESS_NOTICE);
  });

  it('says application-level token verification is not deployed yet', () => {
    const body = `${textOf(ArchitecturePage)} ${textOf(PrivacyPage)}`;
    expect(body).toMatch(/has not been deployed/i);
    expect(body).toMatch(/perimeter control/i);
  });

  it('never claims application-level JWT verification exists', async () => {
    for (const [name, text] of await everyPageText()) {
      for (const sentence of sentencesMentioning(text, /\b(jwt|access token)\b/i)) {
        expect(sentence, `${name}: ${sentence}`).toMatch(NEGATED);
      }
    }
  });

  it('never implies the public marketing website needs a login', async () => {
    for (const [name, text] of await everyPageText()) {
      expect(text, name).not.toMatch(/sign in to (read|view|browse) this (site|website)/i);
      expect(text, name).not.toMatch(/this website requires (a login|authentication|an account)/i);
    }
  });

  it('distinguishes the public website from the separately hosted demonstration', () => {
    for (const [name, Page] of [
      ['privacy', PrivacyPage],
      ['architecture', ArchitecturePage],
      ['demo disclaimer', DemoDisclaimerPage],
    ] as const) {
      const body = textOf(Page);
      expect(body, name).toMatch(/public/i);
      expect(body, name).toMatch(/separate hostname|separate application|own hostname/i);
      expect(body, name).toMatch(/Cloudflare Access/);
    }
  });

  it('names the deployed pieces on the architecture page without leaking a secret', () => {
    const body = textOf(ArchitecturePage);
    for (const piece of [/Next\.js/, /Streamlit/i, /FastAPI/, /PostgreSQL/, /Cloudflare Tunnel/]) {
      expect(body, String(piece)).toMatch(piece);
    }
    // The tunnel is named; the token, the host and the credentials are not.
    expect(body).not.toMatch(/CLOUDFLARE_TUNNEL_TOKEN/);
    expect(body).not.toMatch(/eyJ[A-Za-z0-9_-]{20,}/);
    expect(body).toMatch(/nothing about the tunnel, its credentials or the host/i);
  });
});

describe('upload wording matches the disabled state', () => {
  it('states the agreed position', () => {
    expect(UPLOAD_NOTICE).toMatch(/currently uses bundled fictional data/i);
    expect(UPLOAD_NOTICE).toMatch(/planned but are not currently enabled/i);
  });

  it.each([
    ['home', HomePage],
    ['how it works', HowItWorksPage],
    ['architecture', ArchitecturePage],
    ['platform', PlatformPage],
    ['privacy', PrivacyPage],
    ['terms', TermsPage],
    ['demo disclaimer', DemoDisclaimerPage],
  ] as const)('carries it on the %s page', (_name, Page) => {
    expect(textOf(Page)).toContain(UPLOAD_NOTICE);
  });

  it('carries it on every module detail page', async () => {
    for (const module of modules) {
      const { container, unmount } = render(
        await ModulePage({ params: Promise.resolve({ slug: module.slug }) }),
      );
      expect((container.textContent ?? '').replace(/\s+/g, ' '), module.slug).toContain(
        UPLOAD_NOTICE,
      );
      unmount();
    }
  });

  it.each([
    ['an invitation to upload', /upload your (files?|data|export|spreadsheet)/i],
    ['bring your own export', /bring your own\b/i],
    ['uploading customer documents', /upload (customer|supplier|your) documents/i],
    ['immediate deletion', /files? (are|is) immediately deleted/i],
    ['drag and drop', /drag (and|&) drop (your|a) file/i],
  ])('makes no %s claim anywhere', async (_label, pattern) => {
    for (const [name, text] of await everyPageText()) {
      expect(text, name).not.toMatch(pattern);
    }
  });

  it('keeps the three upload states distinguishable rather than merged', () => {
    const body = textOf(PrivacyPage);
    expect(body).toMatch(/refused server-side/i);
    expect(body).toMatch(/run privately on a laptop/i);
    expect(body).toMatch(/if secure uploads for approved users are enabled in future/i);
  });
});

describe('claims no page may make', () => {
  it.each([
    ['a placeholder page', /\bplaceholder\b/i],
    ['work coming soon', /\bcoming (soon|later)\b/i],
    ['a live SAP integration', /\blive SAP integration\b/i],
    ['guaranteed accuracy', /\bguaranteed (accuracy|results?)\b/i],
    ['replacing professional review', /\breplaces? (professional|expert|human) review\b/i],
  ])('never says %s', async (_label, pattern) => {
    for (const [name, text] of await everyPageText()) {
      expect(text, name).not.toMatch(pattern);
    }
  });

  /**
   * These four are phrases the site has to be able to *deny*. "not offered as a
   * commercially production-ready product" and "does not replace review by a
   * qualified lawyer" are the disclaimer working, so the assertion is on how
   * the phrase is used rather than on whether it appears.
   */
  it.each([
    ['production or enterprise readiness', /\b(production|enterprise)[ -]read(y|iness)\b/i],
    ['a connection to SAP', /\bconnected to (a |an |any )?(live |production )?SAP\b/i],
    ['an official SAP product', /\bofficial SAP product\b/i],
    ['legal advice', /\blegal advice\b/i],
  ])('mentions %s only to deny it', async (_label, pattern) => {
    for (const [name, text] of await everyPageText()) {
      for (const sentence of sentencesMentioning(text, pattern)) {
        expect(sentence, `${name}: ${sentence}`).toMatch(NEGATED);
      }
    }
  });
});

describe('the disclaimers that must stay visible', () => {
  it('every module page states what that specific tool must not be mistaken for', async () => {
    for (const module of modules) {
      const { container, unmount } = render(
        await ModulePage({ params: Promise.resolve({ slug: module.slug }) }),
      );
      expect((container.textContent ?? '').replace(/\s+/g, ' '), module.slug).toContain(
        module.limitation.replace(/\s+/g, ' '),
      );
      unmount();
    }
  });

  /**
   * The specific misreadings the brief names, each pinned to the module that
   * could produce it. A generic "results need review" line on every page would
   * satisfy a laxer test and would not stop the contract module reading as
   * legal review.
   */
  it.each([
    ['contract_assistant', /does not replace review by a qualified lawyer/i],
    ['contract_assistant', /OCR is not enabled/i],
    ['inventory_predictor', /not a statement of what will happen/i],
    ['interview_coach', /do not predict how any interview will go/i],
    ['supplier_risk_copilot', /no live news, financial, credit, sanctions or ESG feed/i],
    ['supplier_recommendation', /no external supplier, financial, credit or news data source/i],
    ['blueprint_generator', /not a validated implementation design/i],
    ['test_case_generator', /has not been executed against any SAP system/i],
    ['invoice_validator', /a suggestion for a person to approve/i],
    ['spend_analytics', /not money saved/i],
    ['po_risk', /not an audit/i],
  ])('%s states its own boundary', (id, pattern) => {
    const module = modules.find((entry) => entry.id === id);
    expect(module, id).toBeDefined();
    expect(module!.limitation, id).toMatch(pattern);
  });

  it('keeps the human-review requirement on the pages a reader lands on', () => {
    for (const [name, Page] of [
      ['home', HomePage],
      ['how it works', HowItWorksPage],
      ['terms', TermsPage],
      ['about', AboutPage],
      ['demo disclaimer', DemoDisclaimerPage],
    ] as const) {
      expect(textOf(Page), name).toMatch(/(qualified person|human review|review by a qualified)/i);
    }
  });

  /**
   * The fictional-data statement reaches every page through the footer, which
   * the layout renders around all of them - so the footer is where to assert
   * it. Requiring the word on each page body instead failed on the contact
   * page, which is about how to send an email and has no business discussing
   * sample data; that assertion would have been satisfied by padding the page
   * with a sentence nobody needed.
   */
  it('carries the fictional-data statement in the footer, on every page', () => {
    const { container } = render(<Footer />);
    const footer = (container.textContent ?? '').replace(/\s+/g, ' ');
    expect(footer).toContain(DEMO_NOTICE);
    expect(footer).toMatch(/fictional/i);
    expect(footer).toMatch(/not endorsed by, certified by/i);
  });

  it('describes itself as a demonstration on every page body', async () => {
    for (const [name, text] of await everyPageText()) {
      expect(text, name).toMatch(/demonstration/i);
    }
  });

  it('keeps the sensitive-information warning where a visitor can act on it', () => {
    for (const [name, Page] of [
      ['demo disclaimer', DemoDisclaimerPage],
      ['privacy', PrivacyPage],
      ['terms', TermsPage],
      ['home', HomePage],
    ] as const) {
      const body = textOf(Page);
      expect(body, name).toMatch(/confidential/i);
      expect(body, name).toMatch(/personal/i);
    }
  });

  it('names the mix of methods rather than implying one of them everywhere', () => {
    const body = textOf(DemoDisclaimerPage);
    expect(body).toMatch(/deterministic/i);
    expect(body).toMatch(/statistical estimates/i);
    expect(body).toMatch(/mock AI/i);
    expect(body).toMatch(/generated/i);
  });
});

/**
 * Render inside a fully-configured contact deployment, then restore.
 *
 * Every variable `readContactConfig()` requires has to be present, because the
 * readiness check is all-or-nothing by design - setting only the flag would
 * exercise the fail-closed path and silently assert the wrong branch.
 */
function withContactFormEnabled(body: () => void): void {
  const vars = {
    CONTACT_FORM_ENABLED: 'true',
    CONTACT_RECIPIENT_EMAIL: 'someone@example.com',
    SMTP_HOST: 'smtp.example.com',
    SMTP_PORT: '587',
    SMTP_USER: 'someone@example.com',
    SMTP_APP_PASSWORD: 'not-a-real-password',
    TURNSTILE_SECRET_KEY: '1x0000000000000000000000000000000AA',
    CONTACT_RATE_LIMIT_SECRET: 'test-secret',
    NEXT_PUBLIC_TURNSTILE_SITE_KEY: '1x00000000000000000000AA',
  };
  const previous = new Map(
    Object.keys(vars).map((key) => [key, process.env[key]] as const),
  );
  Object.assign(process.env, vars);
  try {
    body();
  } finally {
    for (const [key, value] of previous) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
}

describe('the official contact address survives this change', () => {
  it('is still the configured address, and still reachable from the legal pages', () => {
    expect(siteConfig.contactEmail).toBe('solveaihub@gmail.com');
    for (const [name, Page] of [
      ['privacy', PrivacyPage],
      ['terms', TermsPage],
      ['contact', ContactPage],
    ] as const) {
      expect(textOf(Page), name).toContain('solveaihub@gmail.com');
    }
  });

  /**
   * The privacy policy must describe the deployment it is served from, and the
   * contact form is the one feature on this site that can be present or absent
   * at run time. That makes a *pair* of failures possible, and only asserting
   * one direction catches half of them:
   *
   * * the policy documents a form the deployment does not serve - the original
   *   failure this test was written for;
   * * the deployment serves a form the policy still denies exists - which is
   *   the worse of the two, because it is a false statement about data
   *   handling rather than a stale one.
   *
   * Both pages read the same `isContactFormAvailable()` the endpoint does, so
   * stubbing the environment is what proves they cannot disagree with it.
   */
  describe('the privacy policy matches whether the form actually shipped', () => {
    it('denies the form when it is off, and mentions no captcha', () => {
      // The default. No CONTACT_FORM_ENABLED anywhere in the test environment.
      const body = `${textOf(PrivacyPage)} ${textOf(TermsPage)}`;
      expect(body).not.toMatch(/turnstile|recaptcha|captcha/i);
      expect(body).not.toMatch(/when you submit the (contact )?form/i);
      expect(body).not.toMatch(/the contact form (collects|stores|sends)/i);
      expect(textOf(PrivacyPage)).toMatch(/There is no contact form on this site/i);
      expect(textOf(ContactPage)).toMatch(/Why there is no contact form/i);
    });

    it('describes the form, and stops denying it, when it is fully configured', () => {
      withContactFormEnabled(() => {
        const privacy = textOf(PrivacyPage);

        // The denial is gone - this is the assertion that catches a policy
        // left behind by an operator switching the form on.
        expect(privacy).not.toMatch(/There is no contact form on this site/i);
        expect(textOf(ContactPage)).not.toMatch(/Why there is no contact form/i);

        // And what replaced it states the things a reader has to be told.
        expect(privacy).toMatch(/turnstile/i);
        expect(privacy).toMatch(/when you submit the form/i);
        expect(privacy).toMatch(/gmail/i);
        expect(privacy).toMatch(/cloudflare/i);
        // No storage claim, positively stated.
        expect(privacy).toMatch(/writes no copy/i);
      });
    });

    /**
     * The policy promises the message is not stored and that the address is
     * kept only as a keyed fingerprint. A policy that says so while the page
     * quietly claims something softer is the same pair of fields disagreeing.
     */
    it('does not claim the raw address is retained', () => {
      withContactFormEnabled(() => {
        const privacy = textOf(PrivacyPage);
        expect(privacy).toMatch(/not retained|never written to disk|lost when the server restarts/i);
      });
    });
  });
});
