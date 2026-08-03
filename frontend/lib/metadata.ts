/**
 * One place that decides what every page's metadata says.
 *
 * Before this module each page hand-wrote a `Metadata` object, and the objects
 * had drifted in the way hand-written duplicates always do: some carried an
 * `openGraph` block and some did not, the root layout declared
 * `alternates: { canonical: '/' }` which every page without its own canonical
 * silently inherited - so a 404 and an unknown tool slug both announced
 * themselves as the home page - and the Twitter card was `summary`, which shows
 * a thumbnail rather than the wide preview the social image is drawn for.
 *
 * The rule here is that a page supplies **facts** - its path, its title, its
 * description - and this module derives every tag from them. A page cannot
 * forget a canonical, cannot invent a second one, and cannot disagree with the
 * sitemap, because all three read the same registry in `content/pages.ts`.
 */

import type { Metadata } from 'next';
import { type PagePath, pages } from '@/content/pages';
import type { ModuleContent } from '@/content/modules';
import { PUBLIC_ORIGIN, siteConfig } from '@/lib/site';

/**
 * Hostnames that are never a canonical URL, whatever the environment says.
 *
 * A canonical URL is a claim about where a page really lives, so the failure
 * mode is not a broken link somebody notices - it is a search engine being told
 * to index an address it cannot reach, or to merge the public site into a
 * hostname that is not public. Three sources of a wrong value are real in this
 * repository rather than hypothetical:
 *
 * * `docker-compose.debug.yml` sets `NEXT_PUBLIC_SITE_URL` to
 *   `http://127.0.0.1:3000` by default;
 * * `docker-compose.selfhosted.yml` writes `${PUBLIC_SITE_URL:-}`, so an unset
 *   variable arrives as a blank that `siteConfig.url` has already defaulted;
 * * a Docker service name (`website`) is a single label with no dot, and would
 *   be accepted by `new URL()` without complaint.
 *
 * `demo.` is on the list for a different reason: it resolves, it is public in
 * the DNS sense, and it is the Streamlit demonstration behind Cloudflare
 * Access. Advertising a marketing canonical there points crawlers at a login.
 */
const NON_PUBLIC_FIRST_LABELS = new Set(['demo', 'staging', 'preview', 'localhost', 'test']);

/**
 * The configured origin, reduced to the one form every canonical uses - or
 * `null` when it is not an address the public can reach.
 *
 * Returning `null` rather than a corrected guess is deliberate: the caller
 * falls back to `PUBLIC_ORIGIN`, which is a known-correct answer, instead of
 * this function inventing one from a value it has already decided to distrust.
 */
export function normalizePublicOrigin(value: string): string | null {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return null;
  }

  // Not a `NODE_ENV` branch, and not "https unless developing": the public site
  // is served through a Cloudflare tunnel and is always TLS, so an `http:`
  // canonical is either a mistake or a loopback address.
  if (parsed.protocol !== 'https:') {
    return null;
  }

  const host = parsed.hostname.toLowerCase();
  // An IPv4 or IPv6 literal is never the address a visitor typed.
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(host) || host.startsWith('[')) {
    return null;
  }
  // A single label with no dot is a Docker service name, not a domain.
  const labels = host.split('.');
  if (labels.length < 2) {
    return null;
  }
  if (NON_PUBLIC_FIRST_LABELS.has(labels[0] ?? '')) {
    return null;
  }
  if (host.endsWith('.local') || host.endsWith('.localhost') || host.endsWith('.internal')) {
    return null;
  }

  // `www` and the bare domain serve the same pages. One of them has to be the
  // canonical one, and it is the bare domain.
  const canonicalHost = host.startsWith('www.') ? host.slice(4) : host;
  const port = parsed.port ? `:${parsed.port}` : '';
  return `https://${canonicalHost}${port}`;
}

/**
 * The origin every canonical URL, Open Graph URL and sitemap entry is built
 * from. Resolved once, at module load, from the configured value.
 */
