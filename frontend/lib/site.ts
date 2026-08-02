/**
 * Site-wide public configuration.
 *
 * Everything a deployment has to change lives here and reads from the
 * environment. Nothing here is a secret: `NEXT_PUBLIC_*` values are compiled
 * into the browser bundle by definition, so only public addresses belong in
 * this file - a hostname, an email address, a repository URL. Anything that
 * needs protecting must never reach this module.
 *
 * The address defaults are placeholders on purpose. A site that ships with a
 * real domain baked in is a site that quietly links somewhere wrong the first
 * time it is deployed under a different one. The *contact* default is the
 * exception and is deliberately the real address: a placeholder recipient that
 * escapes into a build is a visitor writing to nobody, which is worse than a
 * link pointing at localhost that anyone can see is unconfigured.
 */

/**
 * Read a build-time value, treating blank as absent.
 *
 * This exists because `??` is the wrong operator here and the difference is
 * invisible until deployment. Nullish coalescing falls back on `undefined` and
 * `null` only - never on `''` - and the empty string is exactly what this
 * project's deployment path supplies. `docker-compose.selfhosted.yml` declares
 * `NEXT_PUBLIC_SITE_URL: ${PUBLIC_SITE_URL:-}`, whose `:-` default is `''`, and
 * the Dockerfile's `ARG NEXT_PUBLIC_SITE_URL=""` does the same. So a variable
 * that is merely unset in `.env.selfhosted` arrives as a defined empty string,
 * every `??` default below is skipped, and each value fails differently:
 *
 * * `url` reaches `new URL('')` in `app/layout.tsx`, which throws
 *   `ERR_INVALID_URL` and fails `next build` with an error naming neither the
 *   variable nor the file - it reports "Failed to collect page data for
 *   /contact";
 * * `demoUrl` renders every Launch Demo button as `href=""`, which reloads the
 *   current page instead of opening the demonstration - a page that looks
 *   perfect in every automated check and links nowhere;
 * * `contactEmail` renders `mailto:?subject=...`, with no recipient.
 *
 * Trimming as well as checking for empty is deliberate: a value that is a
 * single space came from a hand-edited environment file, and honouring it would
 * produce the same three failures with a character that does not show up in a
 * diff.
 */
function fromEnv(value: string | undefined, fallback: string): string {
  const trimmed = value?.trim();
  return trimmed ? trimmed : fallback;
}

/**
 * Read a value that is genuinely allowed to be absent, and say so as `null`.
 *
 * `fromEnv` answers "what should this be when nobody configured it". Some
 * values have no sensible answer to that, and the repository URL is the one
 * that matters here: this project's repository is private, so the honest
 * default is *no link at all*. Returning `''` would be worse than useless -
 * `href=""` is a valid anchor that silently reloads the current page - so the
 * absent case is a distinct type the caller has to handle.
 *
 * Missing, blank and whitespace-only all collapse to the same `null`, for the
 * same reason `fromEnv` trims: they all arrive through Docker, and they all
 * mean "nobody set this".
 */
