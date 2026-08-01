/**
 * Site-wide configuration.
 *
 * Everything a deployment has to change lives here and reads from the
 * environment. Nothing here is a secret: `NEXT_PUBLIC_*` values are compiled
 * into the browser bundle by definition, so only public addresses belong in
 * this file - a hostname, an email address, a repository URL. Anything that
 * needs protecting must never reach this module.
 *
 * The defaults are placeholders on purpose. A site that ships with a real
 * domain baked in is a site that quietly links somewhere wrong the first time
 * it is deployed under a different one.
 */

export const siteConfig = {
  name: 'SAPDemo',
  /** Used in the tab title and the JSON-LD name. */
  title: 'SAPDemo — SAP-focused demonstration platform',
  shortDescription:
    'Ten procurement and supply-chain demonstration tools built on deterministic Python, running on fictional data.',
  description:
    'SAPDemo is an SAP-focused demonstration platform: ten procurement and supply-chain ' +
    'tools that analyse fictional SAP-style data with transparent, deterministic logic. ' +
    'Every calculation is ordinary code; AI only explains results. Not affiliated with SAP.',

  /** The public site address. Used for canonical URLs and Open Graph. */
  url: process.env.NEXT_PUBLIC_SITE_URL ?? 'http://localhost:3000',

  /**
   * Where every Launch Demo call to action points. Configured rather than
   * hardcoded so the same image serves a local run and a published one.
   */
  demoUrl: process.env.NEXT_PUBLIC_DEMO_URL ?? 'http://localhost:8501',

  /**
   * Contact is a `mailto:` link, deliberately. A public contact form needs an
   * endpoint that accepts unauthenticated writes from the internet, and this
   * project is not adding one - see docs/DEMO_SECURITY_CHECKLIST.md.
   */
  contactEmail: process.env.NEXT_PUBLIC_CONTACT_EMAIL ?? 'contact@example.com',

  repositoryUrl:
    process.env.NEXT_PUBLIC_REPOSITORY_URL ?? 'https://github.com/iShayanNabi/SAPDemo',

  /** Shown in the footer. Kept as a placeholder until a real one is supplied. */
  locationLabel: process.env.NEXT_PUBLIC_LOCATION_LABEL ?? '',
} as const;

/**
 * The standing statement about what this platform is and is not.
 *
 * SAP is a third-party trademark. Nothing on this site claims endorsement,
 * certification, sponsorship, partnership or affiliation, and this sentence is
 * rendered on every page so the claim cannot be lost by navigating.
 */
export const TRADEMARK_NOTICE =
  'SAP and other SAP product names are trademarks of SAP SE or its affiliates. ' +
  `${siteConfig.name} is an independent demonstration project and is not endorsed by, ` +
  'certified by, sponsored by, partnered with or affiliated with SAP.';

export const DEMO_NOTICE =
  'Every figure, supplier, purchase order, invoice and contract in this project is fictional ' +
  'sample data generated for demonstration. Nothing is connected to a live SAP system, and no ' +
  'output has been validated in one.';

export function mailto(subject: string): string {
  return `mailto:${siteConfig.contactEmail}?subject=${encodeURIComponent(subject)}`;
}