export const canonicalOrigin: string =
  normalizePublicOrigin(siteConfig.url) ?? PUBLIC_ORIGIN;

/**
 * A path reduced to the single form it is allowed to be canonical as.
 *
 * Query strings are dropped rather than preserved, and that is the whole point
 * of this function existing: `/contact?service=consulting` is the Services
 * page's call to action, it is the same page as `/contact`, and a canonical
 * carrying the parameter would split one page into two in an index. The
 * trailing slash goes for the same reason - `/about` and `/about/` are one
 * page, and only one of them may be named.
 */
export function canonicalPath(path: string): string {
  const withoutQuery = path.split(/[?#]/)[0] ?? '';
  const withLeadingSlash = withoutQuery.startsWith('/') ? withoutQuery : `/${withoutQuery}`;
  const collapsed = withLeadingSlash.replace(/\/{2,}/g, '/');
  const trimmed = collapsed.replace(/\/+$/, '');
  return trimmed === '' ? '/' : trimmed;
}

/** An absolute public URL for a path on this site. */
export function canonicalUrl(path: string): string {
  const normalized = canonicalPath(path);
  return normalized === '/' ? `${canonicalOrigin}/` : `${canonicalOrigin}${normalized}`;
}

/**
 * The browser title for a page, spelled out rather than left to the template.
 *
 * `app/layout.tsx` declares `title.template`, which Next applies to the `<title>`
 * element. It does not apply it to `og:title`, so a social preview built from
 * the bare segment would read "About" with no indication of what it is about.
 * Both are derived here from the same pair, so they cannot drift.
 */
export const TITLE_SEPARATOR = ' — ';

export function pageTitle(segment: string): string {
  return `${segment}${TITLE_SEPARATOR}${siteConfig.name}`;
}

/**
 * The social preview image.
 *
 * `app/opengraph-image.tsx` renders the PNG and, through the Next file
 * convention, publishes it at this path. The tags, however, are written here
 * explicitly, and the reason is a failure that only showed up in the built
 * HTML: Next applies the file convention **only to pages that do not declare an
 * `openGraph` object of their own**. Every page routed through `buildMetadata`
 * declares one - it has to, for `og:url` and `og:site_name` - so the first
 * version of this module produced a home page with a preview image and ten
 * marketing pages and ten tool pages with none. Nothing failed; the pages were
 * simply unshareable.
 *
 * Declaring the image here fixes that and cannot double up, for the same reason
 * it broke: an explicit `openGraph.images` is what suppresses the convention's
 * own tag, so there is exactly one `og:image` per page either way.
 *
 * The dimensions live here because the image module reads them too - a declared
 * size that disagrees with the rendered one is a preview the platform crops.
 */
export const SOCIAL_IMAGE = {
  path: '/opengraph-image',
  width: 1200,
  height: 630,
  contentType: 'image/png',
  alt:
    'Procurement Intelligence Demo by Solve AI Hub — ten procurement and supply-chain ' +
    'demonstration tools running on fictional SAP-style data.',
} as const;

/** The absolute URL of the social preview image. */
export function socialImageUrl(): string {
  return canonicalUrl(SOCIAL_IMAGE.path);
}

export interface PageMetadataInput {
  /** The public path. Also the canonical, after normalization. */
  path: string;
  /**
   * The title segment. Combined with the product name unless `absoluteTitle`
   * is set - which only the home page does, because "Procurement Intelligence
   * Demo — Procurement Intelligence Demo" is what a template produces there.
   */
  title: string;
  /** The full title, verbatim, for the one page that needs no suffix. */
  absoluteTitle?: string;
  description: string;
  /** Overrides for the social card, where the page title is too terse to share. */
  socialTitle?: string;
  socialDescription?: string;
  /**
   * Keep the page out of search results. Used for the pages that exist but are
   * not destinations - a 404, an unknown tool slug.
   */
  noIndex?: boolean;
  /**
   * Suppress the canonical link entirely. A page that does not exist has no
   * canonical address, and inheriting the layout's would claim it is the home
   * page.
   */
  noCanonical?: boolean;
}

/**
 * Every tag a public page needs, derived from what the page knows about itself.
 */
export function buildMetadata(input: PageMetadataInput): Metadata {
  const fullTitle = input.absoluteTitle ?? pageTitle(input.title);
  const socialTitle = input.socialTitle ?? fullTitle;
  const socialDescription = input.socialDescription ?? input.description;
  const url = canonicalUrl(input.path);
  const image = {
    url: socialImageUrl(),
    width: SOCIAL_IMAGE.width,
    height: SOCIAL_IMAGE.height,
    alt: SOCIAL_IMAGE.alt,
    type: SOCIAL_IMAGE.contentType,
  };

  return {
    title: input.absoluteTitle ? { absolute: input.absoluteTitle } : input.title,
    description: input.description,
    alternates: input.noCanonical ? undefined : { canonical: url },
    openGraph: {
      type: 'website',
      // The publisher, not the product: the product name is already the whole
      // of `og:title`, and a preview repeating it twice reads as a stutter.
      siteName: siteConfig.parentBrand,
      title: socialTitle,
      description: socialDescription,
      url,
      locale: 'en_GB',
      images: [image],
    },
    twitter: {
      // `summary_large_image`, not `summary`. The preview image is drawn at
      // 1200×630 for the wide card; `summary` crops it to a square thumbnail
      // and the wordmark disappears.
      card: 'summary_large_image',
      title: socialTitle,
      description: socialDescription,
      images: [{ url: image.url, alt: image.alt }],
    },
    robots: input.noIndex
      ? { index: false, follow: true }
      : { index: true, follow: true },
  };
}

/**
 * The metadata for one of the registered marketing pages.
 *
 * A page writes `export const metadata = pageMetadata('/about')` and nothing
 * else. The argument is typed as `PagePath`, so a path that is not in the
 * registry - a typo, or a page somebody added without listing it - fails to
 * compile rather than shipping a page the sitemap does not know about.
 */
export function pageMetadata(path: PagePath): Metadata {
  const page = pages[path];
  return buildMetadata({
    path: page.path,
    title: page.title,
    absoluteTitle: page.absoluteTitle,
    description: page.description,
  });
}

/**
 * A description for a tool page, built from the copy the page already renders.
 *
 * The tagline says what the tool does and the first sentence of the business
 * problem says who has that problem, which between them is what somebody
 * reading a search result wants. Taking the *whole* problem paragraph and
 * truncating it - which is what this used to do, with `.slice(0, 300)` - cut
 * mid-word and mid-clause, and the visible half of a sentence about what goes
 * wrong reads like a claim that it does.
 */
export function toolDescription(module: ModuleContent): string {
  const [firstSentence] = module.problem.split(/(?<=\.)\s+/);
  return `${module.tagline} ${firstSentence ?? ''}`.trim();
}

/**
 * The metadata for one tool page.
 *
 * Generated from the same typed module content the page body renders, so ten
 * pages get ten distinct titles, descriptions and canonicals without ten
 * hand-written objects - and adding an eleventh module cannot produce a page
 * that shares the tenth's canonical.
 */
export function toolMetadata(module: ModuleContent): Metadata {
  return buildMetadata({
    path: `/tools/${module.slug}`,
    title: module.name,
    description: toolDescription(module),
    socialDescription: module.tagline,
  });
}

/**
 * The metadata for a page that does not exist.
 *
 * `noIndex` because there is nothing here to find, and `noCanonical` because
 * the alternative is worse than none: without it the page inherits the root
 * layout's canonical and every mistyped address on the site announces itself
 * as the home page.
 */
export const NOT_FOUND_METADATA: Metadata = buildMetadata({
  path: '/',
  title: 'Page not found',
  description:
    'This address does not match a page on this site. The tools overview lists all ten ' +
    'demonstration modules, and the contact page is the way to report a broken link.',
  noIndex: true,
  noCanonical: true,
});