function optionalFromEnv(value: string | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

/**
 * A repository URL is only usable if it is an absolute http(s) address.
 *
 * A half-configured value (`github.com/owner/repo` with no scheme, or a stray
 * shell fragment) would otherwise be rendered as a relative link inside this
 * site. Rejecting it falls back to the same behaviour as no value at all,
 * which is the safe direction: the link disappears rather than pointing
 * somewhere wrong.
 */
function optionalUrlFromEnv(value: string | undefined): string | null {
  const candidate = optionalFromEnv(value);
  if (!candidate) {
    return null;
  }
  try {
    const parsed = new URL(candidate);
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? candidate : null;
  } catch {
    return null;
  }
}

/**
 * Read a boolean switch, defaulting to on.
 *
 * Only `false`/`0`/`no`/`off` turn a feature off. Anything else - including
 * blank, which is what an unset Docker variable supplies - leaves it on, so a
 * page cannot vanish from the public site because an environment file was not
 * filled in.
 */
function flagFromEnv(value: string | undefined, fallback: boolean): boolean {
  const trimmed = value?.trim().toLowerCase();
  if (!trimmed) {
    return fallback;
  }
  return !['false', '0', 'no', 'off'].includes(trimmed);
}

export const siteConfig = {
  /** The product. What the site is about. */
  name: 'Procurement Intelligence Demo',
  /** The parent brand the product is published under. */
  parentBrand: 'Solve AI Hub',
  /** The two together, for legal statements and the browser title. */
  fullName: 'Procurement Intelligence Demo by Solve AI Hub',
  /** Used in the tab title and the JSON-LD name. */
  title: 'Procurement Intelligence Demo by Solve AI Hub',
  shortDescription:
    'Ten procurement and supply-chain demonstration tools built on deterministic Python, running on fictional data.',
  description:
    'Procurement Intelligence Demo by Solve AI Hub is an SAP-focused demonstration platform: ' +
    'ten procurement and supply-chain tools that analyse fictional SAP-style data with ' +
    'transparent, deterministic logic. Every calculation is ordinary code; AI only explains ' +
    'results. Not affiliated with SAP.',

  /** The public site address. Used for canonical URLs and Open Graph. */
  url: fromEnv(process.env.NEXT_PUBLIC_SITE_URL, 'http://localhost:3000'),

  /**
   * Where every Launch Demo call to action points. Configured rather than
   * hardcoded so the same image serves a local run and a published one.
   */
  demoUrl: fromEnv(process.env.NEXT_PUBLIC_DEMO_URL, 'http://localhost:8501'),

  /**
   * The single public contact address, used by every `mailto:` on the site.
   *
   * Contact is a `mailto:` link, deliberately. A public contact form needs an
   * endpoint that accepts unauthenticated writes from the internet, and this
   * project is not adding one - see docs/DEMO_SECURITY_CHECKLIST.md.
   */
  contactEmail: fromEnv(process.env.NEXT_PUBLIC_CONTACT_EMAIL, 'solveaihub@gmail.com'),

  /**
   * The public source repository, or `null` when there is not one.
   *
   * This project's repository is private, so the deployed configuration leaves
   * this unset and every "Source on GitHub", "View source" and repository
   * reference on the site disappears with it. Setting a valid URL brings them
   * all back; nothing else has to change.
   */
  repositoryUrl: optionalUrlFromEnv(process.env.NEXT_PUBLIC_REPOSITORY_URL),

  /**
   * Whether the consulting Services page is linked from the site.
   *
   * Read server-side (it is not a `NEXT_PUBLIC_*` variable, so it never reaches
   * the browser bundle) and passed down to the navigation as data. That is why
   * `Nav` takes its links as a prop rather than importing them: a client
   * component reading this would always see the default and disagree with the
   * server that rendered around it.
   */
  servicesPageEnabled: flagFromEnv(process.env.SERVICES_PAGE_ENABLED, true),

  /**
   * Shown in the footer. Kept as a placeholder until a real one is supplied.
   *
   * Goes through `fromEnv` with a blank fallback so the next person to give it
   * a real default does not have to notice that this line was the exception.
   */
  locationLabel: fromEnv(process.env.NEXT_PUBLIC_LOCATION_LABEL, ''),
} as const;

/** True when a public repository is configured and every source link may render. */
export const hasRepository: boolean = siteConfig.repositoryUrl !== null;

/**
 * The repository URL as a human-readable label - `github.com/owner/repo`.
 *
 * Returns `null` in exactly the cases `repositoryUrl` does, so a caller cannot
 * render a label for a link that is not there.
 */
export function repositoryLabel(): string | null {
  if (!siteConfig.repositoryUrl) {
    return null;
  }
  return siteConfig.repositoryUrl.replace(/^https?:\/\//, '').replace(/\/$/, '');
}

/**
 * The standing statement about what this platform is and is not.
 *
 * SAP is a third-party trademark. Nothing on this site claims endorsement,
 * certification, sponsorship, partnership or affiliation, and this sentence is
 * rendered on every page so the claim cannot be lost by navigating.
 */
export const TRADEMARK_NOTICE =
  'SAP and other SAP product names are trademarks of SAP SE or its affiliates. ' +
  `${siteConfig.fullName} is an independent demonstration project and is not endorsed by, ` +
  'certified by, sponsored by, partnered with or affiliated with SAP.';

export const DEMO_NOTICE =
  'Every figure, supplier, purchase order, invoice and contract in this project is fictional ' +
  'sample data generated for demonstration. Nothing is connected to a live SAP system, and no ' +
  'output has been validated in one.';

export function mailto(subject: string): string {
  return `mailto:${siteConfig.contactEmail}?subject=${encodeURIComponent(subject)}`;
}
