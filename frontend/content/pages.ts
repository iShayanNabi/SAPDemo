/**
 * The public marketing pages, and what each one says it is.
 *
 * One registry, read by three things that used to be maintained separately and
 * therefore used to disagree:
 *
 * * each page's `export const metadata`, through `pageMetadata()`;
 * * `app/sitemap.ts`, so a page cannot be published without being listed and a
 *   route cannot be listed without existing;
 * * the tests, which assert every title and description is unique - a check
 *   that is only possible because there is one list to check.
 *
 * The `title` here is the *segment*: `app/layout.tsx` appends the product name
 * through `title.template`, and `lib/metadata.ts` appends the same suffix to
 * the social card. Writing the suffix out per page would put "Procurement
 * Intelligence Demo" in eleven places and let one of them drift.
 *
 * A description is a sentence a search result shows to somebody deciding
 * whether to click. It says what the page contains, not what the project is -
 * eleven pages all describing the project is eleven identical results.
 */

export const PAGE_PATHS = [
  '/',
  '/platform',
  '/tools',
  '/how-it-works',
  '/architecture',
  '/services',
  '/about',
  '/contact',
  '/demo-disclaimer',
  '/privacy',
  '/terms',
] as const;

export type PagePath = (typeof PAGE_PATHS)[number];

export interface PageDefinition {
  path: PagePath;
  /** The title segment. The product name is appended by the template. */
  title: string;
  /** The full title, for the one page that is the product name. */
  absoluteTitle?: string;
  description: string;
  /**
   * True when the page is only published if `SERVICES_PAGE_ENABLED` is on. The
   * navigation, the footer and the sitemap all follow the same switch, so a
   * page that is not linked is not advertised to a crawler either.
   */
  requiresServicesPage?: boolean;
}

export const pages: Record<PagePath, PageDefinition> = {
  '/': {
    path: '/',
    title: 'Home',
    absoluteTitle: 'Procurement Intelligence Demo by Solve AI Hub',
    description:
      'Ten procurement and supply-chain demonstration tools running on fictional SAP-style ' +
      'data. Deterministic calculations and business rules do the deciding; AI writes the ' +
      'explanations, and every result says which produced it.',
  },
  '/platform': {
    path: '/platform',
    title: 'Platform overview',
    description:
      'The shape of the application behind the demonstration: a FastAPI backend of ten ' +
      'modules with their own rules and configuration, one shared services layer, and an ' +
      'interface that holds no business logic of its own.',
  },
  '/tools': {
    path: '/tools',
    title: 'The ten tools',
    description:
      'Every tool in the demonstration, from purchase order risk and spend analytics to ' +
      'inventory forecasting, blueprint drafting and interview coaching - with what each one ' +
      'takes in, what it returns and what it must not be mistaken for.',
  },
  '/how-it-works': {
    path: '/how-it-works',
    title: 'How it works',
    description:
      'The path a dataset takes from arriving to being a labelled result: validation, column ' +
      'mapping, configured rules, statistical models, and the five origin labels that ' +
      'separate a calculated figure from a sentence a model wrote.',
  },
  '/architecture': {
    path: '/architecture',
    title: 'Architecture',
    description:
      'How this is deployed: a public Next.js website and a Streamlit demonstration behind ' +
      'Cloudflare Access, reached through an outbound Cloudflare Tunnel, with a FastAPI ' +
      'backend and a PostgreSQL database that are never published.',
  },
  '/services': {
    path: '/services',
    title: 'Consulting services',
    requiresServicesPage: true,
    description:
      'SAP-focused consulting: procurement and supply-chain analysis, deterministic rule ' +
      'engines with configurable thresholds, document extraction with citations, and ' +
      'pragmatic use of language models where they genuinely help.',
  },
  '/about': {
    path: '/about',
    title: 'About',
    description:
      'Why this project exists and the principles it follows: deterministic calculation, ' +
      'labelled output origins, documented fictional data, and honest statements about what ' +
      'has not been built or validated.',
  },
  '/contact': {
    path: '/contact',
    title: 'Contact',
    description:
      'How to get in touch: consulting enquiries, questions about how a module calculates ' +
      'something, and requests for access to the protected interactive demonstration.',
  },
  '/demo-disclaimer': {
    path: '/demo-disclaimer',
    title: 'Demonstration disclaimer',
    description:
      'What the interactive demonstration is, the fictional data it runs on, the mock AI ' +
      'provider it uses, and the information you must not enter into it.',
  },
  '/privacy': {
    path: '/privacy',
    title: 'Privacy',
    description:
      'What this website and the interactive demonstration do with information: operational ' +
      'logging, the Cloudflare services in front of them, email contact, and the current ' +
      'disabled upload state.',
  },
  '/terms': {
    path: '/terms',
    title: 'Terms and disclaimer',
    description:
      'Terms of use for this website and the interactive demonstration: what the outputs are ' +
      'and are not, what may not be submitted, the professional advice this does not ' +
      'constitute, and what is not claimed.',
  },
};

/** The registry as a list, in navigation order. */
export const pageList: readonly PageDefinition[] = PAGE_PATHS.map((path) => pages[path]);

/**
 * The pages a given deployment actually publishes.
 *
 * Takes the flag as an argument rather than reading the environment, for the
 * same reason `getNavItems` does: the server resolves it once and every
 * consumer receives the identical list.
 */
export function publishedPages(servicesPageEnabled: boolean): readonly PageDefinition[] {
  return pageList.filter((page) => !page.requiresServicesPage || servicesPageEnabled);
}
